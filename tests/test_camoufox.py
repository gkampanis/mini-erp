"""Offline checks of optional isolation, installation integrity and private diagnostics."""
from io import BytesIO
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch,MagicMock,AsyncMock
import zipfile
from app.infrastructure import camoufox_install as setup
from app.infrastructure.crashlog import record,export
from app.infrastructure.camoufox_worker import CamoufoxPDFDownloader
from app.application.service import ERP

class CamoufoxTests(unittest.TestCase):
    def test_diagnostics_never_include_error_text_locals_or_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            try:raise ValueError('SECRET password https://example.com/?key=secret 000000001 invoice.pdf')
            except ValueError as error:record(temp,error,'worker')
            file=Path(temp)/'support.txt';export(temp,file);content=file.read_text()
            for value in ['SECRET','password','https://','000000001','invoice.pdf',temp]:self.assertNotIn(value,content)
            data=json.loads(content.strip());self.assertEqual(data['error'],'ValueError');self.assertEqual(data['area'],'worker')
    def test_bad_log_directory_never_breaks_application(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'diagnostics').write_text('not a directory')
            self.assertIsNone(record(temp,RuntimeError('private')))
    def test_installer_rejects_zip_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'bad.zip'
            with zipfile.ZipFile(file,'w') as z:z.writestr('../escape.txt','bad')
            with self.assertRaises(ValueError):setup.extract(file,Path(temp)/'browser')
            self.assertFalse((Path(temp)/'escape.txt').exists())
    def test_ready_rejects_changed_browser(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(setup,'directory',return_value=Path(temp)):
            binary=setup.executable();binary.parent.mkdir();binary.write_bytes(b'synthetic')
            python=setup.interpreter();python.parent.mkdir();python.write_bytes(b'synthetic')
            (Path(temp)/'ready.json').write_text(json.dumps(dict(package='0.5.8',archive_sha256=setup.SHA256,executable_sha256=setup.digest(binary))))
            self.assertTrue(setup.ready());binary.write_bytes(b'changed');self.assertFalse(setup.ready())
    def test_install_is_explicit_local_and_requires_verified_download_and_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'Optional'/'Camoufox'/'python-test'
            data=BytesIO()
            with zipfile.ZipFile(data,'w') as z:z.writestr('camoufox.exe',b'synthetic browser')
            archive=data.getvalue()
            def make_env(path):
                python=setup.interpreter(Path(path));python.parent.mkdir(parents=True);python.write_bytes(b'synthetic python')
            with patch.object(setup,'directory',return_value=folder),patch.object(setup.sys,'platform','win32'),patch.object(setup.platform,'machine',return_value='AMD64'),patch.object(setup.venv.EnvBuilder,'create',side_effect=make_env),patch.object(setup.shutil,'disk_usage',return_value=SimpleNamespace(free=10*1024**3)),patch.object(setup.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run,patch.object(setup.urllib.request,'urlopen',return_value=BytesIO(archive)),patch.object(setup,'SIZE',len(archive)),patch.object(setup,'SHA256',hashlib.sha256(archive).hexdigest()):
                self.assertTrue(setup.install());self.assertTrue(setup.ready())
                self.assertEqual(run.call_count,3)
                self.assertTrue(all(str(folder) in call.args[0][0] for call in run.call_args_list))
                self.assertIn('Camoufox',run.call_args_list[-1].args[0][2])
    def test_missing_install_never_starts_process_or_changes_database(self):
        from app.application.camoufox_pdf import run
        with tempfile.TemporaryDirectory() as temp:
            erp=ERP(temp);company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ')
            try:
                with patch.object(setup,'ready',return_value=False),patch('app.application.camoufox_pdf.subprocess.Popen') as process:
                    with self.assertRaises(ValueError):run(erp,company,'test',['10000001'],threading.Event())
                    process.assert_not_called();self.assertEqual(erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],0)
            finally:erp.close()
    def test_async_adapter_uses_visible_separate_profile_and_disables_printing(self):
        api=ModuleType('camoufox.async_api');addons=ModuleType('camoufox.addons')
        context=SimpleNamespace(browser=MagicMock());api.AsyncNewBrowser=AsyncMock(return_value=context)
        addons.DefaultAddons=['synthetic-addon']
        playwright=SimpleNamespace(start=AsyncMock(return_value=SimpleNamespace()))
        with patch.dict('sys.modules',{'camoufox.async_api':api,'camoufox.addons':addons}),patch('playwright.async_api.async_playwright',return_value=playwright):
            backend=CamoufoxPDFDownloader(None,'synthetic/camoufox.exe',Path('synthetic/profile'))
            asyncio.run(backend._start())
            opts=api.AsyncNewBrowser.call_args.kwargs
            self.assertTrue(opts['persistent_context']);self.assertFalse(opts['headless']);self.assertFalse(opts['geoip'])
            self.assertEqual(opts['user_data_dir'],'synthetic/profile');self.assertFalse(backend.allow_print)
            self.assertEqual(backend.context,context)

    def test_adapter_capture_preserves_original_bytes_with_synthetic_chromium_transport(self):
        # This checks our capture adapter with real Playwright, not Firefox compatibility.
        import socket
        import shutil
        from app.infrastructure.providers.models import Client
        from tests.test_workspace import synthetic_pdf
        api=ModuleType('camoufox.async_api');addons=ModuleType('camoufox.addons');addons.DefaultAddons=[]
        async def launch(playwright,**options):
            context=await playwright.chromium.launch_persistent_context(options['user_data_dir'],headless=True,executable_path=shutil.which('chromium'),accept_downloads=True)
            async def handler(route):
                if route.request.url.endswith('/original.pdf'):await route.fulfill(body=synthetic_pdf(),content_type='application/pdf')
                else:await route.fulfill(body='<html><body><iframe src="/original.pdf"></iframe></body></html>',content_type='text/html')
            await context.route('**/*',handler);return context
        api.AsyncNewBrowser=AsyncMock(side_effect=launch)
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        with tempfile.TemporaryDirectory() as temp,patch.dict('sys.modules',{'camoufox.async_api':api,'camoufox.addons':addons}),patch('app.infrastructure.providers.pdf_downloads.socket.getaddrinfo',return_value=public):
            backend=CamoufoxPDFDownloader(None,'unused synthetic binary',Path(temp)/'profile');backend.timeout=5
            row=dict(mark=10000001,issue_date='2026-10-21',download_url='https://example.com/invoice')
            with backend.session():artifact=backend._download(Client('synthetic','ΣΥΝΘΕΤΙΚΗ','000000000','production'),row,Path(temp)/'archive',threading.Event())
            self.assertEqual(artifact[0].read_bytes(),synthetic_pdf());self.assertEqual(api.AsyncNewBrowser.call_count,1)
    def test_already_cancelled_recovery_never_starts_process(self):
        from app.application.camoufox_pdf import run
        cancel=threading.Event();cancel.set()
        with patch('app.application.camoufox_pdf.subprocess.Popen') as process:
            result=run(None,1,'test',['10000001'],cancel)
            self.assertTrue(result['cancelled']);process.assert_not_called()

    def test_cancelled_result_preserves_number_of_already_saved_pdfs(self):
        from app.application.camoufox_pdf import run
        with tempfile.TemporaryDirectory() as temp:
            erp=ERP(temp);company=erp.company('000000000','ΣΥΝΘΕΤΙΚΗ');cancel=threading.Event()
            def worker(command,**options):
                data=json.loads(Path(command[-1]).read_text())
                Path(data['response']).write_text(json.dumps(dict(result=dict(saved=2,printed=0,pending=0,skipped=0,cancelled=True))))
                cancel.set();process=MagicMock();process.poll.return_value=0;return process
            try:
                with patch.object(setup,'ready',return_value=True),patch('app.application.camoufox_pdf.subprocess.Popen',side_effect=worker):
                    result=run(erp,company,'test',['10000001'],cancel)
                    self.assertEqual(result['saved'],2);self.assertTrue(result['cancelled'])
            finally:erp.close()
