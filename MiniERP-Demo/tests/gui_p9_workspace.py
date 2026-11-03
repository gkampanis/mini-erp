"""P9 pending scope and three-action UI checks, with synthetic data only."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import gui_regressions as harness
from tests.fixtures import HEADERS, ROW, workbook


class P9Workspace(unittest.TestCase):
    setUpClass = classmethod(harness.DesktopRegressions.setUpClass.__func__)
    tearDownClass = classmethod(harness.DesktopRegressions.tearDownClass.__func__)
    setUp = harness.DesktopRegressions.setUp
    tearDown = harness.DesktopRegressions.tearDown
    button = harness.DesktopRegressions.button
    count = harness.DesktopRegressions.count
    open_preview = harness.DesktopRegressions.open_preview
    commit = harness.DesktopRegressions.commit
    close_children = harness.DesktopRegressions.close_children
    import_fixture = harness.DesktopRegressions.import_fixture
    continuous_batch_fixture = harness.DesktopRegressions.continuous_batch_fixture

    def test_posting_hotkey_hint_stays_visible_without_covering_actions(self):
        from app.ui.rpa_panel import HOTKEY_HINT
        panel=self.app.rpa_panel;hint=panel.hotkey_hint;root=self.app.root
        self.assertEqual(hint.cget('text'),HOTKEY_HINT)
        for key in ('Ctrl+Shift','F9','F10','F12'):self.assertIn(key,HOTKEY_HINT)
        self.assertFalse(self.app._documents)
        root.state('normal')
        for mode in ('dark','light'):
            self.app.change_theme(mode)
            for size in ('960x650','1440x860'):
                root.geometry(size);root.update()
                self.assertTrue(hint.winfo_ismapped())
                actions=[panel.buttons[key] for key in ('post','selected','one')]
                for button in actions:self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth())
                self.assertLessEqual(actions[-1].winfo_x()+actions[-1].winfo_width(),hint.winfo_x())
                self.assertLessEqual(hint.winfo_x()+hint.winfo_width(),hint.master.winfo_width())
                self.assertGreaterEqual(hint.winfo_width(),hint.winfo_reqwidth())

    def test_unreconciled_received_values_visible_but_not_postable(self):
        from app.infrastructure.importers.excel import preview
        from app.application.rpa import RPA
        row=list(ROW);row[8]=''
        workbook(self.folder/'pending.xlsx',[HEADERS,row])
        app=self.app;app.erp.commit_import(app.company,preview(self.folder/'pending.xlsx'),confirmed=True)
        app.state_filter.set('Μη καταχωρισμένα');app.refresh()
        self.assertEqual(len(app._documents),1)
        document=next(iter(app._documents))
        self.assertEqual(app._evidence[document]['status'],'unreconciled')
        self.assertIn('συμφωνία',app._documents[document]['preparation_state'])
        self.assertEqual(RPA(app.erp).plan(app.company,[document])['documents'],[])

    def test_all_filters_keep_pending_scope_and_nonfinancial_exclusion(self):
        from app.application.mydata import MyData
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.infrastructure.aade.client import parsed_page
        from tests.test_workflow import response
        from tests.test_supplier_purchases import synthetic_vat
        from app.ui.desktop import STATES
        app=self.app;api=MyData(app.erp);supplier=synthetic_vat(1)
        for index,(code,outgoing,delivery) in enumerate([('1.1',False,True),('5.1',False,False),('8.6',False,False),('9.3',False,False),('10.1',False,False),('1.1',True,False),('1.1',False,False)]):
            xml=response(mark=str(99920001+index),number=str(index+1),issuer='000000000' if outgoing else supplier,receiver=synthetic_vat(2) if outgoing else '000000000')
            xml=xml.replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType>'.encode())
            if delivery:xml=xml.replace(b'</invoiceHeader>',b'<isDeliveryNote>true</isDeliveryNote></invoiceHeader>')
            method='RequestTransmittedDocs' if outgoing else 'RequestDocs'
            api.persist(app.company,'production','2026-10-01','2026-10-31',[(xml,parsed_page(xml))],method)
            api.import_documents(app.company,'production','2026-10-01','2026-10-31',confirmed=True,direction='outgoing' if outgoing else 'incoming')
        docs={r['number']:r['id'] for r in app.erp.search(app.company)}
        registered=docs['7'];EBSReconciliation(app.erp).confirm_manual(app.company,registered,'synthetic',confirmed=True)
        expected={docs['1'],docs['2']}
        app.refresh()
        for state in (*STATES,'Καταχωρισμένα'):
            app.state_filter.set(state);app.filter_documents()
            self.assertLessEqual(set(app._documents),expected,state)
            self.assertEqual(app.notebook.tab(app.documents_tab,'text'),'Μη καταχωρισμένα στο EBS')
            app.column_filters.cell('vat','none');app.column_filters.clear(notify=True)
            self.assertLessEqual(set(app._documents),expected)
        app.state_filter.set('Μη καταχωρισμένα');app.refresh()
        self.assertEqual(set(app._documents),expected)
        app.group_filter.set('Όλες οι ομάδες');app.column_filters.cell('vat',supplier)
        app.query.set('missing');self.button(app.documents_tab,'Καθαρισμός').invoke()
        self.assertEqual(set(app._documents),expected)
        self.assertTrue(app.column_filters.cell_filters)
        app.column_filters.clear(notify=True);app.refresh()
        self.assertEqual(set(app._documents),expected)
        app.reconciliation.filter.set('Καταχωρισμένα');app.reconciliation.refresh(app._evidence)
        self.assertEqual(set(map(int,app.reconciliation.tree.get_children())),{registered})

    def test_posting_three_actions_pass_existing_limit_without_simulation(self):
        from tests.gui_smoke import wait
        app=self.app;panel=app.rpa_panel
        for index in range(3):app.tree.insert('','end',iid=str(index+1))
        app._documents={i:dict(source_record_id=i) for i in range(1,4)}
        app.tree.selection_set('2')
        for action,ids,kwargs in ((panel.post,[1,2,3],{'limit':40}),(panel.post_selected,[2],{}),(panel.post_one,[2],{})):
            with patch('app.ui.rpa_panel.sys',SimpleNamespace(platform='win32')),patch('ctypes.windll',SimpleNamespace(user32=SimpleNamespace(GetAsyncKeyState=lambda _:0)),create=True),patch('app.application.rpa.RPA.posting',return_value=dict(job=None,skipped=[])) as posting,patch('app.application.vat_lines.VATLines.posting_requirements',return_value=[]) as requirements,patch('app.application.review_permissions.ReviewPermissions.inspect',return_value=[]) as reviews,patch('app.ui.posting_issues.open_issues'),patch('app.ui.rpa_panel.messagebox.showerror'),patch('app.ui.rpa_panel.messagebox.askyesno') as confirm:
                action();wait(self.root,lambda:not app.busy)
                posting.assert_called_once_with(app.company,ids,**kwargs)
                requirements.assert_called_once_with(app.company,ids)
                reviews.assert_called_once_with(app.company,ids)
                confirm.assert_not_called()
        self.assertEqual(panel.buttons['post'].cget('text'),'Καταχώριση έως 40')

    def choose(self,path,*,purpose='documents'):
        from tests.gui_smoke import wait
        with patch('app.ui.desktop.filedialog.askopenfilename',return_value=str(path)):
            self.app.choose_excel(purpose=purpose)
        wait(self.root,lambda:not self.app.busy)
        return self.app.preview_window

    def test_two_explicit_import_actions_keep_their_business_purpose(self):
        from tests.gui_smoke import wait,widgets
        from tkinter import ttk
        self.assertTrue(hasattr(self.app,'ebs_import_button'),'A separate EBS evidence action is required')
        self.assertEqual(self.app.import_button.cget('text'),'Εισαγωγή βιβλίου ΑΑΔΕ')
        self.assertEqual(self.app.ebs_import_button.cget('text'),'Έλεγχος καταχωρημένων EBS')
        path=self.folder/'purpose.xlsx';workbook(path,[[f'Column{i}' for i in range(6)]])
        for action,ebs in ((self.app.import_button,False),(self.app.ebs_import_button,True)):
            with patch('app.ui.desktop.filedialog.askopenfilename',return_value=str(path)):
                action.invoke();wait(self.root,lambda:not self.app.busy)
            win=self.app.preview_window
            self.assertEqual(hasattr(win,'mapping_vars'),ebs)
            self.assertFalse(any(isinstance(w,ttk.Combobox) and w.get()=='Επίλεξε περιεχόμενο αρχείου' for w in widgets(win)))
            self.app._dismiss_preview()

    def test_explicit_ebs_import_checks_evidence_without_importing_documents(self):
        from tests.gui_smoke import widgets
        from tkinter import ttk
        path=self.folder/'ebs.xlsx'
        workbook(path,[['Ημ/νία','Παρ/κό','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21','INTERNAL','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        win=self.choose(path,purpose='ebs')
        self.assertIsNone(win)
        import json
        mapping=json.loads(self.app.erp.db.execute('SELECT mapping_json FROM ebs_column_mappings WHERE company_id=?',(self.app.company,)).fetchone()[0])
        self.assertEqual(mapping['invoice'],2)
        self.assertEqual(self.count('documents'),0)

    def test_known_ebs_file_removes_matches_without_a_confirmation_window(self):
        from app.infrastructure.importers.excel import preview
        from tests.gui_smoke import wait
        self.app.erp.commit_import(self.app.company,preview(self.folder/'inputs/separate.xlsx'),confirmed=True)
        self.app.refresh();before=set(self.app._documents)
        path=self.folder/'automatic-ebs.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        self.choose(path,purpose='ebs');wait(self.root,lambda:not self.app.busy)
        self.assertFalse(self.app._has_preview(),'Known EBS files must apply directly')
        self.assertEqual(len(before-set(self.app._documents)),1)
        self.assertEqual(self.count('documents'),2)

    def test_optional_ebs_column_mapping_opens_known_file_without_applying_on_cancel(self):
        from tests.gui_smoke import wait,widgets
        from tkinter import ttk
        self.assertIn('Αντιστοίχιση στηλών EBS',[w.cget('text') for w in widgets(self.app.reconciliation_tab) if isinstance(w,ttk.Button)])
        path=self.folder/'manual-ebs.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        with patch('app.ui.desktop.filedialog.askopenfilename',return_value=str(path)):
            self.button(self.app.reconciliation_tab,'Αντιστοίχιση στηλών EBS').invoke()
            wait(self.root,lambda:not self.app.busy)
        win=self.app.preview_window
        self.assertTrue(self.app._has_preview())
        self.assertEqual(win.pages.select(),str(win.mapping_page))
        self.assertEqual(self.count('ebs_reconciliation_runs'),0)
        self.assertEqual(self.count('ebs_column_mappings'),0)
        self.app._dismiss_preview()
        self.assertEqual(self.count('ebs_reconciliation_runs'),0)

    def test_manual_column_reassignment_is_applied_and_reused_by_automatic_import(self):
        from app.infrastructure.importers.excel import preview
        from tests.gui_smoke import wait,widgets
        from tkinter import ttk
        import json
        self.assertIn('Αντιστοίχιση στηλών EBS',[w.cget('text') for w in widgets(self.app.reconciliation_tab) if isinstance(w,ttk.Button)])
        self.app.erp.commit_import(self.app.company,preview(self.folder/'inputs/separate.xlsx'),confirmed=True)
        self.app.refresh();before=set(self.app._documents)
        path=self.folder/'override-ebs.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο','Αριθμός τιμολογίου'],['2026-10-21','OTHER123','000000001','0.10','0.02','0.12','ΔΟΚ/1']])
        with patch('app.ui.desktop.filedialog.askopenfilename',return_value=str(path)):
            self.button(self.app.reconciliation_tab,'Αντιστοίχιση στηλών EBS').invoke()
            wait(self.root,lambda:not self.app.busy)
        win=self.app.preview_window
        win.mapping_vars['invoice'].set('7: Αριθμός τιμολογίου')
        self.button(win,'Εφαρμογή').invoke();wait(self.root,lambda:not self.app.busy)
        self.assertFalse(self.app._has_preview())
        self.assertEqual(len(before-set(self.app._documents)),1)
        self.assertEqual(self.count('documents'),2)
        saved=json.loads(self.app.erp.db.execute('SELECT mapping_json FROM ebs_column_mappings WHERE company_id=?',(self.app.company,)).fetchone()[0])
        self.assertEqual(saved['invoice'],6)
        self.choose(path,purpose='ebs');wait(self.root,lambda:not self.app.busy)
        self.assertFalse(self.app._has_preview())
        self.assertEqual(len(before-set(self.app._documents)),1)
        self.assertEqual(self.count('documents'),2)

    def test_competing_local_copies_leave_pending_without_becoming_two_registered_entries(self):
        from app.infrastructure.importers.excel import preview
        from app.application.rpa import RPA
        rows=[]
        for series in ('A','B'):
            row=list(ROW);row[2]=series;row[3]='17';row[8]='';rows.append(row)
        source=self.folder/'copies.xlsx';workbook(source,[HEADERS,*rows])
        self.app.erp.commit_import(self.app.company,preview(source),confirmed=True);self.app.refresh()
        before=set(self.app._documents);self.assertEqual(len(before),2)
        path=self.folder/'posted.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21','/17','000000001','0.10','0.02','0.12']])
        self.choose(path,purpose='ebs')
        self.assertFalse(self.app.tree.get_children())
        self.assertTrue(all(r['status']=='review' and r['match_kind']=='ambiguous' and r['file_matched'] for r in self.app._evidence.values()))
        self.assertEqual(RPA(self.app.erp).plan(self.app.company,list(before))['documents'],[])
        self.app.reset_filters();self.app.column_filters.clear(notify=True);self.app.refresh()
        self.assertFalse(self.app.tree.get_children());self.assertEqual(self.count('documents'),2)
        self.app._dismiss_preview()
        self.assertIsNone(self.choose(path,purpose='documents'))
        self.assertIn('Έλεγχος καταχωρημένων EBS',self.app.status.get())
        self.assertEqual(self.count('documents'),2)

    def test_unknown_workbook_uses_explicit_ebs_purpose_without_role_guessing(self):
        import tkinter as tk
        from tkinter import ttk
        from tests.gui_smoke import widgets
        from app.ui.excel_mapping import ColumnMapping
        path=self.folder/'unknown.xlsx'
        workbook(path,[[f'Column{i}' for i in range(6)],['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        win=self.choose(path,purpose='ebs')
        self.assertTrue(hasattr(win,'mapping_vars'))
        self.assertIs(self.app.preview_window,win)
        self.assertEqual(sum(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()),1)
        self.assertEqual(sum(isinstance(w,ColumnMapping) for w in widgets(win)),1)
        self.assertEqual(self.count('documents'),0)

    def test_automatic_ebs_import_preserves_supplier_filter_and_ready_remaining_expense(self):
        from copy import deepcopy
        from app.infrastructure.importers.excel import preview
        from app.application.supplier_accounts import SupplierAccounts
        from app.application.rpa import RPA
        from tests.fixtures import reconcile_empty
        rows=[]
        for number in ('17','18'):
            row=list(ROW);row[3]=number;row[8]='';rows.append(row)
        other=list(ROW);other[0]='000000002';other[3]='99';other[8]='';rows.append(other)
        path=self.folder/'local-expenses.xlsx';workbook(path,[HEADERS,*rows])
        app=self.app;app.erp.commit_import(app.company,preview(path),confirmed=True)
        reconcile_empty(app.erp,app.company)
        documents={r['number']:r for r in app.erp.search(app.company)}
        SupplierAccounts(app.erp).save(app.company,[documents['17']['counterparty_id']],'6','64.03',confirmed=True)
        app.refresh();app.column_filters.cell('vat','000000001')
        filters=deepcopy(app.column_filters.cell_filters);state=app.state_filter.get()
        path=self.folder/'ebs-filtered.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],['2026-10-21','ΔΟΚ/17','000000001','0.10','0.02','0.12']])
        self.choose(path,purpose='ebs')
        self.assertEqual(set(app._documents),{documents['18']['id']})
        self.assertEqual(app.column_filters.cell_filters,filters);self.assertEqual(app.state_filter.get(),state)
        self.assertEqual(RPA(app.erp).plan(app.company,[documents['18']['id']])['documents'],[documents['18']['id']])

    def test_raw_recheck_uses_same_window_and_original_frozen_file(self):
        from tests.gui_smoke import wait
        path=self.folder/'raw.xlsx';row=list(ROW);row[8]=''
        workbook(path,[HEADERS,row]);win=self.choose(path)
        win.column_mapping.variables['name'].set('—')
        changed=list(row);changed[3]='REPLACEMENT';workbook(path,[HEADERS,changed])
        self.button(win,'Επανέλεγχος αντιστοίχισης').invoke();wait(self.root,lambda:not self.app.busy)
        self.assertIs(self.app.preview_window,win)
        with patch('app.ui.desktop.messagebox.askyesno') as redundant_popup:
            self.button(win,'Επιβεβαιώνω εισαγωγή').invoke();wait(self.root,lambda:not self.app.busy)
            redundant_popup.assert_not_called()
        self.assertEqual([r['number'] for r in self.app.erp.search(self.app.company)],['1'])
        self.assertEqual(self.count('import_jobs'),1)

    def test_upto40_does_not_automatically_resume_oversized_previous_queue(self):
        ids=self.continuous_batch_fixture(count=41);app=self.app;panel=app.rpa_panel
        job=panel.rpa.posting(app.company,ids)['job'];panel.rpa.pause(app.company,job)
        before=[tuple(r) for r in app.erp.db.execute('SELECT * FROM rpa_items WHERE job_id=?',(job,))]
        with patch('app.ui.rpa_panel.sys',SimpleNamespace(platform='win32')),patch.object(panel,'start') as start,patch.object(app,'run_worker',side_effect=lambda execute,done:done(execute())):
            panel.post();start.assert_not_called()
        self.assertEqual(panel.job,job)
        self.assertEqual([tuple(r) for r in app.erp.db.execute('SELECT * FROM rpa_items WHERE job_id=?',(job,))],before)
        self.assertIn('Συνέχεια',panel.state.get())
        self.assertTrue(panel.buttons['resume'].instate(['!disabled']))

    def test_cancel_during_raw_recheck_does_not_reopen_or_report_callback_error(self):
        import threading
        from tests.gui_smoke import wait
        from app.infrastructure.importers.excel import preview
        win=self.open_preview();release=threading.Event();entered=threading.Event();self.releases.append(release)
        def slow_preview(*args,**kwargs):
            entered.set();release.wait(5);return preview(*args,**kwargs)
        with patch('app.ui.desktop.preview',side_effect=slow_preview),patch('app.ui.desktop.messagebox.showerror') as error:
            self.button(win,'Επανέλεγχος αντιστοίχισης').invoke()
            self.assertTrue(entered.wait(5))
            self.button(win,'Ακύρωση').invoke();release.set();wait(self.root,lambda:not self.app.busy)
            error.assert_not_called()
        self.assertFalse(self.app._has_preview());self.assertEqual(self.count('documents'),0)
