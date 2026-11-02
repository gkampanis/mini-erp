"""Startup diagnostics must preserve interpreter failures and application exit codes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import START_DEMO


class StartupTests(unittest.TestCase):
    def test_missing_package_and_old_version_explain_the_problem(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'Python 3.12'):
                START_DEMO.probe(Path(temp),version=(3,11))
            with self.assertRaisesRegex(RuntimeError,'Incomplete extraction'):
                START_DEMO.probe(Path(temp),version=(3,12))

    def test_detected_failure_is_logged_and_returns_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(START_DEMO,'probe',side_effect=RuntimeError('Synthetic Tcl missing')):
                self.assertEqual(START_DEMO.main(['--check','--log-dir',temp]),1)
            logs=list(Path(temp).glob('startup-*.log'))
            self.assertEqual(len(logs),1)
            text=logs[0].read_text(encoding='utf8')
            self.assertIn('Synthetic Tcl missing',text)
            self.assertIn('Traceback',text)
            self.assertIn('Interpreter:',text)

    def test_child_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(START_DEMO,'probe',return_value={'tk':'synthetic'}),patch.object(START_DEMO,'run_child',return_value=17):
                self.assertEqual(START_DEMO.main(['--check','--log-dir',temp]),1)
            text=next(Path(temp).glob('startup-*.log')).read_text(encoding='utf8')
            self.assertIn('exited with code 17',text)
            self.assertNotIn('Launcher check passed.',text)

    def test_check_uses_isolated_data_and_existing_interpreter(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(START_DEMO,'probe',return_value={'tk':'synthetic'}),patch.object(START_DEMO,'run_child',return_value=0) as child:
                self.assertEqual(START_DEMO.main(['--check','--log-dir',temp]),0)
                args=child.call_args.args[0]
                self.assertEqual(args[0],START_DEMO.sys.executable)
                self.assertIn('--prepare-only',args)
                self.assertIn('MiniERP-launcher-check-',args[args.index('--data-dir')+1])
                self.assertFalse(Path(args[args.index('--data-dir')+1]).exists())
            self.assertIn('Launcher check passed.',next(Path(temp).glob('startup-*.log')).read_text(encoding='utf8'))

    def test_normal_startup_does_not_reseed_synthetic_documents(self):
        args=START_DEMO.child_arguments(Path('existing-data'),False)
        self.assertEqual(args[args.index('-m')+1],'app')
        self.assertNotIn('app.demo',args)


if __name__=='__main__':unittest.main()
