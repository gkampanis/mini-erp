"""Application-level browser egress guard, not an OS network sandbox.

Every HTTP response is relayed with a bounded read before Chromium receives it.
GET document redirects become fresh guarded navigations; other redirects fail closed.
No environment proxy or APIRequestContext (which buffers bodies) is used.
"""
import asyncio
import json
import threading
import time
import socket
import ipaddress
from http.client import HTTPSConnection
from urllib.parse import urlsplit
from urllib.parse import urljoin
from .pdf_downloads import MAX_BYTES, Pending, validate_url


class TransferStop:
    def __init__(self, *events):
        self.events=events
    def is_set(self):
        return any(event is not None and event.is_set() for event in self.events)


def check_transfer(stop, deadline):
    if (stop is not None and stop.is_set()) or time.monotonic() >= deadline:
        raise Pending('browser_timeout')


class BrowserPolicy:
    def __init__(self):
        self.stop=threading.Event()
        self.cancel=None
        self.deadline=float('inf')
        self.error=None
        self.generation=0
    def begin(self,cancel,deadline):
        self.cancel,self.deadline,self.error=cancel,deadline,None
        self.generation+=1
    def raise_if_failed(self):
        if self.error:raise Pending(self.error)


def read_bounded(stream, headers, limit=MAX_BYTES, *, stop=None, deadline=None):
    deadline=time.monotonic()+30 if deadline is None else deadline
    check_transfer(stop,deadline)
    # Refuse content coding: the browser would otherwise decompress an unbounded
    # expansion after this wire-byte check. Ask providers for identity below.
    if headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
        raise Pending('browser_download_failed')
    length=headers.get('content-length','')
    if length.isdigit() and int(length)>limit:
        raise Pending('too_large')
    chunks=[];size=0
    while True:
        check_transfer(stop,deadline)
        # HTTPResponse.read(n) can wait for n bytes under a slow trickle.
        chunk=getattr(stream,'read1',stream.read)(min(65536,limit-size+1))
        check_transfer(stop,deadline)
        if not chunk:break
        size+=len(chunk)
        if size>limit:raise Pending('too_large')
        chunks.append(chunk)
    return b''.join(chunks)


def public_endpoints(url):
    try:
        parts=urlsplit(url)
        if (parts.scheme!='https' or not parts.hostname or parts.username or parts.password
                or parts.port not in (None,443) or any(ord(c)<33 for c in url)):
            raise ValueError()
        addresses=socket.getaddrinfo(parts.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
        return parts,addresses
    except socket.gaierror:raise Pending('network_error') from None
    except (ValueError,OSError):raise Pending('unsafe_url') from None


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self,hostname,addresses,stop,deadline):
        super().__init__(hostname,443,timeout=5)
        self.addresses,self.stop,self.deadline=addresses,stop,deadline
    def connect(self):
        # Connect to the exact validated sockaddr, preserving certificate checks
        # and TLS SNI against the provider hostname. No second DNS lookup occurs.
        last=None
        for family,kind,protocol,_,address in self.addresses:
            check_transfer(self.stop,self.deadline)
            raw=socket.socket(family,kind,protocol)
            raw.settimeout(5)
            self.sock=raw
            try:
                raw.connect(address)
                check_transfer(self.stop,self.deadline)
                self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
                return
            except OSError as error:
                last=error;raw.close();self.sock=None
        if last:raise last
        raise Pending('network_error')


def relay_request(url, method, headers, body, *, stop=None, deadline=None):
    deadline=min(deadline or float('inf'),time.monotonic()+30)
    check_transfer(stop,deadline)
    parts,addresses=public_endpoints(url)
    check_transfer(stop,deadline)
    headers={key:value for key,value in headers.items()
             if key.lower() not in ('host','connection','content-length','accept-encoding')}
    headers['Accept-Encoding']='identity'
    if body and len(body)>MAX_BYTES:raise Pending('too_large')
    connection=PinnedHTTPSConnection(parts.hostname,addresses,stop,deadline)
    finished=threading.Event()
    def watchdog():
        while not finished.wait(.05):
            if (stop is not None and stop.is_set()) or time.monotonic()>=deadline:
                # shutdown interrupts a read even if a peer continuously trickles
                # headers; socket timeout alone only bounds individual recv calls.
                active_socket=connection.sock
                if active_socket is not None:
                    try:active_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                connection.close()
                return
    monitor=threading.Thread(target=watchdog,daemon=True)
    monitor.start()
    try:
        path=parts.path or '/'
        if parts.query:path+='?'+parts.query
        connection.connect()
        check_transfer(stop,deadline)
        connection.request(method,path,body=body,headers=headers)
        with connection.getresponse() as response:
            check_transfer(stop,deadline)
            response_headers={key.lower():value for key,value in response.headers.items()}
            data=read_bounded(response,response_headers,stop=stop,deadline=deadline)
            cookies=response.headers.get_all('Set-Cookie',[])
            for key in ('transfer-encoding','content-length','connection','set-cookie'):
                response_headers.pop(key,None)
            return response.status,response_headers,data,cookies
    finally:
        finished.set()
        connection.close()
        monitor.join(.1)


