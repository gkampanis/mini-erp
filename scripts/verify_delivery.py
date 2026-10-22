"""Project-scoped, fail-closed delivery checks inspired by ECC's verification loop.

No ECC installers/hooks are executed. Only our source and synthetic fixtures run.
"""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = {'app':{'.py'},'tests':{'.py'},'scripts':{'.py'},'migrations':{'.sql'},'docs':{'.md','.png'}}
SOURCE_FILES = ('START_DEMO.cmd','TRY_DEMO.md','README.md','NOTICE.md','AGENTS.md')


class CheckFailed(RuntimeError):
    pass


def selected_files(root):
    root = Path(root)
    files = [root/name for name in SOURCE_FILES]
    for directory,extensions in SOURCE_DIRS.items():
        files.extend(p for p in (root/directory).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise CheckFailed('Source contains an unexpected symlink/outside path')
    return sorted(files)


def code_manifest(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n') if p.suffix=='.cmd' else p.read_bytes()).hexdigest()
            for p in selected_files(root) if p.suffix in ('.py','.sql','.cmd')}


def static_checks(root):
    parsed = 0
    problems = []
    for path in selected_files(root):
        if path.suffix!='.py':continue
        relative = path.relative_to(root)
        tree = ast.parse(path.read_text(encoding='utf8'),filename=str(relative))
        parsed += 1
        if relative.parts[0]!='app':continue
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                target = node.func
                if isinstance(target,ast.Name) and target.id in ('eval','exec'):
                    problems.append(f'{relative}:{node.lineno}: dynamic code execution')
                if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='pickle' and target.attr in ('load','loads'):
                    problems.append(f'{relative}:{node.lineno}: unsafe deserialization')
                if any(k.arg=='shell' and isinstance(k.value,ast.Constant) and k.value.value is True for k in node.keywords):
                    problems.append(f'{relative}:{node.lineno}: shell=True')
            if isinstance(node,ast.Assign) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                for target in node.targets:
                    if isinstance(target,ast.Name) and re.search(r'(^|_)(password|secret|api_key|access_token)$',target.id,re.I) and node.value.value.strip():
                        problems.append(f'{relative}:{node.lineno}: credential-like literal (value omitted)')
    if problems:raise CheckFailed('\n'.join(problems))
    return dict(python_files=parsed,scope='Syntax and targeted dangerous-call/credential-literal checks; not a full security audit')


def validate_suite(data):
    if type(data.get('tests')) is not int or data['tests']<=0:
        raise CheckFailed('Suite executed zero tests or has invalid counts')
    for field in ('failures','errors','skipped','expected_failures','unexpected_successes'):
        if type(data.get(field)) is not int or data[field]!=0:
            raise CheckFailed(f'Required suite did not fully pass: {field}')
    if data.get('successful') is not True:
        raise CheckFailed('Runner did not report success')
    return data


def inspect_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names)!=len(set(names)):raise CheckFailed('Archive has duplicate entries')
        required = {'MiniERP-Demo/app/__main__.py','MiniERP-Demo/migrations/001_initial.sql',
                    'MiniERP-Demo/migrations/002_preparation.sql','MiniERP-Demo/tests/fixtures.py',
                    'MiniERP-Demo/START_DEMO.cmd','MiniERP-Demo/TRY_DEMO.md',
                    'MiniERP-Demo/scripts/verify_delivery.py','MiniERP-Demo/scripts/run_checks.py'}
        if not required.issubset(names):raise CheckFailed('Archive missing required runtime/verification files')
        for item in archive.infolist():
            parts = PurePosixPath(item.filename).parts
            suffix = PurePosixPath(item.filename).suffix.lower()
            if not parts or parts[0]!='MiniERP-Demo' or '..' in parts or '\\' in item.filename:
                raise CheckFailed('Unsafe archive path')
            if stat.S_ISLNK(item.external_attr>>16):raise CheckFailed('Archive contains symlink')
            if any(p in ('.git','.local','__pycache__','legacy_reference') or p.startswith('.env') for p in parts) or suffix in ('.db','.sqlite3','.sqlite','.pdf','.pyc'):
                raise CheckFailed('Archive contains forbidden local/user data')
            if suffix in ('.xlsx','.xlsm') and item.filename not in ('MiniERP-Demo/SampleExcel/separate.xlsx','MiniERP-Demo/SampleExcel/combined.xlsx'):
                raise CheckFailed('Unexpected spreadsheet in archive')
            allowed_root = set(SOURCE_FILES) | {'VERIFICATION_REPORT.json'}
            if len(parts)==2:
                allowed = parts[1] in allowed_root
            else:
                allowed = (parts[1] in SOURCE_DIRS and suffix in SOURCE_DIRS[parts[1]]) or (parts[1]=='SampleExcel' and parts[-1] in ('separate.xlsx','combined.xlsx') and len(parts)==3)
            if not allowed:raise CheckFailed('Archive entry outside the delivery allowlist')
        if archive.testzip() is not None:raise CheckFailed('Archive CRC validation failed')
        for sample in ('separate.xlsx','combined.xlsx'):
            if 'MiniERP-Demo/SampleExcel/'+sample not in names:raise CheckFailed('Missing synthetic sample')
        return dict(entries=len(names),crc='passed',local_data='excluded')


