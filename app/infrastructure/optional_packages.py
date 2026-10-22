"""Optional feature dependencies stay separate from the existing Python installation."""
import os
from pathlib import Path
import subprocess
import sys


def directory():
    configured=os.environ.get('MINIERP_OPTIONAL_PACKAGES')
    if configured:return Path(configured)
    base=Path(os.environ.get('LOCALAPPDATA') or str(Path.home()/'MiniERP-data'))
    return base/'MiniERP'/'Packages'/('python-%s.%s'%sys.version_info[:2])


def activate():
    path=directory()
    if path.is_dir() and str(path) not in sys.path:sys.path.insert(0,str(path))


def install(feature):
    if feature not in ('pdf','rpa'):raise ValueError('Άγνωστη προαιρετική δυνατότητα')
    path=directory();path.mkdir(parents=True,exist_ok=True)
    requirement=Path(__file__).resolve().parents[2]/('requirements-'+feature+'.txt')
    command=[sys.executable,'-m','pip','install','--disable-pip-version-check','--target',str(path),'--upgrade','--requirement',str(requirement)]
    if feature=='pdf':command.append('--only-binary=:all:')
    result=subprocess.run(command,capture_output=True,text=True,timeout=240)
    if result.returncode:
        # Do not dump process environment, credentials or arbitrary package-manager logs.
        raise RuntimeError('Δεν ολοκληρώθηκε η εγκατάσταση προβολής/adapter. Έλεγξε ότι υπάρχει pip και πρόσβαση στο PyPI. Η εφαρμογή και τα παραστατικά διατηρήθηκαν.')
    activate()
    return True
