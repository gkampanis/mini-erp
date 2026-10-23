"""Package only source, docs and generated synthetic workbooks, never local data."""
import argparse
import hashlib
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixtures import demos


def build(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in ('START_DEMO.cmd','ANOIGMA_MINI_ERP.bat','START_DEMO.py','TRY_DEMO.md','README.md','NOTICE.md','AGENTS.md','requirements-pdf.txt','requirements-rpa.txt','requirements-browser.txt','requirements-camoufox.txt')]
    files.append(ROOT/'Optional/Camoufox/README.md')
    for directory, extensions in [('app',{'.py'}),('migrations',{'.sql'}),('tests',{'.py'}),('scripts',{'.py'}),('docs',{'.md','.png'})]:
        files.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
    with tempfile.TemporaryDirectory() as temp:
        samples = Path(temp)/'SampleExcel'
        demos(samples)
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(files):
                data = path.read_bytes()
                if path.suffix in ('.cmd','.bat'):
                    data = data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
                archive.writestr('MiniERP-Demo/'+path.relative_to(ROOT).as_posix(),data)
            for path in sorted(samples.glob('*.xlsx')):
                archive.write(path,'MiniERP-Demo/SampleExcel/'+path.name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='ascii')
    print(f'Package: {output.resolve()} ({output.stat().st_size:,} bytes)')
    print('SHA-256:',digest)
    return output


if __name__=='__main__':
    # Public packaging entrypoint always passes through the delivery gate.
    from scripts.verify_delivery import main
    sys.exit(main())
