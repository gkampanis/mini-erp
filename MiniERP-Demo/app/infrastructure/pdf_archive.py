"""Immutable local PDF archive and explicitly requested HTTPS retrieval."""
import hashlib
import ipaddress
from pathlib import Path
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from app.infrastructure.optional_packages import activate

MAX_PDF=40*1024*1024
KINDS={'invoice':'Τιμολόγιο','delivery_note':'Δελτίο αποστολής','other':'Άλλο έγγραφο'}


def renderer_available():
    activate()
    try:
        import pypdfium2
        from PIL import Image
        return True
    except ImportError:return False


def validate_pdf(data):
    if not data or len(data)>MAX_PDF or not data.lstrip().startswith(b'%PDF-'):
        raise ValueError('Απαιτείται PDF έως 40 MB')
    return hashlib.sha256(data).hexdigest()


def store(directory,data):
    digest=validate_pdf(data)
    directory=Path(directory).resolve()
    relative=Path('documents')/digest[:2]/(digest+'.pdf')
    path=directory/relative
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.resolve().is_relative_to(directory):raise ValueError('Μη ασφαλής διαδρομή αρχείου')
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Αλλοιωμένο αρχείο PDF στην αρχειοθήκη')
    else:
        fd,temp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return digest,relative.as_posix()


def checked_path(directory,relative,digest):
    root=Path(directory).resolve();path=(root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('Δεν βρέθηκε ασφαλές αρχείο PDF')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Το PDF δεν συμφωνεί με το αποθηκευμένο hash')
    return path


def validate_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Επιτρέπεται μόνο δημόσιος σύνδεσμος HTTPS χωρίς ενσωματωμένους κωδικούς')
    host=parsed.hostname
    if host.lower()=='localhost' or host.lower().endswith(('.local','.localhost')):raise ValueError('Μη δημόσιος προορισμός')
    try:addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError:raise ValueError('Δεν επιλύεται ο προορισμός λήψης') from None
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError('Δεν επιτρέπονται εσωτερικές ή δεσμευμένες διευθύνσεις')
    return parsed


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections=5
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def download(url,cancel=None):
    parsed=validate_url(url)
    opener=urllib.request.build_opener(SafeRedirect())
    try:
        with opener.open(urllib.request.Request(url,headers={'Accept':'application/pdf'}),timeout=20) as response:
            length=response.headers.get('Content-Length')
            if length and int(length)>MAX_PDF:raise ValueError('Το PDF υπερβαίνει τα 40 MB')
            result=bytearray()
            while True:
                if cancel is not None and cancel.is_set():raise ValueError('Η λήψη ακυρώθηκε')
                chunk=response.read(65536)
                if not chunk:break
                result.extend(chunk)
                if len(result)>MAX_PDF:raise ValueError('Το PDF υπερβαίνει τα 40 MB')
            data=bytes(result)
            validate_pdf(data)
            # Signed URL query strings may contain credentials: never persist them.
            return data,'https:'+parsed.hostname
    except (urllib.error.URLError,TimeoutError,OSError):
        raise RuntimeError('Η λήψη PDF απέτυχε. Έλεγξε τον σύνδεσμο και την πρόσβαση στον πάροχο.') from None


def render(path,page_number=0,width=500,height=680):
    activate()
    try:
        import pypdfium2 as pdfium
    except ImportError:raise RuntimeError('Χρειάζεται η προαιρετική προβολή PDF') from None
    with pdfium.PdfDocument(str(path)) as document:
        count=len(document)
        if not 0<count<=1000 or not 0<=page_number<count:raise ValueError('Μη έγκυρη σελίδα PDF')
        page=document[page_number]
        try:
            w,h=page.get_size()
            if not (0<w<100000 and 0<h<100000):raise ValueError('Μη έγκυρο μέγεθος σελίδας')
            scale=min(max(100,width)/w,max(100,height)/h,2)
            bitmap=page.render(scale=scale)
            try:
                image=bitmap.to_pil().convert('RGB')
                try:
                    ppm=('P6\n%d %d\n255\n'%image.size).encode()+image.tobytes()
                    return dict(ppm=ppm,pages=count,page=page_number)
                finally:image.close()
            finally:bitmap.close()
        finally:page.close()
