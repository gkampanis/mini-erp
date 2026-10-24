"""Synthetic Win32 message model; no native windows or input is used."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from app.infrastructure.ebs_adapter.session import WindowsSession

class NativeReadinessTests(unittest.TestCase):
    def make(self,active=202):
        user=SimpleNamespace()
        user.GetForegroundWindow=Mock(return_value=100)
        def thread(hwnd,pid):pid._obj.value=9;return 11
        user.GetWindowThreadProcessId=Mock(side_effect=thread)
        def info(tid,result):
            result._obj.hwndFocus=100;result._obj.hwndActive=100;return 1
        user.GetGUIThreadInfo=Mock(side_effect=info)
        user.GetParent=Mock(side_effect=lambda h:{201:150,202:150,150:100,100:0}.get(h,0))
        user.GetWindowTextW=Mock(return_value=0)
        def cls(hwnd,buffer,size):buffer.value='MDIClient' if hwnd==150 else 'Other';return len(buffer.value)
        user.GetClassNameW=Mock(side_effect=cls)
        def message(hwnd,msg,wp,lp,flags,ms,result):result._obj.value=active;return 1
        user.SendMessageTimeoutW=Mock(side_effect=message)
        session=WindowsSession.__new__(WindowsSession);session.pid=9;session.expected_ted=None
        session._mdi_forms=Mock(return_value={201,202});session.at_ebs=Mock(return_value=100);session.health=Mock()
        return user,session
    def test_prepare_resolves_mdi_active_child_on_other_ui_thread(self):
        user,session=self.make()
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            self.assertEqual(session.prepare({'save':(10,20),'new':(30,40)},202),202)
        self.assertEqual(session.expected_ted,202)
    def test_unknown_message_handle_never_becomes_a_target(self):
        user,session=self.make(active=999)
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            self.assertIsNone(session._active_ted())
    def test_prepare_waits_for_expected_child_activation_and_never_accepts_another(self):
        _,session=self.make()
        session._active_ted=Mock(side_effect=[201,None,202])
        with patch('app.infrastructure.ebs_adapter.session.time.sleep'):
            self.assertEqual(session.prepare({'save':(10,20),'new':(30,40)},202),202)
        self.assertEqual(session._active_ted.call_count,3)
        session._active_ted=Mock(return_value=201)
        with patch('app.infrastructure.ebs_adapter.session.time.monotonic',side_effect=[0,3]):
            with self.assertRaisesRegex(RuntimeError,'Δεν είναι ενεργό'):
                session.prepare({'save':(10,20),'new':(30,40)},202)
    def test_other_foreground_process_and_hung_mdi_do_not_select_a_child(self):
        user,session=self.make();session.pid=77
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            self.assertIsNone(session._active_ted());user.SendMessageTimeoutW.assert_not_called()
        user,session=self.make();user.SendMessageTimeoutW.return_value=0;user.SendMessageTimeoutW.side_effect=None
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            self.assertIsNone(session._active_ted())
        self.assertEqual(user.SendMessageTimeoutW.call_args.args[4:6],(2,250))
