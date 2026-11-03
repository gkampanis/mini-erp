"""Bounded browser transport tests use synthetic responses, never network."""
import asyncio
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.infrastructure.providers.pdf_downloads import Pending


class BrowserPolicyTests(unittest.TestCase):
    def test_stream_stops_at_limit_without_trusting_content_length(self):
        from app.infrastructure.providers.browser_policy import read_bounded
        for headers in ({}, {'content-length':'1'}):
            stream=io.BytesIO(b'x'*100)
            with self.assertRaises(Pending) as raised:
                read_bounded(stream,headers,limit=8)
            self.assertEqual(raised.exception.state,'too_large')
            self.assertLessEqual(stream.tell(),9)

    def test_compressed_response_is_refused_before_read(self):
        from app.infrastructure.providers.browser_policy import read_bounded
        stream=io.BytesIO(b'compressed')
        with self.assertRaises(Pending):read_bounded(stream,{'content-encoding':'gzip'})
        self.assertEqual(stream.tell(),0)

    def test_context_policy_aborts_private_requests_before_transport(self):
        from app.infrastructure.providers.browser_policy import install_browser_policy
        class Context:
            async def route(self,pattern,handler):self.handler=handler
            async def route_web_socket(self,pattern,handler):self.socket_handler=handler
        class Route:
            request=SimpleNamespace(url='https://127.0.0.1/internal')
            aborted=False
            async def abort(self,*args):self.aborted=True
        async def check():
            context=Context();policy=await install_browser_policy(context)
            route=Route()
            with patch('app.infrastructure.providers.browser_policy.relay_request') as relay:
                await context.handler(route)
                relay.assert_not_called()
            self.assertTrue(route.aborted)
            self.assertEqual(policy.error,'unsafe_url')
        asyncio.run(check())

    def test_policy_fails_closed_without_websocket_routing(self):
        from app.infrastructure.providers.browser_policy import install_browser_policy
        with self.assertRaises(Pending):asyncio.run(install_browser_policy(SimpleNamespace()))

    def test_regular_context_blocks_workers_and_installs_policy(self):
        from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader
        class Context:
            async def route(self,*args):self.routed=True
            async def route_web_socket(self,*args):pass
        class Browser:
            async def new_context(self,**options):self.options=options;return Context()
        async def check():
            backend=BrowserPDFDownloader(None);backend.browser=Browser()
            context=await backend._new_context()
            self.assertEqual(backend.browser.options.get('service_workers'),'block')
            self.assertTrue(context.routed)
        asyncio.run(check())

    def test_blob_download_is_cancelled_without_save_as(self):
        from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader
        class Download:
            url='blob:https://example.com/id'
            cancelled=False
            async def cancel(self):self.cancelled=True
            async def save_as(self,*args):raise AssertionError('unbounded browser tempfile')
        async def check():
            download=Download()
            with self.assertRaises(Pending):
                await BrowserPDFDownloader(None)._download_event(download,None,None,None,None,0)
            self.assertTrue(download.cancelled)
        asyncio.run(check())

    def test_chromium_guards_redirects_frames_popups_resources_and_cookies(self):
        import socket
        from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader
        from app.infrastructure.providers.browser_recovery import RecoveryPDFDownloader
        import tempfile
        seen=[]
        def relay(url,method,headers,body,**kwargs):
            seen.append((url,headers))
            if url.endswith('/start'):
                return 302,{'location':'https://example.com/landing'},b'',[]
            if url.endswith('/landing'):
                return 200,{'content-type':'text/html'},b'''<html><body>
                  <iframe src="https://127.0.0.1/private-frame"></iframe>
                  <img src="https://127.0.0.1/private-image">
                  <script>fetch('/cookie');window.open('https://127.0.0.1/private-popup');
                  fetch('/redirect-private');
                  new WebSocket('wss://127.0.0.1/private-socket');</script>
                </body></html>''',['session=synthetic; Path=/; Secure; HttpOnly','other=fixture; Path=/; Secure']
            if url.endswith('/redirect-private'):
                return 302,{'location':'https://127.0.0.1/private-redirect'},b'',[]
            return 200,{'content-type':'text/plain'},b'ok',[]
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        async def check(backend):
            try:
                await backend._start()
                page=await backend.context.new_page()
                attempted=[]
                backend.context.on('request',lambda request:attempted.append(request.url))
                await page.goto('https://example.com/start')
                await page.wait_for_timeout(600)
                self.assertEqual(await page.evaluate('navigator.serviceWorker.controller'),None)
                self.assertEqual({c['name'] for c in await backend.context.cookies()}, {'session','other'})
                self.assertTrue(any(url.endswith('/cookie') and 'session=synthetic' in headers.get('cookie','') for url,headers in seen))
                self.assertTrue(any(url.endswith('/landing') for url,_ in seen))
                self.assertFalse(any('127.0.0.1' in url for url,_ in seen))
                self.assertTrue(any('/private-frame' in url for url in attempted))
                self.assertTrue(any('/private-image' in url for url in attempted))
                self.assertTrue(any('/private-popup' in url for url in attempted))
            finally:await backend._close()
        with patch('app.infrastructure.providers.pdf_downloads.socket.getaddrinfo',return_value=public),patch('app.infrastructure.providers.browser_policy.relay_request',side_effect=relay):
            # Numeric private addresses must remain private despite synthetic DNS.
            original=__import__('app.infrastructure.providers.pdf_downloads',fromlist=['validate_url']).validate_url
            def validate(url):
                if '127.0.0.1' in url:raise Pending('unsafe_url')
                return original(url)
            with patch('app.infrastructure.providers.browser_policy.validate_url',side_effect=validate),tempfile.TemporaryDirectory() as profile:
                asyncio.run(check(BrowserPDFDownloader(None,headless=True)))
                seen.clear()
                recovery=RecoveryPDFDownloader(None,headless=True)
                recovery.profile_directory=profile
                asyncio.run(check(recovery))

    def test_chromium_blob_snapshot_reads_stream_without_response_blob(self):
        from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader, VIEWER_SNAPSHOT
        async def check():
            backend=BrowserPDFDownloader(None,headless=True)
            try:
                await backend._start();page=await backend.context.new_page()
                await page.set_content('<iframe id="pdf"></iframe>')
                await page.evaluate('''() => {
                    Response.prototype.blob=()=>{throw Error('unbounded blob allocation');};
                    document.querySelector('iframe').src=URL.createObjectURL(new Blob([new Uint8Array(100)]));
                }''')
                result=await page.evaluate(VIEWER_SNAPSHOT,{'limit':8})
                self.assertTrue(result.get('large'))
            finally:await backend._close()
        asyncio.run(check())

    def test_slow_stream_cancel_and_deadline_stop_before_full_body(self):
        import threading
        import time
        from app.infrastructure.providers.browser_policy import read_bounded
        class SlowStream:
            count=0
            def read1(self,size):
                time.sleep(.02);self.count+=1;return b'x'
            def read(self,size):
                raise AssertionError('read can wait for the entire requested size')
        for cancel_early in (True,False):
            stream=SlowStream();stop=threading.Event()
            timer=threading.Timer(.04,stop.set) if cancel_early else None
            if timer:timer.start()
            started=time.monotonic()
            try:
                with self.assertRaises(Pending) as raised:
                    read_bounded(stream,{},limit=1000,stop=stop,deadline=started+.09)
                self.assertEqual(raised.exception.state,'browser_timeout')
                self.assertLess(time.monotonic()-started,.3)
                self.assertLess(stream.count,10)
            finally:
                if timer:timer.join()

    def test_context_close_signals_policy_stop(self):
        from app.infrastructure.providers.browser_policy import install_browser_policy
        class Context:
            def on(self,event,handler):self.closed=handler
            async def route(self,*args):pass
            async def route_web_socket(self,*args):pass
        async def check():
            context=Context();policy=await install_browser_policy(context)
            context.closed()
            self.assertTrue(policy.stop.is_set())
        asyncio.run(check())

    def test_pinned_socket_uses_validated_address_and_hostname_sni(self):
        import socket
        from app.infrastructure.providers.browser_policy import public_endpoints, PinnedHTTPSConnection
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        private=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        class Sock:
            def settimeout(self,value):pass
            def connect(self,address):self.address=address
            def close(self):pass
        raw=Sock()
        with patch('app.infrastructure.providers.browser_policy.socket.getaddrinfo',side_effect=[public,private]) as dns,patch('app.infrastructure.providers.browser_policy.socket.socket',return_value=raw):
            parts,addresses=public_endpoints('https://example.com/invoice')
            connection=PinnedHTTPSConnection(parts.hostname,addresses,None,float('inf'))
            with patch.object(connection._context,'wrap_socket',return_value=raw) as tls:
                connection.connect()
                tls.assert_called_once_with(raw,server_hostname='example.com')
            self.assertEqual(raw.address,('93.184.216.34',443))
            self.assertEqual(dns.call_count,1)

    def test_relay_deadline_interrupts_slow_headers_and_closes_connection(self):
        import threading
        import time
        from app.infrastructure.providers.browser_policy import relay_request
        closed=threading.Event()
        class Socket:
            def shutdown(self,*args):closed.set()
        class Connection:
            sock=Socket()
            cleaned=False
            def connect(self):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):
                if not closed.wait(1):raise AssertionError('watchdog did not interrupt headers')
                raise OSError('socket shut down')
            def close(self):self.cleaned=True
        connection=Connection();started=time.monotonic()
        with patch('app.infrastructure.providers.browser_policy.public_endpoints',return_value=(SimpleNamespace(hostname='example.com',path='/',query=''),[])),patch('app.infrastructure.providers.browser_policy.PinnedHTTPSConnection',return_value=connection):
            with self.assertRaises(OSError):
                relay_request('https://example.com/','GET',{},None,deadline=started+.06)
        self.assertTrue(connection.cleaned)
        self.assertLess(time.monotonic()-started,.4)

    def test_cancelled_dns_worker_does_not_block_runner_shutdown(self):
        import threading
        import time
        from app.infrastructure.providers.browser_policy import run_transport
        stop=threading.Event();release=threading.Event()
        def slow_dns():release.wait(1)
        async def check():
            with self.assertRaises(Pending):
                await run_transport(slow_dns,transfer_stop=stop,transfer_deadline=time.monotonic()+.06)
        started=time.monotonic()
        try:
            asyncio.run(check())
            self.assertLess(time.monotonic()-started,.4)
        finally:release.set()
