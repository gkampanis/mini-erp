"""Native-fault diagnostics must be enabled in both launcher child modes."""
from pathlib import Path
import unittest
import START_DEMO


class LauncherFaultDiagnostics(unittest.TestCase):
    def test_normal_and_check_child_enable_fault_handler_before_module_execution(self):
        for check,module in ((False,'app'),(True,'app.demo')):
            with self.subTest(check=check):
                args=START_DEMO.child_arguments(Path('synthetic-data'),check)
                self.assertEqual(args[0],START_DEMO.sys.executable)
                module_index=args.index('-m')
                self.assertEqual(args[module_index+1],module)
                self.assertIn('-X',args[1:module_index])
                self.assertEqual(args[args.index('-X')+1],'faulthandler')
                self.assertIn('-u',args[1:module_index])
                self.assertEqual(args[args.index('--data-dir')+1],'synthetic-data')
