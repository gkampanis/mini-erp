"""Synthetic UI review flow; never sends input to EBS."""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from app.ui.posting_review import open_review
from app.ui.text_editing import perform


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class PostingReviewGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=tk.Tk();cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):cls.root.destroy()

    def setUp(self):
        self.owner=SimpleNamespace(root=self.root,company=7,erp=object(),busy=False,
            rpa_panel=SimpleNamespace(running=False),refresh=Mock(),
            reconciliation=SimpleNamespace(show_document_comparison=Mock()))
        self.requirements=[dict(document=11,reference='TEST/11',name='SYNTHETIC ALPHA',reason='Excel totals differ',signature='sig11',status='review'),
                           dict(document=12,reference='TEST/12',name='SYNTHETIC BETA',reason='Missing in Excel',signature='sig12',status='not_found')]
        self.service=Mock();self.after=Mock()
        patcher=patch('app.application.review_permissions.ReviewPermissions',return_value=self.service)
        patcher.start();self.addCleanup(patcher.stop)
        self.errors=patch('app.ui.posting_review.messagebox.showerror');self.error=self.errors.start();self.addCleanup(self.errors.stop)
        self.win=None
        self.addCleanup(self.close_dialog)

    def close_dialog(self):
        if self.win is not None and self.win.winfo_exists():self.win.destroy()
        self.root.update_idletasks()

    def open(self,requirements=None):
        self.win=open_review(self.owner,self.requirements if requirements is None else requirements,self.after)
        self.root.update();return self.win

    def test_opening_grants_nothing_and_explicit_button_authorizes_only_checked_snapshot(self):
        win=self.open();self.service.authorize.assert_not_called()
        self.assertTrue(all(value.get() for value in win.review_vars.values()))
        win.review_vars[12].set(False);win.authorize_review()
        self.service.authorize.assert_called_once_with(7,[11],expected_signatures={11:'sig11'},confirmed=True)
        self.owner.refresh.assert_called_once();self.after.assert_called_once_with([11])
        self.assertFalse(win.winfo_exists())

    def test_comparison_opens_target_document_and_reason_is_copyable_readonly(self):
        win=self.open()
        buttons=[widget for widget in descendants(win) if isinstance(widget,ttk.Button) and widget.cget('text')=='Σύγκριση στοιχείων']
        buttons[1].invoke();self.owner.reconciliation.show_document_comparison.assert_called_once_with(12)
        reasons=[widget for widget in descendants(win) if isinstance(widget,tk.Text)]
        reason=reasons[0];reason.tag_add('sel','1.0','end-1c');perform(reason,'copy');self.root.update()
        self.assertEqual(self.root.clipboard_get(),'Excel totals differ')
        self.assertEqual(str(reason.cget('state')),'disabled')
        reason.insert('1.0','changed');self.assertEqual(reason.get('1.0','end-1c'),'Excel totals differ')
        self.service.authorize.assert_not_called()

    def test_stale_authorization_stays_open_without_refresh_or_continuation(self):
        win=self.open();self.service.authorize.side_effect=ValueError('Evidence changed')
        win.authorize_review();self.error.assert_called_once()
        self.assertTrue(win.winfo_exists());self.owner.refresh.assert_not_called();self.after.assert_not_called()

    def test_company_change_prevents_authorization(self):
        win=self.open();self.owner.company=8;win.authorize_review()
        self.error.assert_called_once();self.service.authorize.assert_not_called();self.after.assert_not_called()

    def test_known_registered_documents_are_not_shown(self):
        win=self.open(self.requirements+[dict(document=13,status='registered',reason='Already present',signature='no'),
                                          dict(document=14,status='review',reason='Already permitted',signature='yes',posting_permitted=True)])
        self.assertEqual(set(win.review_vars),{11,12})
        self.service.authorize.assert_not_called()


    def test_no_selected_documents_cannot_authorize(self):
        win=self.open()
        for selected in win.review_vars.values():selected.set(False)
        with patch('app.ui.posting_review.messagebox.showinfo') as info:win.authorize_review()
        info.assert_called_once();self.service.authorize.assert_not_called()
        self.assertTrue(win.winfo_exists());self.after.assert_not_called()


if __name__=='__main__':unittest.main()
