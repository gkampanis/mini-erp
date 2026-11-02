"""Synthetic foreground/occlusion model: never sends native input."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from tests import test_native_readiness as readiness


class EBSForegroundTests(unittest.TestCase):
    def graph(self,activate=True):
        user,session=readiness.HostedTEDTests().graph();session.pid=None;session.pg=Mock()
        del session.at_ebs
        state={'foreground':900}
        user.GetForegroundWindow.side_effect=lambda:state['foreground']
        user.WindowFromPoint=Mock(side_effect=lambda point:221 if state['foreground']==100 else 901)
        user.GetWindow=Mock(return_value=0)
        user.IsIconic=Mock(return_value=False);user.ShowWindow=Mock()
        def foreground(handle):
            if activate:state['foreground']=handle
            return int(activate)
        user.SetForegroundWindow=Mock(side_effect=foreground)
        return user,session,state

    def environment(self,user):
        return patch.multiple(ctypes,windll=SimpleNamespace(user32=user),WINFUNCTYPE=ctypes.CFUNCTYPE,create=True)

    def test_prepare_brings_verified_ebs_in_front_before_resolving_mapping(self):
        user,session,state=self.graph()
        # The current implementation fails against the browser-covered point.
        with self.environment(user):
            try:actual=session.prepare({'save':(10,20),'new':(30,40)},202)
            except RuntimeError as exc:self.fail('The mapped EBS window must be activated before point validation: '+str(exc))
            self.assertEqual(actual,202)
        self.assertEqual(state['foreground'],100)
        user.SetForegroundWindow.assert_called_once_with(100)
        self.assertEqual(session.pid,9)
        self.assertEqual(session.pg.mock_calls,[])
        user.ShowWindow.assert_not_called()

    def test_denied_foreground_activation_sends_no_click_or_keyboard_input(self):
        user,session,_=self.graph(activate=False)
        with self.environment(user),patch('app.infrastructure.ebs_adapter.session.time.sleep'),patch('app.infrastructure.ebs_adapter.session.time.monotonic',side_effect=[0,3]):
            with self.assertRaisesRegex(RuntimeError,'προσκήνιο'):
                session.prepare({'save':(10,20),'new':(30,40)},202)
        self.assertEqual(session.pg.mock_calls,[])

    def test_resumed_new_form_also_activates_ebs_before_the_new_click(self):
        import itertools
        user,session,_=self.graph()
        session._mdi_forms=Mock(side_effect=lambda:{201,202} if session.pg.click.called else {201})
        session._active_ted=Mock(return_value=202);session._activate_fresh_ted=Mock()
        with self.environment(user),patch('app.infrastructure.ebs_adapter.session.time.sleep'),patch('app.infrastructure.ebs_adapter.session.time.monotonic',side_effect=itertools.count()):
            try:actual=session.open_new((30,40))
            except RuntimeError as exc:self.fail('Resume must activate EBS before using the New point: '+str(exc))
            self.assertEqual(actual,202)
        user.SetForegroundWindow.assert_called_once_with(100)
        session.pg.click.assert_called_once_with(30,40)

    def test_existing_foreground_does_not_trigger_another_activation(self):
        user,session,state=self.graph();state['foreground']=100
        with self.environment(user):session.prepare({'save':(10,20),'new':(30,40)},202)
        user.SetForegroundWindow.assert_not_called()

    def test_minimized_ebs_is_restored_without_moving_or_maximizing_it(self):
        user,session,_=self.graph();user.IsIconic.return_value=True
        with self.environment(user):session.prepare({'save':(10,20),'new':(30,40)},202)
        user.ShowWindow.assert_called_once_with(100,9)
        user.SetForegroundWindow.assert_called_once_with(100)

    def test_two_background_ebs_roots_are_not_selected_arbitrarily(self):
        user,session,_=self.graph();user.parents[400]=0
        original=user.GetWindowTextW.side_effect
        def title(handle,buffer,size):
            if handle==400:buffer.value='Entersoft EBS ERP';return len(buffer.value)
            return original(handle,buffer,size)
        user.GetWindowTextW.side_effect=title
        user.EnumWindows.side_effect=lambda callback,arg:(callback(100,arg),callback(400,arg))
        with self.environment(user):
            with self.assertRaisesRegex(RuntimeError,'μοναδικό'):
                session.prepare({'save':(10,20),'new':(30,40)},202)
        user.SetForegroundWindow.assert_not_called();self.assertEqual(session.pg.mock_calls,[])

    def test_bound_session_never_steals_foreground_back_during_save(self):
        user,session,_=self.graph();session.pid=9;session.expected_ted=202
        with self.environment(user):
            with self.assertRaises(RuntimeError):session.save((10,20))
        user.SetForegroundWindow.assert_not_called();self.assertEqual(session.pg.mock_calls,[])

    def test_net_field_is_reached_if_ted_caption_disappears_after_account_entry(self):
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        user,session,foreground_state=self.graph();session.pid=9;session.expected_ted=202
        foreground_state['foreground']=100
        user.WindowFromPoint.side_effect=None;user.WindowFromPoint.return_value=221
        state={'caption':True}
        session._mdi_forms=Mock(side_effect=lambda:{202} if state['caption'] else {201})
        def write(value,**_):
            if value=='64.03':state['caption']=False
        session.pg.write.side_effect=write
        mapping={field:(10+index*20,20) for index,(field,_) in enumerate(FIELDS)}
        payload=dict(vat='000000001',invoice='S/1',date='21/10/2026',account='64.03',net='123,45')
        def focused(thread,out):
            out._obj.hwndFocus=221;out._obj.hwndActive=100;return 1
        user.GetGUIThreadInfo.side_effect=focused
        def editor_rect(handle,out):
            x,y=mapping['NET_AMOUNT_GRID_CELL'];rect=out._obj
            rect.left,rect.top,rect.right,rect.bottom=x-5,y-5,x+5,y+5
            return 1
        user.GetWindowRect=Mock(side_effect=editor_rect)
        with self.environment(user),patch('app.infrastructure.ebs_adapter.adapter.time.sleep'):
            try:session.fill(payload,mapping)
            except RuntimeError as exc:self.fail('Valid net cell must remain reachable after account entry: '+str(exc))
        self.assertEqual([call.args[0] for call in session.pg.write.call_args_list],['000000001','S/1','21102026','64.03','123,45'])
        self.assertEqual([call.args for call in session.pg.click.call_args_list],list(mapping.values()))
        self.assertEqual(sum(call.args==('tab',) for call in session.pg.press.call_args_list),5)
