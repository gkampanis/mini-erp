"""Optional recovery never imports Camoufox into the ERP interpreter."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from app.infrastructure import camoufox_install as setup

def stop_owned_process(process):
    try:
        if os.name=='nt':
            # Include only this optional worker's children; never another browser/EBS process.
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:process.terminate()
    except (OSError,subprocess.TimeoutExpired):process.kill()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()

def run(erp,company,environment,marks,cancel):
    if environment not in ('production','test'):raise ValueError('Μη έγκυρο περιβάλλον')
    if cancel.is_set():return dict(saved=0,printed=0,pending=0,skipped=0,cancelled=True)
    if not setup.ready():raise ValueError('Εγκατάστησε πρώτα το Camoufox από τις Ρυθμίσεις → PDF και λήψεις.')
    # Export only explicitly selected pending MARKs, never the entire company's list.
    if not marks:raise ValueError('Επίλεξε εκκρεμή παραστατικά για ανάκτηση.')
    with tempfile.TemporaryDirectory(prefix='minierp-camoufox-') as folder:
        folder=Path(folder);response=folder/'response.json';stop=folder/'cancel'
        payload=dict(directory=str(erp.directory.resolve()),company=company,environment=environment,marks=[str(m) for m in marks],binary=str(setup.executable()),destination=str((erp.directory/'pdf-archive').resolve()),cancel=str(stop),response=str(response))
        request=folder/'request.json';request.write_text(json.dumps(payload))
        env=os.environ.copy();env['PYTHONPATH']=str(setup.ROOT);env['MINIERP_OPTIONAL_PACKAGES']=str(setup.directory()/'unused')
        with tempfile.TemporaryFile() as quiet:
            process=subprocess.Popen([str(setup.interpreter()),'-m','app.infrastructure.camoufox_worker',str(request)],cwd=setup.ROOT,env=env,stdout=quiet,stderr=quiet,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            stopped=None;deadline=time.monotonic()+max(180,len(marks)*130)
            try:
                while process.poll() is None:
                    if cancel.is_set():
                        stop.touch(exist_ok=True)
                        if stopped is None:stopped=time.monotonic()
                    if time.monotonic()>deadline or (stopped and time.monotonic()-stopped>15):
                        stop_owned_process(process);break
                    time.sleep(.1)
            finally:
                if process.poll() is None:stop_owned_process(process)
        if cancel.is_set() and not response.is_file():return dict(cancelled=True,incomplete_summary=True)
        if not response.is_file():raise RuntimeError('Η ανάκτηση Camoufox δεν ολοκληρώθηκε. Τα ήδη αποθηκευμένα PDF διατηρούνται. Εξήγαγε το διαγνωστικό από τις Ρυθμίσεις.')
        result=json.loads(response.read_text())
        if result.get('error'):raise RuntimeError('Η ανάκτηση Camoufox δεν ολοκληρώθηκε. Δοκίμασε την κανονική ανάκτηση ή εξήγαγε το διαγνωστικό από τις Ρυθμίσεις.')
        return result['result']
