"""Explicit optional Windows installation, local to the application folder."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
import zipfile

ROOT=Path(__file__).resolve().parents[2]
VERSION='156.0.1-beta.36'
ASSET='camoufox-'+VERSION+'-win.x86_64.zip'
SHA256='096fd4832a7a32f2aa7f7bdd07fe6253dda296cbe783acd7bc2c86cf5ae62031'
SIZE=1311638126

def directory():return ROOT/'Optional'/'Camoufox'/('python-%s.%s'%sys.version_info[:2])
def interpreter(folder=None):return (folder or directory())/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
def executable(folder=None):return (folder or directory())/'browser'/'camoufox.exe'
def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

def ready():
    folder=directory()
    try:
        marker=json.loads((folder/'ready.json').read_text())
        return marker.get('archive_sha256')==SHA256 and marker.get('package')=='0.5.8' and interpreter().is_file() and executable().is_file() and marker.get('executable_sha256')==digest(executable())
    except (OSError,ValueError):return False

def extract(archive,destination):
    destination=Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        if sum(i.file_size for i in bundle.infolist())>8*1024**3:raise ValueError('Υπερβολικό μέγεθος browser')
        for info in bundle.infolist():
            if not (destination/info.filename).resolve().is_relative_to(destination) or info.external_attr>>16 & 0o170000==0o120000:raise ValueError('Μη έγκυρο αρχείο browser')
        bundle.extractall(destination)

def install():
    if sys.platform!='win32' or platform.machine().lower() not in ('amd64','x86_64'):
        raise ValueError('Η προαιρετική εγκατάσταση Camoufox υποστηρίζει Windows 64-bit (x64).')
    target=directory();target.parent.mkdir(parents=True,exist_ok=True)
    if ready():return True
    if shutil.disk_usage(target.parent).free<7*1024**3:raise ValueError('Χρειάζονται τουλάχιστον 7 GB ελεύθερα για την εγκατάσταση.')
    # An incomplete installation is never marked ready. Existing ERP packages stay untouched.
    target.mkdir(exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(target)
    result=subprocess.run([str(interpreter()),'-m','pip','install','--disable-pip-version-check','-r',str(ROOT/'requirements-camoufox.txt')],capture_output=True,timeout=600)
    if result.returncode:raise RuntimeError('Δεν εγκαταστάθηκαν οι βιβλιοθήκες Camoufox. Έλεγξε pip/δίκτυο και ξαναδοκίμασε από Ρυθμίσεις.')
    fd,temp=tempfile.mkstemp(dir=target,suffix='.zip');os.close(fd)
    try:
        url='https://github.com/daijro/camoufox/releases/download/v'+VERSION+'/'+ASSET
        with urllib.request.urlopen(url,timeout=60) as source,open(temp,'wb') as stream:
            total=0
            while True:
                block=source.read(1024*1024)
                if not block:break
                total+=len(block)
                if total>SIZE:raise ValueError('Λανθασμένο μέγεθος browser')
                stream.write(block)
        if total!=SIZE or digest(temp)!=SHA256:raise ValueError('Ο έλεγχος ακεραιότητας Camoufox απέτυχε. Δεν ενεργοποιήθηκε.')
        extract(temp,target/'browser')
        if not executable().is_file():raise ValueError('Δεν βρέθηκε ο browser μετά την αποσυμπίεση')
        # Verify the pinned Python package before marking the isolated installation ready.
        probe=subprocess.run([str(interpreter()),'-c',"from importlib.metadata import version; assert version('camoufox')=='0.5.8'; assert version('playwright')=='1.62.0'"],capture_output=True,timeout=30)
        if probe.returncode:raise RuntimeError('Δεν επιβεβαιώθηκε η εγκατάσταση Camoufox.')
        environment=os.environ.copy();environment.pop('PYTHONPATH',None)
        probe_code="from camoufox.sync_api import Camoufox; from camoufox.addons import DefaultAddons; import sys; c=Camoufox(headless=True,executable_path=sys.argv[1],exclude_addons=list(DefaultAddons),geoip=False); b=c.__enter__(); b.new_page().goto('about:blank'); c.__exit__(None,None,None)"
        launch=subprocess.run([str(interpreter()),'-c',probe_code,str(executable())],env=environment,capture_output=True,timeout=180)
        if launch.returncode:raise RuntimeError('Ο browser εγκαταστάθηκε αλλά δεν ξεκίνησε επιτυχώς. Δεν ενεργοποιήθηκε στο Mini ERP.')
        (target/'ready.json').write_text(json.dumps(dict(archive_sha256=SHA256,executable_sha256=digest(executable()),package='0.5.8')))
    finally:Path(temp).unlink(missing_ok=True)
    return True
