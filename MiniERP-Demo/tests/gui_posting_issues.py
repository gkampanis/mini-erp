"""Synthetic posting issues navigation; no Entersoft input."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.ui.posting_issues import open_issues
from app.ui.text_editing import perform


class PostingIssuesGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.root=tk.Tk();cls.root.withdraw()
    @classmethod
    def tearDownClass(cls):cls.root.destroy()
    def setUp(self):
        self.owner=SimpleNamespace(root=self.root,company=7,erp=SimpleNamespace(detail=Mock(return_value=(dict(series='S',number='11',name='SYNTHETIC',vat='123'),[]))),busy=False,
            rpa_panel=SimpleNamespace(running=False,settings=Mock()),reconciliation=SimpleNamespace(show_document_comparison=Mock()),open_detail=Mock(),choose_excel=Mock())
        self.service=Mock();self.service.inspect.return_value=[dict(document=11,reference='S/11',name='SYNTHETIC',reason='Excel missing reference',posting_permitted=False,signature='sig')]
        p=patch('app.application.review_permissions.ReviewPermissions',return_value=self.service);p.start();self.addCleanup(p.stop)
        self.retry=Mock();self.win=None;self.addCleanup(self.close)
    def close(self):
        if self.win is not None and self.win.winfo_exists():self.win.destroy()
    def open(self,rows=None):
        self.win=open_issues(self.owner,rows or [dict(document=11,reason='Excel missing reference')],self.retry)
        self.root.update();return self.win
    def test_all_rows_and_original_reason_copyable(self):
        win=self.open([dict(document=11,reason='Excel missing reference'),dict(document=12,reason='Different error')])
        self.assertEqual(len(win.issue_tree.get_children()),2)
        text=win.issue_reason;text.tag_add('sel','1.0','end-1c');perform(text,'copy');self.root.update()
        self.assertEqual(self.root.clipboard_get(),'Excel missing reference')
        self.assertEqual(str(text.cget('state')),'disabled')
        self.service.authorize.assert_not_called()
    def test_comparison_and_review_target_selected_document(self):
        win=self.open();win.issue_buttons['compare'].invoke()
        self.owner.reconciliation.show_document_comparison.assert_called_once_with(11)
        with patch('app.ui.posting_review.open_review') as review:
            win.issue_buttons['review'].invoke()
        self.assertEqual(review.call_args.args[:2],(self.owner,self.service.inspect.return_value))
        self.assertIsNotNone(review.call_args.kwargs['on_authorized'])
        review.call_args.kwargs['on_authorized']([11]);self.retry.assert_called_once()
    def test_known_registered_has_no_mutating_shortcuts(self):
        self.service.inspect.return_value=[]
        win=self.open([dict(document=11,reason='Καταχωρισμένο')])
        for key in ('review','account','settings','import'):self.assertIn('disabled',win.issue_buttons[key].state())
        self.assertNotIn('disabled',win.issue_buttons['detail'].state())
    def test_account_mapping_and_retry_actions(self):
        self.service.inspect.return_value=[]
        win=self.open([dict(document=11,reason='Λείπει λογαριασμός και mapper')])
        with patch('app.ui.quick_account.open_account') as account:win.issue_buttons['account'].invoke()
        account.assert_called_once_with(self.owner,11)
        win.issue_buttons['settings'].invoke();self.owner.rpa_panel.settings.assert_called_once()
        win.issue_buttons['retry'].invoke();self.retry.assert_called_once();self.assertFalse(win.winfo_exists())
    def test_company_change_blocks_navigation(self):
        win=self.open();self.owner.company=8
        with patch('app.ui.posting_issues.messagebox.showerror') as error:win.issue_buttons['compare'].invoke()
        error.assert_called_once();self.owner.reconciliation.show_document_comparison.assert_not_called()

    def test_already_permitted_hides_review_and_excel_import_targets_ebs(self):
        self.service.inspect.return_value[0]['posting_permitted']=True
        win=self.open();self.assertIn('disabled',win.issue_buttons['review'].state())
        win.issue_buttons['import'].invoke();self.owner.choose_excel.assert_called_once_with(purpose='ebs')

    def test_purchase_exclusion_does_not_offer_unrelated_corrections(self):
        self.service.inspect.return_value=[]
        win=self.open([dict(document=11,reason='Αγορές, έσοδα ή μη υποστηριζόμενο είδος · εκτός RPA')])
        for key in ('review','account','settings','import','compare'):self.assertIn('disabled',win.issue_buttons[key].state())

    def test_changing_selection_opens_exact_document(self):
        win=self.open([dict(document=11,reason='Excel first'),dict(document=12,reason='Excel second')])
        win.issue_tree.selection_set('1');self.root.update()
        win.issue_buttons['detail'].invoke();self.owner.open_detail.assert_called_once_with(12)
        self.assertEqual(win.issue_reason.get('1.0','end-1c'),'Excel second')

    def test_backend_preparation_and_date_conflict_reasons_offer_matching_actions(self):
        self.service.inspect.return_value=[]
        win=self.open([dict(document=11,reason='Λείπει εγκεκριμένη προετοιμασία για το παραστατικό 11'),dict(document=12,reason='Χρειάζεται έλεγχος — διαφορετικά/ελλιπή: ημερομηνία')])
        self.assertNotIn('disabled',win.issue_buttons['account'].state())
        win.issue_tree.selection_set('1');self.root.update()
        self.assertNotIn('disabled',win.issue_buttons['compare'].state())
        self.assertNotIn('disabled',win.issue_buttons['import'].state())

    def test_probably_registered_review_remains_actionable(self):
        win=self.open([dict(document=11,reason='Μερική συμφωνία — Πιθανώς καταχωρισμένο: ίδια ημερομηνία, ΑΦΜ, καθαρή, ΦΠΑ και σύνολο.')])
        self.assertNotIn('disabled',win.issue_buttons['review'].state())
        self.assertNotIn('disabled',win.issue_buttons['compare'].state())
        self.assertNotIn('disabled',win.issue_buttons['import'].state())