async def run_transport(function,*args,transfer_stop,transfer_deadline,**kwargs):
    # getaddrinfo cannot be interrupted portably. A daemon transport worker lets
    # cancellation return without Runner waiting on the default executor's DNS.
    # The worker checks stop immediately after DNS/connect before sending HTTP.
    check_transfer(transfer_stop,transfer_deadline)
    loop=asyncio.get_running_loop();future=loop.create_future()
    def deliver(value,error):
        if future.done():return
        if error is None:future.set_result(value)
        else:future.set_exception(error)
    def worker():
        try:value,error=function(*args,**kwargs),None
        except Exception as caught:value,error=None,caught
        try:loop.call_soon_threadsafe(deliver,value,error)
        except RuntimeError:pass
    threading.Thread(target=worker,daemon=True).start()
    try:
        while not future.done():
            check_transfer(transfer_stop,transfer_deadline)
            await asyncio.wait({future},timeout=.05)
        check_transfer(transfer_stop,transfer_deadline)
        return future.result()
    finally:
        if not future.done():future.cancel()
        elif not future.cancelled():future.exception()


async def install_browser_policy(context):
    """Install before creating/navigating pages, including persistent contexts."""
    if not callable(getattr(context,'route_web_socket',None)):
        raise Pending('browser_unavailable')
    policy=BrowserPolicy()
    if callable(getattr(context,'on',None)):
        context.on('close',lambda *args:policy.stop.set())
    async def websocket(socket):
        await socket.close(code=1008,reason='Browser capture does not use WebSockets')
    await context.route_web_socket('**/*',websocket)
    slots=asyncio.Semaphore(4)
    async def handle_route(route):
        generation=policy.generation
        try:
            request=route.request
            page_stop=threading.Event()
            try:
                owner=request.frame.page
                owner.on('close',lambda *args:page_stop.set())
                if owner.is_closed():page_stop.set()
            except (AttributeError,RuntimeError):pass
            stop=TransferStop(policy.stop,policy.cancel,page_stop)
            deadline=min(policy.deadline,time.monotonic()+30)
            await run_transport(validate_url,request.url,transfer_stop=stop,transfer_deadline=deadline)
            headers=await request.all_headers()
            status,response_headers,data,cookies=await run_transport(
                relay_request,request.url,request.method,headers,request.post_data_buffer,
                transfer_stop=stop,transfer_deadline=deadline,stop=stop,deadline=deadline)
            # Chromium does not re-run context routes for HTTP redirect followups.
            # Never hand it a redirect response. A GET document can safely begin
            # a fresh navigation; other redirect semantics are refused.
            if 300 <= status < 400 and 'location' in response_headers:
                target=urljoin(request.url,response_headers['location'])
                await run_transport(validate_url,target,transfer_stop=stop,transfer_deadline=deadline)
                if request.method != 'GET' or not request.is_navigation_request():
                    raise Pending('browser_download_failed')
                target_json=json.dumps(target).replace('<',chr(92)+'u003c')
                data=('<!doctype html><script>location.replace('+target_json+')</script>').encode()
                response_headers={'content-type':'text/html; charset=utf-8'}
                status=200
            # Chromium processes Set-Cookie on fulfilled responses. Repeated fields
            # use newline separation as supported by Playwright's header protocol.
            if cookies:response_headers['set-cookie']='\n'.join(cookies)
            await route.fulfill(status=status,headers=response_headers,body=data)
        except Pending as error:
            if generation==policy.generation:
                policy.error=error.state
            await route.abort('blockedbyclient')
        except Exception:
            await route.abort('blockedbyclient')
    async def route_request(route):
        async with slots:
            await handle_route(route)
    await context.route('**/*',route_request)
    return policy