class DeliveryCheck:
    def __init__(self,root,run_dir,timeout=180):
        self.root,self.run_dir = Path(root),Path(run_dir)
        self.run_dir.mkdir(parents=True,exist_ok=True)
        self.timeout = timeout
        self.checks = []

    def command(self,name,args,cwd=None,env=None):
        log = self.run_dir/(name+'.log')
        started = time.monotonic()
        with log.open('w',encoding='utf8') as out:
            try:
                process = subprocess.run(args,cwd=cwd or self.root,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=self.timeout,check=False)
                code = process.returncode
            except subprocess.TimeoutExpired:
                self.checks.append(dict(name=name,status='FAILED',reason='timeout',log=str(log)))
                raise CheckFailed(name+': timed out')
        item = dict(name=name,status='PASSED' if code==0 else 'FAILED',returncode=code,
                    seconds=round(time.monotonic()-started,3),log=str(log))
        self.checks.append(item)
        if code!=0:raise CheckFailed(f'{name}: exit {code}; see {log}')
        print('PASS:',name,flush=True)
        return item

    def suite(self,name,kind,cwd):
        report = self.run_dir/(name+'.json')
        item = self.command(name,[sys.executable,'scripts/run_checks.py','--suite',kind,'--report',str(report)],cwd=cwd)
        try:
            result = validate_suite(json.loads(report.read_text(encoding='utf8')))
        except Exception:
            item['status']='FAILED'
            raise
        item['counts']=result


def ensure_display():
    # Use the caller's existing graphical session; never silently skip GUI checks.
    probe = subprocess.run([sys.executable,'-c','import tkinter as tk; r=tk.Tk(); r.withdraw(); r.update(); r.destroy()'],capture_output=True,text=True,timeout=20)
    if probe.returncode!=0:raise CheckFailed('A working desktop display/Tk is required. On cloud start Xvfb and set DISPLAY; GUI checks are not skipped.')


