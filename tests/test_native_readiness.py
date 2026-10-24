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
    def test_new_ted_is_explicitly_activated_before_prepare_can_fill_it(self):
        user,session=self.make(active=201);session.pg=Mock()
        state={'active':201}
        session._mdi_forms.side_effect=lambda:{201,202} if session.pg.click.called else {201}
        def message(hwnd,msg,wp,lp,flags,ms,result):
            if msg==0x0222:state['active']=wp;result._obj.value=0
            elif msg==0x0229:result._obj.value=state['active']
            return 1
        user.SendMessageTimeoutW.side_effect=message
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            fresh=session.open_new((30,40))
            self.assertEqual(fresh,202)
            self.assertEqual(session.prepare({'save':(10,20),'new':(30,40)},fresh),fresh)
        activation=[c.args for c in user.SendMessageTimeoutW.call_args_list if c.args[1]==0x0222]
        self.assertEqual(len(activation),1);self.assertEqual(activation[0][2],202)
        session.pg.click.assert_called_once_with(30,40)
    def test_fresh_activation_rejects_unknown_handle_and_another_process(self):
        user,session=self.make()
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            with self.assertRaises(RuntimeError):session._activate_fresh_ted(999)
            session.pid=77
            with self.assertRaises(RuntimeError):session._activate_fresh_ted(202)
        self.assertFalse(any(c.args[1]==0x0222 for c in user.SendMessageTimeoutW.call_args_list))
    def test_open_new_does_not_return_a_handle_recreated_during_activation(self):
        user,session=self.make(active=201);session.pg=Mock()
        state={'active':201,'new':202}
        session._mdi_forms.side_effect=lambda:{201,state['new']} if session.pg.click.called else {201}
        user.GetParent.side_effect=lambda h:150 if h in (201,202,203) else 100 if h==150 else 0
        def message(hwnd,msg,wp,lp,flags,ms,result):
            if msg==0x0222:
                # WinForms can recreate its HWND while applying layout/DPI.
                state['new']=203;state['active']=203;result._obj.value=0
            elif msg==0x0229:result._obj.value=state['active']
            return 1
        user.SendMessageTimeoutW.side_effect=message
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True):
            fresh=session.open_new((30,40))
            self.assertEqual(fresh,203)
            self.assertEqual(session.prepare({'save':(10,20),'new':(30,40)},fresh),203)
        session.pg.click.assert_called_once_with(30,40)
    def test_mapping_point_on_an_old_ted_cannot_be_typed_even_in_same_ebs_process(self):
        from app.infrastructure.ebs_adapter.adapter import WindowsAdapter
        user,session=self.make();session.expected_ted=202
        user.WindowFromPoint=Mock(return_value=220)
        parent=user.GetParent.side_effect
        user.GetParent.side_effect=lambda h:201 if h==220 else parent(h)
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(WindowsAdapter,'validate_target',return_value=(10,20)):
            with self.assertRaisesRegex(RuntimeError,'δεν ανήκει'):session.validate_target('AFM_CREDITOR',(10,20))
            user.GetParent.side_effect=lambda h:202 if h==220 else parent(h)
            self.assertEqual(session.validate_target('AFM_CREDITOR',(10,20)),(10,20))

