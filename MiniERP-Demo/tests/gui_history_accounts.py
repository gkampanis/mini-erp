import tkinter as tk
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
from tests import test_history_accounts as fixtures


class HistoryImportGUI(unittest.TestCase):
    def setUp(self):
        fixtures.HistoryAccountTests.setUp(self)
        self.root_ui=tk.Tk();self.addCleanup(self.root_ui.destroy)
        self.owner=SimpleNamespace(root=self.root_ui,erp=self.erp,company=self.company,refresh=Mock())
    packet=fixtures.HistoryAccountTests.packet
    def test_preview_and_apply_selected_updates_card_and_pending(self):
        from app.ui.history_accounts import HistoryImport
        packet=self.packet();ui=HistoryImport(self.owner);ui.load(self.root/'accounts.xlsx');self.root_ui.update()
        self.assertEqual(len(ui.tree.get_children()),1)
        ui.select_ready();self.assertEqual(len(ui.tree.selection()),1)
        with patch('app.ui.history_accounts.messagebox.askyesno',return_value=True):ui.apply_selected()
        doc=self.erp.search(self.company,'10000001')[0]['id']
        self.assertEqual(self.erp.preparation(self.company,doc)['account_code'],'64.03.0000')
        self.assertIn('1',ui.status.get())
        ui.select_ready();self.assertFalse(ui.tree.selection())
    def test_company_change_cannot_apply_old_preview(self):
        from app.ui.history_accounts import HistoryImport
        packet=self.packet();ui=HistoryImport(self.owner);ui.load(self.root/'accounts.xlsx');ui.select_ready()
        self.owner.company=self.erp.company('000000009','OTHER')
        with patch('app.ui.history_accounts.messagebox.showerror') as error:ui.apply_selected()
        error.assert_called_once()
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM counterparty_accounts').fetchone()[0],0)