def verify_demo(folder,data_dir):
    # Run this in a separate process against exactly the extracted delivery files.
    script = '''from pathlib import Path
import sys
from app.application.service import ERP
from app.infrastructure.importers.excel import preview
service=ERP(sys.argv[1])
try:
 companies=service.db.execute('SELECT id FROM companies').fetchall()
 assert len(companies)==1
 company=companies[0][0]
 assert len(service.search(company))==3
 assert service.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert service.db.execute('PRAGMA foreign_key_check').fetchall()==[]
 for name,count in [('separate.xlsx',2),('combined.xlsx',1)]:
  result=service.commit_import(company,preview(Path('SampleExcel')/name),confirmed=True)
  assert result['inserted']==0 and result['duplicates']==count
 assert len(service.search(company))==3
 print('DEMO PASS: 3 documents, DB integrity, foreign keys, packaged samples idempotent')
finally:service.close()
'''
    return [sys.executable,'-c',script,str(data_dir)]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Mini ERP delivery gate (ECC-inspired)')
    parser.add_argument('--output',type=Path,default=ROOT/'.local/releases/MiniERP-Checked-Demo.zip')
    parser.add_argument('--require-windows',action='store_true',help='Fail on non-Windows; additionally validate CMD launcher prerequisites')
    args = parser.parse_args(argv)
    output = args.output.resolve()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    run_dir = ROOT/'.local/verification'/run_id
    gate = DeliveryCheck(ROOT,run_dir)
    report = dict(run_id=run_id,status='FAILED',platform=platform.platform(),python=sys.version.split()[0],
                  artifact=None,checks=gate.checks,windows_desktop='NOT_RUN' if os.name!='nt' else 'REQUIRED',
                  windows_launcher='NOT_RUN',ebs_live='NOT_RUN',pdf_download='NOT_IMPLEMENTED',
                  scope='Synthetic source demo only; not a certified Windows EXE or EBS integration')
    report_path = run_dir/'report.json'
    try:
        if args.require_windows and os.name!='nt':raise CheckFailed('Windows required by target, current host is not Windows')
        original = code_manifest(ROOT)
        report['source_code_sha256']=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()
        report['source_files']=original
        with tempfile.TemporaryDirectory(prefix='mini-erp-delivery-') as temp:
            temp = Path(temp)
            snapshot = temp/'source'
            snapshot.mkdir()
            for path in selected_files(ROOT):
                destination = snapshot/path.relative_to(ROOT)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,destination)
            gate.checks.append(dict(name='static_checks',status='PASSED',details=static_checks(snapshot)))
            ensure_display()
            gate.checks.append(dict(name='desktop_display',status='PASSED'))
            gate.suite('source_tests','backend',snapshot)
            gate.suite('source_gui','gui',snapshot)
            gate.command('source_gui_smoke',[sys.executable,'-m','tests.gui_smoke'],cwd=snapshot)
            candidate = temp/'MiniERP-Demo.zip'
            gate.command('package_build',[sys.executable,'-c','from pathlib import Path; from scripts.package_demo import build; import sys; build(Path(sys.argv[1]))',str(candidate)],cwd=snapshot)
            gate.checks.append(dict(name='archive_integrity',status='PASSED',details=inspect_archive(candidate)))
            extracted = temp/'extracted'
            with zipfile.ZipFile(candidate) as archive:archive.extractall(extracted)
            packaged = extracted/'MiniERP-Demo'
            if code_manifest(packaged)!=original:raise CheckFailed('Packaged code differs from checked source')
            gate.suite('package_tests','backend',packaged)
            gate.suite('package_gui','gui',packaged)
            gate.command('package_gui_smoke',[sys.executable,'-m','tests.gui_smoke'],cwd=packaged)
            data_dir = temp/'synthetic-data'
            gate.command('demo_initialization',[sys.executable,'-m','app.demo','--prepare-only','--data-dir',str(data_dir)],cwd=packaged)
            gate.command('demo_readback',verify_demo(packaged,data_dir),cwd=packaged)
            if os.name=='nt':
                gate.command('windows_launcher_check',['cmd.exe','/d','/c','START_DEMO.cmd','--check'],cwd=packaged)
                report['windows_launcher']='PASSED'
                report['windows_desktop']='PASSED'
            if code_manifest(ROOT)!=original:raise CheckFailed('Source changed during checks; restart verification')
            report['status']='PASSED'
            embedded = dict(report,artifact=None)
            with zipfile.ZipFile(candidate,'a',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('MiniERP-Demo/VERIFICATION_REPORT.json',json.dumps(embedded,ensure_ascii=False,indent=2))
            inspect_archive(candidate)
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            output.parent.mkdir(parents=True,exist_ok=True)
            # Stage in the destination filesystem, then atomically replace only after all checks.
            fd,staged = tempfile.mkstemp(prefix='verified-',suffix='.zip',dir=output.parent)
            os.close(fd)
            try:
                shutil.copyfile(candidate,staged)
                os.replace(staged,output)
            finally:
                if os.path.exists(staged):os.unlink(staged)
            report['artifact']=dict(path=str(output),sha256=digest,size=output.stat().st_size)
            output.with_suffix('.zip.sha256').write_text(digest+'  '+output.name+'\n',encoding='ascii')
            output.with_suffix('.verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print('DELIVERY CHECK PASSED:',output)
        print('Windows desktop:',report['windows_desktop'],'| EBS live: NOT_RUN')
        return 0
    except Exception as exc:
        report['status']='FAILED'
        report['error']=str(exc)
        print('DELIVERY BLOCKED:',str(exc),file=sys.stderr)
        print('No new ZIP published; any older ZIP remains unchanged.',file=sys.stderr)
        return 1
    finally:
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print('Verification report:',report_path)


if __name__=='__main__':sys.exit(main())