class HostedTEDTests(unittest.TestCase):
    """Exercise real enumeration, not a preselected list of supposed forms."""
    def graph(self,native=True):
        parents={100:0,150:100,201:150,202:150,211:201,221:202,223:202,222:223}
        titles={100:'Entersoft EBS ERP',211:'ΤΕΔ old',222:'ΤΕΔ new'}
        if not native:titles.update({201:'ΤΕΔ old',202:'ΤΕΔ new'})
        user=SimpleNamespace()
        user.parents=parents
        def thread(h,pid):pid._obj.value=9;return 11
        user.GetWindowThreadProcessId=Mock(side_effect=thread)
        user.GetParent=Mock(side_effect=lambda h:parents.get(h,0))
        def ancestor(h,flag):
            while parents.get(h):h=parents[h]
            return h
        user.GetAncestor=Mock(side_effect=ancestor)
        def title(h,buf,size):buf.value=titles.get(h,'');return len(buf.value)
        user.GetWindowTextW=Mock(side_effect=title)
        def cls(h,buf,size):
            buf.value='MDIClient' if h==150 and native else 'WindowsForms10.Window.app';return len(buf.value)
        user.GetClassNameW=Mock(side_effect=cls)
        user.IsWindowVisible=Mock(return_value=True)
        user.EnumWindows=Mock(side_effect=lambda cb,arg:cb(100,arg))
        def children(root,cb,arg):
            for h in parents:
                p=parents[h]
                while p:
                    if p==root:cb(h,arg);break
                    p=parents.get(p,0)
            return 1
        user.EnumChildWindows=Mock(side_effect=children)
        user.GetForegroundWindow=Mock(return_value=100)
        def info(tid,out):out._obj.hwndFocus=221;out._obj.hwndActive=100;return 1
        user.GetGUIThreadInfo=Mock(side_effect=info)
        def message(h,msg,wp,lp,flags,ms,out):out._obj.value=202;return 1
        user.SendMessageTimeoutW=Mock(side_effect=message)
        user.WindowFromPoint=Mock(return_value=221)
        session=WindowsSession.__new__(WindowsSession);session.pid=9;session.expected_ted=None
        session.at_ebs=Mock(return_value=100);session.health=Mock()
        return user,session

    def test_caption_descendant_is_resolved_to_real_mdi_document_and_sibling_field(self):
        from app.infrastructure.ebs_adapter.adapter import WindowsAdapter
        user,session=self.graph()
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True),patch.object(WindowsAdapter,'validate_target',return_value=(10,20)):
            self.assertEqual(session._mdi_forms(),{201,202})
            self.assertEqual(session.prepare({'save':(1,2),'new':(3,4),'mapping':{'AFM_CREDITOR':(10,20)}},202),202)
            session._active_ted=Mock(return_value=201)
            session._activate_fresh_ted(202)
            self.assertEqual(user.SendMessageTimeoutW.call_args.args[:3],(150,0x0222,202))
            user.WindowFromPoint.return_value=211
            with self.assertRaises(RuntimeError):session.validate_target('AFM_CREDITOR',(10,20))

    def test_custom_host_resolves_actual_focused_document_without_mdi_message(self):
        from app.infrastructure.ebs_adapter.adapter import WindowsAdapter
        user,session=self.graph(native=False)
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True),patch.object(WindowsAdapter,'validate_target',return_value=(10,20)):
            self.assertEqual(session._mdi_forms(),{201,202})
            self.assertEqual(session.prepare({'save':(1,2),'new':(3,4),'mapping':{'AFM_CREDITOR':(10,20)}},202),202)
            user.SendMessageTimeoutW.assert_not_called()
            # Inactive custom document is not activated through an invented MDI parent.
            session._activate_fresh_ted(201)
            user.SendMessageTimeoutW.assert_not_called()
            user.WindowFromPoint.return_value=211
            with self.assertRaises(RuntimeError):session.validate_target('AFM_CREDITOR',(10,20))

    def test_winforms_prefixed_mdi_class_uses_the_real_document(self):
        user,session=self.graph()
        original=user.GetClassNameW.side_effect
        def cls(h,buf,size):
            if h==150:buf.value='WindowsForms10.MDICLIENT.app.0.synthetic';return len(buf.value)
            return original(h,buf,size)
        user.GetClassNameW.side_effect=cls
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True):
            self.assertEqual(session._mdi_forms(),{201,202})
            self.assertEqual(session._active_ted(),202)

    def test_only_one_custom_ted_does_not_own_an_unrelated_sibling_page(self):
        user,session=self.graph(native=False)
        user.parents.update({250:150,251:250})
        user.IsWindowVisible.side_effect=lambda h:h not in (201,211)
        def info(tid,out):out._obj.hwndFocus=251;out._obj.hwndActive=100;return 1
        user.GetGUIThreadInfo.side_effect=info
        with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True):
            self.assertEqual(session._mdi_forms(),{202})
            self.assertIsNone(session._ted_for_window(251,{202}))
            self.assertIsNone(session._active_ted())

    def test_filtered_queue_runs_real_session_enumeration_fill_save_new_across_nested_teds(self):
        import itertools
        import tempfile
        from pathlib import Path
        from app.application.service import ERP
        from app.application.rpa import RPA
        from app.application.workspace import Workspace
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        from app.infrastructure.importers.excel import preview
        from tests.fixtures import HEADERS,ROW,workbook,reconcile_empty
        user,session=self.graph();session.pg=Mock()
        state={'active':202,'base':240,'new':False}
        for index in range(len(FIELDS)):user.parents[240+index]=202
        # Map every real field to a sibling of the nested TED caption.
        mapping={field:[10+i,20+i] for i,(field,_) in enumerate(FIELDS)}
        handles={tuple(mapping[f]):i for i,(f,_) in enumerate(FIELDS)}
        user.parents[600]=100
        user.WindowFromPoint.side_effect=lambda point:state['base']+handles[(point.x,point.y)] if (point.x,point.y) in handles else 600
        title=user.GetWindowTextW.side_effect
        def text(h,buf,size):
            if h==333:buf.value='ΤΕΔ new';return len(buf.value)
            return title(h,buf,size)
        user.GetWindowTextW.side_effect=text
        def message(h,msg,wp,lp,flags,ms,out):
            if msg==0x0222:state['active']=wp
            out._obj.value=state['active'];return 1
        user.SendMessageTimeoutW.side_effect=message
        def click(x,y):
            if (x,y)==(300,400):
                state.update(active=203,base=340,new=True)
                user.parents.update({203:150,333:203})
                for index in range(len(FIELDS)):user.parents[340+index]=203
        session.pg.click.side_effect=click
        # Run the actual process/root/control validation, not a mocked validator.
        del session.at_ebs
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);erp=ERP(root/'data')
            try:
                company=erp.company('000000008','SYNTHETIC')
                rows=[HEADERS]
                for vat,number in [('000000001','1'),('000000001','2'),('000000002','3')]:
                    row=list(ROW);row[0]=vat;row[2]='S';row[3]=number;row[8]='';rows.append(row)
                workbook(root/'sample.xlsx',rows)
                erp.commit_import(company,preview(root/'sample.xlsx'),confirmed=True);reconcile_empty(erp,company)
                ws=Workspace(erp)
                ws.approve_many(company,[dict(document=r['id'],group='6',account='64.03') for r in erp.search(company)],confirmed=True)
                ws.save_profile(company,dict(mapping=mapping,save=[100,200],new=[300,400]))
                with erp.db:erp.db.execute('UPDATE ebs_profiles SET pilot_at=CURRENT_TIMESTAMP WHERE company_id=?',(company,))
                visible=[r['id'] for r in erp.search(company) if r['vat']=='000000001'][::-1]
                rpa=RPA(erp);job=rpa.posting(company,visible)['job']
                with patch.object(ctypes,'windll',SimpleNamespace(user32=user),create=True),patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True),patch('time.sleep'),patch('time.monotonic',side_effect=itertools.count(0,.2)):
                    first=rpa.advance(company,job,adapter=session,live_confirmed=True)
                    second=rpa.advance(company,job,adapter=session,live_confirmed=True)
                self.assertEqual((first['status'],second['status']),('running','completed'))
                items=rpa.items(company,job)[1]
                self.assertEqual([i['document_id'] for i in items],visible)
                self.assertEqual([i['status'] for i in items],['ui_saved_review','save_invoked'])
                clicks=[c.args for c in session.pg.click.call_args_list]
                self.assertEqual(clicks.count((100,200)),2);self.assertEqual(clicks.count((300,400)),1)
                self.assertEqual(erp.db.execute("SELECT count(DISTINCT entity_id) FROM audit_events WHERE company_id=? AND action='rpa_save_invoked'",(company,)).fetchone()[0],2)
            finally:erp.close()
