"""Integration of posting scope callbacks and the actual comparison window."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from app.ui.rpa_panel import RPAPanel
from app.ui.ebs_reconciliation import ReconciliationTab


class ReviewFlowGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.root=tk.Tk();cls.root.withdraw()
    @classmethod
    def tearDownClass(cls):cls.root.destroy()
    def setUp(self):
        self.tree=ttk.Treeview(self.root)
        self.addCleanup(self.tree.destroy)
        for doc in (30,10,20):self.tree.insert('','end',iid=str(doc))
        self.tree.selection_set(('30','10','20'))
        self.service=Mock();self.service.db.execute.return_value.fetchone.return_value=None
        self.owner=SimpleNamespace(root=self.root,tree=self.tree,company=7,directory='synthetic-only',erp=self.service,
                                   busy=False,_closing=False,refresh=Mock())
        self.owner.run_worker=lambda execute,done:done(execute())
        self.panel=RPAPanel.__new__(RPAPanel);self.panel.owner=self.owner;self.panel.running=False
        self.panel.notify=Mock();self.panel.refresh=Mock();self.panel.start=Mock();self.panel.job=None
        self.backend=Mock();self.backend.posting.return_value=dict(job=9,documents=[30,10],skipped=[],pilot=False)
        for target,kwargs in [('app.ui.rpa_panel.ERP',dict(return_value=self.service)),
                              ('app.ui.rpa_panel.RPA',dict(return_value=self.backend)),
                              ('app.application.review_permissions.ReviewPermissions.inspect',dict(return_value=[])),
                              ('app.application.vat_lines.VATLines.posting_requirements',dict(return_value=[])),
                              ('app.ui.rpa_panel.sys',dict(new=SimpleNamespace(platform='win32')))]:
            patcher=patch(target,**kwargs);value=patcher.start();self.addCleanup(patcher.stop)
            if target.endswith('.inspect'):self.inspect=value
        self.addCleanup(self.close_windows)
    def close_windows(self):
        for child in self.root.winfo_children():
            if isinstance(child,tk.Toplevel):child.destroy()
        self.root.update_idletasks()

    def test_review_precedes_queue_and_checked_subset_preserves_ready_document_order(self):
        requirements=[dict(document=10,signature='a',reason='Review'),dict(document=20,signature='b',reason='Review')]
        self.inspect.side_effect=[requirements,[]]
        with patch('app.ui.posting_review.open_review') as review:
            self.panel.post_selected()
            self.backend.posting.assert_not_called();self.panel.start.assert_not_called()
            self.assertEqual(review.call_args.args[1],requirements)
            review.call_args.kwargs['on_authorized']([10])
        self.backend.posting.assert_called_once_with(7,[30,10])
        self.panel.start.assert_called_once();self.assertEqual(self.panel.job,9)

    def test_vat_mapping_continuation_keeps_authorized_subset(self):
        reviews=[dict(document=10,signature='a',reason='Review'),dict(document=20,signature='b',reason='Review')]
        requirements=[dict(document=10,analysis=dict(status='verified'),missing=[(2,0)])]
        self.inspect.side_effect=[reviews,[],[]]
        with patch('app.application.vat_lines.VATLines.posting_requirements',side_effect=[requirements,[]]),patch('app.ui.vat_accounts.open_rules') as rules,patch('app.ui.posting_review.open_review') as review:
            self.panel.post_selected()
            review.call_args.kwargs['on_authorized']([10])
            self.backend.posting.assert_not_called()
            rules.call_args.kwargs['on_saved']()
        self.backend.posting.assert_called_once_with(7,[30,10])
        self.assertEqual([call.args[1] for call in self.inspect.call_args_list],[[30,10,20],[30,10],[30,10]])
        self.panel.start.assert_called_once()

    def test_no_eligible_queue_shows_every_skip_and_retry_scope(self):
        skips=[dict(document=30,reason='XML invalid'),dict(document=10,reason='Missing mapping'),dict(document=20,reason='Account missing')]
        self.backend.posting.return_value=dict(job=None,documents=[],skipped=skips,pilot=False)
        with patch('app.ui.posting_issues.open_issues') as issues,patch('app.ui.rpa_panel.messagebox.showinfo') as info:
            self.panel.post_selected()
            self.assertEqual(issues.call_args.args[1],skips);self.panel.start.assert_not_called();info.assert_not_called()
            with patch.object(self.panel,'posting') as retry:issues.call_args.kwargs['on_retry']()
            retry.assert_called_once_with('selected',documents_override=[30,10,20])

    def test_completed_partial_queue_retry_contains_only_skipped_documents(self):
        skipped=[dict(document=20,reason='XML invalid')]
        self.panel.job=9;self.panel.running=True;self.panel.pause_requested=False;self.panel.stop_requested=False
        self.panel._posting_skipped=list(skipped);self.panel._posting_scope=None
        self.panel.rpa=Mock();self.panel.rpa.items.return_value=(dict(mode='simulation',status='running'),[])
        self.panel.state=Mock();self.backend.advance.return_value=dict(status='completed')
        with patch('app.ui.posting_issues.open_issues') as issues:
            self.panel.next_item()
            self.assertEqual(issues.call_args.args[1],skipped)
            with patch.object(self.panel,'posting') as retry:issues.call_args.kwargs['on_retry']()
            retry.assert_called_once_with('selected',documents_override=[20])
        self.assertEqual(self.panel._posting_skipped,[])

    def test_direct_comparison_preserves_excel_error_cell_and_missing_reference(self):
        row=dict(id=30,status='review',reason='Excel error',match_kind='invalid',issue_date='2026-10-21',vat='000000001',
                 series='VALID',number='123',net_minor=10000,tax_minor=2400,gross_minor=12400)
        entry=dict(row_number=6,error='C6: missing invoice reference',original_reference='',normalized=dict(date='2026-10-21',vat='000000001',net_minor=10000,tax_minor=2400,gross_minor=12400))
        tab=ReconciliationTab.__new__(ReconciliationTab);tab.owner=self.owner;tab.service=Mock()
        tab.service.evidence.return_value=(row,[entry]);self.owner.rpa_panel=self.panel
        win=tab.show_document_comparison(30);self.root.update()
        values=[win.comparison_tree.item(key,'values') for key in win.comparison_tree.get_children()]
        self.assertIn(('Πρόβλημα / κελί Excel','','C6: missing invoice reference'),values)
        self.assertIn(('Παραστατικό','VALID/123',''),values)
        tab.service.evidence.assert_called_once_with(7,30)


from tests import gui_regressions as desktop_harness


class AuthorizedPendingVisibilityGUI(unittest.TestCase):
    setUpClass=classmethod(desktop_harness.DesktopRegressions.setUpClass.__func__)
    tearDownClass=classmethod(desktop_harness.DesktopRegressions.tearDownClass.__func__)
    setUp=desktop_harness.DesktopRegressions.setUp
    tearDown=desktop_harness.DesktopRegressions.tearDown

    def test_real_excel_permission_exposes_only_authorized_pending_and_registered_stays_hidden(self):
        from app.infrastructure.importers.excel import preview
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.application.review_permissions import ReviewPermissions
        from tests.fixtures import HEADERS,ROW,workbook
        app=self.app;rows=[]
        for series in ('A','B'):
            row=list(ROW);row[2]=series;row[3]='17';row[8]='';rows.append(row)
        source=self.folder/'review-copies.xlsx';workbook(source,[HEADERS,*rows])
        app.erp.commit_import(app.company,preview(source),confirmed=True)
        book=self.folder/'ambiguous-export.xlsx'
        workbook(book,[['Date','Reference','VAT','Net','Tax','Gross'],['2026-10-21','/17','000000001','0.10','0.02','0.12']])
        service=EBSReconciliation(app.erp)
        company_vat=app.erp.db.execute('SELECT vat FROM companies WHERE id=?',(app.company,)).fetchone()[0]
        packet=service.preview(app.company,book,'Συνθετικά',1,dict(date=0,invoice=1,vat=2,net=3,tax=4,gross=5),
                               '2026-10-01','2026-10-31',company_vat,complete=True,company_confirmed=True)
        service.commit(packet,confirmed=True)
        app.state_filter.set('Μη καταχωρισμένα');app.refresh()
        documents=service.documents(app.company);self.assertEqual(len(documents),2)
        ids=[row['id'] for row in documents]
        self.assertFalse(app.tree.get_children())
        self.assertTrue(all(app._evidence[doc]['file_matched'] for doc in ids))
        permission=ReviewPermissions(app.erp);candidate=permission.inspect(app.company,[ids[0]])[0]
        permission.authorize(app.company,[ids[0]],expected_signatures={ids[0]:candidate['signature']},confirmed=True)
        app.refresh()
        self.assertEqual(tuple(map(int,app.tree.get_children())),(ids[0],))
        self.assertEqual(app._evidence[ids[0]]['status'],'review')
        self.assertTrue(app._evidence[ids[0]]['posting_permitted'])
        win=app.reconciliation.show_document_comparison(ids[0])
        from tests.gui_smoke import widgets
        buttons=[widget for widget in widgets(win) if isinstance(widget,ttk.Button)]
        button=next(widget for widget in buttons if widget.cget('text')=='Καταχώριση στο EBS')
        with patch.object(app.rpa_panel,'posting') as post,patch('app.ui.posting_review.open_review') as repeat:
            button.invoke();post.assert_called_once_with('selected',documents_override=[ids[0]])
            repeat.assert_not_called()
        win.destroy()
        service.confirm_manual(app.company,ids[0],'Synthetic visual confirmation',confirmed=True)
        app.refresh();self.assertEqual(app._evidence[ids[0]]['status'],'registered')
        self.assertFalse(app.tree.get_children())


if __name__=='__main__':unittest.main()
