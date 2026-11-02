import unittest
import ctypes
from types import SimpleNamespace
from app.infrastructure.ebs_adapter.duplicates import parse_duplicate, is_ok_button, is_ok_label, DuplicateExistingDocument, CreditorResolutionRequired
from unittest.mock import patch,Mock
from app.infrastructure.ebs_adapter.session import WindowsSession

MESSAGE='Ο κωδικός εναλ/κού παραστατικού που επιλέξατε χρησιμοποιείται ήδη στο παρ/κό ΤΕΔ-0-13693 με ημ/νία 16/09/2026 12:00:00πμ και συνολική αξία 4,01.'

class DuplicateDialogTests(unittest.TestCase):
    def test_exact_template(self):
        self.assertEqual(parse_duplicate('Προσοχή',MESSAGE),('ΤΕΔ-0-13693','16/09/2026 12:00:00πμ','4,01'))
        for title,body in [('Error',MESSAGE),('Προσοχή','duplicate'),('Προσοχή',MESSAGE+' Extra')]:
            self.assertIsNone(parse_duplicate(title,body))

    def test_native_and_winforms_ok_button_classes(self):
        self.assertTrue(is_ok_button('Button','OK'))
        self.assertTrue(is_ok_button('WindowsForms10.BUTTON.app.0.123','&OK'))
        self.assertFalse(is_ok_button('WindowsForms10.STATIC.app.0.123','OK'))
        self.assertFalse(is_ok_button('Button','Cancel'))

    def test_unknown_custom_ok_is_chrome_but_not_clickable(self):
        values=[MESSAGE,' &OK ']
        body=' '.join(value for value in values if not is_ok_label(value))
        self.assertIsNotNone(parse_duplicate('Προσοχή',body))
        self.assertFalse(is_ok_button('WindowsForms10.Window.app.SimpleButton',' &OK '))
        self.assertFalse(is_ok_label('OK extra'))

    def test_native_custom_ok_reaches_manual_signal_without_click(self):
        s=self.session();del s._duplicate_dialogs;del s._dismiss_duplicate
        s._ancestors=lambda h:[30] if h==30 else []
        user=SimpleNamespace()
        user.GetWindow=Mock(return_value=30)
        user.IsWindowVisible=Mock(return_value=True);user.IsWindowEnabled=Mock(return_value=True)
        def process(h,out):out._obj.value=20;return 1
        user.GetWindowThreadProcessId=Mock(side_effect=process)
        def name(h,buf,size):
            buf.value='Static' if h==41 else 'WindowsForms10.Window.app.SimpleButton'
            return len(buf.value)
        user.GetClassNameW=Mock(side_effect=name)
        def message(h,msg,wp,lp,flags,timeout,out):
            self.assertEqual(msg,13)  # Observation only; never BM_CLICK.
            value={40:'Προσοχή',41:MESSAGE,42:'OK'}[h]
            buf=ctypes.create_unicode_buffer(value)
            ctypes.memmove(lp,buf,ctypes.sizeof(buf));out._obj.value=len(value)
            return 1
        user.SendMessageTimeoutW=Mock(side_effect=message)
        user.EnumWindows=Mock(side_effect=lambda callback,arg:callback(40,arg))
        user.EnumChildWindows=Mock(side_effect=lambda h,callback,arg:(callback(41,arg),callback(42,arg)))
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True):
            with self.assertRaises(DuplicateExistingDocument) as raised:s._check_duplicate()
        self.assertFalse(raised.exception.dismissed)

    def session(self):
        s=WindowsSession.__new__(WindowsSession);s.pid=20;s.expected_ted=30
        s._duplicate_context=dict(vat='123',invoice='INV',expected_ted=30)
        s._duplicate_dialogs=lambda:[dict(handle=40,pid=20,owner_ted=30,title='Προσοχή',body=MESSAGE,ok=41)]
        s._dismiss_duplicate=lambda dialog:True
        return s

    def test_verified_signal(self):
        s=self.session()
        with self.assertRaises(DuplicateExistingDocument) as raised:s._check_duplicate()
        self.assertEqual((raised.exception.vat,raised.exception.invoice,raised.exception.dismissed),('123','INV',True))

    def test_identity_and_ownership_required(self):
        for change in ('context','ted','pid','owner'):
            s=self.session();dialog=s._duplicate_dialogs()[0]
            if change=='context':s._duplicate_context=None
            elif change=='ted':s.expected_ted=99
            elif change=='pid':dialog['pid']=99
            else:dialog['owner_ted']=99
            s._duplicate_dialogs=lambda:[dialog]
            s._dismiss_duplicate=lambda _:self.fail('unsafe dismissal')
            s._check_duplicate()

    def test_manual_dismissal_signal(self):
        s=self.session();s._dismiss_duplicate=lambda _:False
        with self.assertRaises(DuplicateExistingDocument) as raised:s._check_duplicate()
        self.assertFalse(raised.exception.dismissed)

    def test_reference_requires_live_pre_tab_identity(self):
        s=self.session();s._duplicate_context=None;s._supplier_entered=True;s._active_ted=lambda:99
        s.before_field_commit('invoice',dict(vat='123',invoice='INV'))
        self.assertIsNone(s._duplicate_context)
        s._active_ted=lambda:30
        s.before_field_commit('invoice',dict(vat='123',invoice='INV'))
        self.assertEqual(s._duplicate_context['invoice'],'INV')

    def test_ambiguous_dialogs_do_not_dismiss(self):
        s=self.session();dialog=s._duplicate_dialogs()[0]
        s._duplicate_dialogs=lambda:[dialog,dict(dialog,handle=42)]
        s._dismiss_duplicate=lambda _:self.fail('ambiguous dismissal')
        s._check_duplicate()

    def test_dismiss_revalidates_without_clicking(self):
        s=self.session();dialog=s._duplicate_dialogs()[0]
        s._duplicate_dialogs=lambda:[dict(dialog,body='changed')]
        self.assertFalse(WindowsSession._dismiss_duplicate(s,dialog))

    def test_new_invalidates_previous_document_provenance(self):
        s=self.session()
        def stop():raise RuntimeError('stop before native work')
        s._start_ebs=stop
        with self.assertRaises(RuntimeError):s.open_new((0,0))
        self.assertIsNone(s._duplicate_context)

    def test_vat_same_editor_stops_before_reference(self):
        s=self.session();s._active_ted=lambda:30;s._focused_ted_editor=lambda point=None:50
        s.before_field_commit('vat',dict(vat='123',invoice='INV'))
        with patch('app.infrastructure.ebs_adapter.session.time.monotonic',side_effect=[0,0,3]),patch('app.infrastructure.ebs_adapter.session.time.sleep'):
            with self.assertRaises(CreditorResolutionRequired) as raised:s.field_completed('vat',dict(vat='123',invoice='INV'))
        self.assertEqual((raised.exception.vat,raised.exception.invoice,raised.exception.expected_ted),('123','INV',30))
        self.assertFalse(s._supplier_entered)

    def test_vat_changed_or_unknown_editor_continues(self):
        for before,after in [(50,51),(None,None),(50,None)]:
            s=self.session();s._active_ted=lambda:30;s._focused_ted_editor=lambda point=None:before
            s.before_field_commit('vat',dict(vat='123',invoice='INV'))
            s._focused_ted_editor=lambda:after
            s.field_completed('vat',dict(vat='123',invoice='INV'))
            self.assertTrue(s._supplier_entered)
