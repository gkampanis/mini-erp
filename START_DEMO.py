"""Visible startup diagnostics for the existing Python installation.

No installations, network calls, EBS access or production data changes.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback
import uuid

ROOT = Path(__file__).resolve().parent
MINIMUM = (3, 12)


def probe(root=ROOT, version=None):
    version = sys.version_info[:2] if version is None else version
    if version < MINIMUM:
        raise RuntimeError('Detected Python %s.%s; this build requires Python 3.12 or newer.' % tuple(version))
    for name in ('app/demo.py','app/__init__.py','migrations/001_initial.sql','migrations/002_preparation.sql','migrations/003_rounding.sql','migrations/004_workspace.sql','tests/fixtures.py'):
        if not (root/name).is_file():
            raise RuntimeError('Incomplete extraction: missing '+name+'. Extract the entire ZIP, not just the launcher.')
    import sqlite3
    import tkinter as tk
    display = tk.Tk()
    try:
        display.withdraw()
        display.update()
        tk_version = display.tk.call('package','provide','Tk')
    finally:
        display.destroy()
    return {'sqlite':sqlite3.sqlite_version,'tk':str(tk_version)}


def child_arguments(data_dir, check):
    return [sys.executable,'-u','-m','app.demo','--data-dir',str(data_dir)]+(['--prepare-only'] if check else [])


def run_child(arguments, log, root=ROOT):
    child_env = os.environ.copy()
    child_env['PYTHONUTF8']='1'
    child_env['PYTHONIOENCODING']='utf-8'
    process = subprocess.Popen(arguments,cwd=root,env=child_env,stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace')
    try:
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line,end='',flush=True)
        return process.wait()
    finally:
        process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Mini ERP startup diagnostics')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--log-dir',type=Path)
    args = parser.parse_args(argv)
    base = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir())/'MiniERP'
    log_dir = args.log_dir or base/'Logs'
    try:
        log_dir.mkdir(parents=True,exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
        log_path = log_dir/('startup-'+stamp+'.log')
        log = log_path.open('x',encoding='utf8')
    except OSError as exc:
        print('STARTUP ERROR: cannot create diagnostic log:',exc,flush=True)
        return 1
    with log:
        def say(text):
            print(text,flush=True)
            log.write(text+'\n');log.flush()
        try:
            say('Mini ERP startup - no EBS connection')
            say('Python: '+platform.python_version())
            say('Interpreter: '+sys.executable)
            say('Diagnostic log: '+str(log_path))
            versions = probe()
            say('Tk and SQLite ready: '+str(versions))
            if args.check:
                with tempfile.TemporaryDirectory(prefix='MiniERP-launcher-check-') as temporary:
                    code = run_child(child_arguments(Path(temporary)/'demo',True),log)
            else:
                if os.name=='nt' and not os.environ.get('LOCALAPPDATA'):
                    raise RuntimeError('LOCALAPPDATA is unavailable; no demo data directory was selected.')
                say('Opening Mini ERP. Keep this window available if a problem appears.')
                code = run_child(child_arguments(base/'Demo',False),log)
            if code!=0:
                raise RuntimeError('Application exited with code '+str(code)+'. See the diagnostic log above.')
            say('Launcher check passed.' if args.check else 'Mini ERP closed normally.')
            return 0
        except Exception as exc:
            traceback.print_exc(file=log)
            say('STARTUP ERROR: '+str(exc))
            say('Please share this log file: '+str(log_path))
            return 1


if __name__=='__main__':
    raise SystemExit(main())
