"""Delivery gate must fail closed, including deceptively successful empty suites."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts.verify_delivery import CheckFailed,DeliveryCheck,code_manifest,inspect_archive,static_checks,validate_suite
from scripts.package_demo import build

ROOT = Path(__file__).resolve().parents[1]


class DeliveryTests(unittest.TestCase):
    def test_empty_skipped_or_expected_failure_suite_is_not_delivery_success(self):
        good = dict(tests=1,failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0,successful=True)
        self.assertEqual(validate_suite(good),good)
        for key,value in [('tests',0),('tests',True),('skipped',1),('expected_failures',1),('failures',1),('errors',1),('unexpected_successes',1),('successful',False)]:
            with self.subTest(key=key):
                with self.assertRaises(CheckFailed):validate_suite(dict(good,**{key:value}))

    def test_command_failure_and_timeout_keep_true_outcomes(self):
        with tempfile.TemporaryDirectory() as temp:
            gate = DeliveryCheck(ROOT,temp,timeout=5)
            with self.assertRaises(CheckFailed):gate.command('exit_failure',[sys.executable,'-c','raise SystemExit(7)'])
            self.assertEqual(gate.checks[0]['returncode'],7)
            self.assertEqual(gate.checks[0]['status'],'FAILED')
            gate.timeout=.1
            with self.assertRaises(CheckFailed):gate.command('timed_out',[sys.executable,'-c','import time;time.sleep(10)'])
            self.assertEqual(gate.checks[1]['reason'],'timeout')

    def test_timeout_stops_spawned_worker_before_workspace_cleanup(self):
        import os,time,signal
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);beat=root/'heartbeat';pidfile=root/'child.pid'
            writer="import pathlib,time; p=pathlib.Path("+repr(str(beat))+"); "+"\nwhile True:\n p.write_text(str(time.time_ns())); time.sleep(.03)"
            parent="import pathlib,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c',"+repr(writer)+"]); pathlib.Path("+repr(str(pidfile))+").write_text(str(p.pid)); time.sleep(30)"
            gate=DeliveryCheck(ROOT,root/'logs',timeout=5)
            try:
                with self.assertRaises(CheckFailed):gate.command('spawned_worker',[sys.executable,'-c',parent],cwd=root)
                self.assertTrue(beat.exists(),'spawned worker did not start')
                pid=int(pidfile.read_text())
                def alive():
                    if os.name=='nt':
                        import ctypes
                        from ctypes import wintypes
                        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
                        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
                        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
                        handle=kernel.OpenProcess(0x1000,False,pid)
                        if not handle:return False
                        try:
                            code=wintypes.DWORD()
                            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
                        finally:kernel.CloseHandle(handle)
                    try:os.kill(pid,0)
                    except ProcessLookupError:return False
                    stat=Path('/proc')/str(pid)/'stat'
                    return not stat.exists() or stat.read_text().split()[2]!='Z'
                deadline=time.monotonic()+1
                while alive() and time.monotonic()<deadline:time.sleep(.05)
                self.assertFalse(alive(),'timed-out command left its worker running')
            finally:
                if pidfile.exists():
                    pid=int(pidfile.read_text())
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,check=False)
                    else:
                        try:os.kill(pid,signal.SIGKILL)
                        except ProcessLookupError:pass

    def test_fresh_result_missing_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            gate = DeliveryCheck(ROOT,temp)
            with patch.object(gate,'command',return_value={}):
                with self.assertRaises(FileNotFoundError):gate.suite('never_ran','backend',ROOT)

    def test_syntax_and_unsafe_app_calls_are_blocked_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('START_DEMO.cmd','ANOIGMA_MINI_ERP.bat','START_DEMO.py','TRY_DEMO.md','README.md','NOTICE.md','AGENTS.md'):(root/name).touch()
            (root/'app').mkdir()
            source = root/'app/main.py'
            source.write_text('def broken(:\n',encoding='utf8')
            with self.assertRaises(SyntaxError):static_checks(root)
            for code in ["eval('1+1')",'import pickle;pickle.loads(b"x")','import subprocess;subprocess.run("x",shell=True)',"API_KEY='synthetic-sensitive-literal'"]:
                source.write_text(code,encoding='utf8')
                with self.subTest(code=code),self.assertRaises(CheckFailed) as error:static_checks(root)
                self.assertNotIn('synthetic-sensitive-literal',str(error.exception))
            source.write_text('x = 1\n')
            self.assertEqual(static_checks(root)['python_files'],2)

    def test_packaged_source_matches_manifest_and_excludes_local_data(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            archive = build(temp/'demo.zip')
            inspect_archive(archive)
            with zipfile.ZipFile(archive) as z:z.extractall(temp/'unpack')
            self.assertEqual(code_manifest(temp/'unpack/MiniERP-Demo'),code_manifest(ROOT))
            for forbidden in ('user.sqlite3','.env.production','customer.csv','../escape.py'):
                altered = temp/'altered.zip'
                altered.write_bytes(archive.read_bytes())
                with zipfile.ZipFile(altered,'a') as z:z.writestr('MiniERP-Demo/'+forbidden,'synthetic')
                with self.subTest(forbidden=forbidden),self.assertRaises(CheckFailed):inspect_archive(altered)

    def test_failed_required_suite_does_not_publish_zip(self):
        # Exercise the orchestrator itself: a failed stage cannot call the publisher.
        from scripts import verify_delivery
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'delivery.zip'
            # Existing user artifacts must be preserved; no failed run may replace them.
            output.write_bytes(b'previous-verified-artifact')
            with patch.object(verify_delivery,'ensure_display'),patch.object(verify_delivery.DeliveryCheck,'command',return_value={}),patch.object(verify_delivery.DeliveryCheck,'suite',side_effect=CheckFailed('synthetic required failure')):
                self.assertEqual(verify_delivery.main(['--output',str(output)]),1)
            self.assertEqual(output.read_bytes(),b'previous-verified-artifact')
            self.assertFalse(output.with_suffix('.verification.json').exists())

    def test_targeted_runner_records_real_counts_and_rejects_invalid_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            gate=DeliveryCheck(ROOT,temp)
            gate.targeted(['tests.test_pdf_cancel'],ROOT)
            self.assertEqual(gate.checks[0]['counts']['tests'],2)
            self.assertEqual(gate.checks[0]['selector'],'tests.test_pdf_cancel')
            with self.assertRaises(CheckFailed):gate.targeted(['not.a.test'],ROOT)

    def test_targeted_failure_keeps_previous_zip_and_never_runs_full_suites(self):
        from scripts import verify_delivery
        original=DeliveryCheck.command
        def command(gate,name,args,**kwargs):
            if name=='package_build':return original(gate,name,args,**kwargs)
            return {}
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'delivery.zip';output.write_bytes(b'previous')
            with patch.object(verify_delivery,'ensure_display'),patch.object(DeliveryCheck,'command',command),patch.object(DeliveryCheck,'suite',side_effect=AssertionError('Full suites forbidden in targeted mode')),patch.object(DeliveryCheck,'targeted',side_effect=CheckFailed('synthetic selected test failure')) as scoped:
                self.assertEqual(verify_delivery.main(['--output',str(output),'--targeted-test','tests.test_pdf_cancel']),1)
            scoped.assert_called_once()
            self.assertEqual(output.read_bytes(),b'previous')
            self.assertFalse(output.with_suffix('.verification.json').exists())


if __name__=='__main__':unittest.main()
