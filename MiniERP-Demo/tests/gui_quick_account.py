import tkinter as tk,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from tests import test_history_accounts as fixtures


class QuickAccountGUI(unittest.TestCase):
    def setUp(self):
        fixtures.HistoryAccountTests.setUp(self)
        self.root_ui=tk.Tk();self.addCleanup(self.root_ui.destroy)
        self.doc=self.erp.search(self.company,'10000001')[0]['id']
        with self.erp.db:self.erp.db.execute("UPDATE documents SET environment='production' WHERE id=?",(self.doc,))
        self.owner=SimpleNamespace(root=self.root_ui,erp=self.erp,company=self.company,refresh=Mock(),busy=False,rpa_panel=SimpleNamespace(running=False),status=tk.StringVar(master=self.root_ui),state_filter=SimpleNamespace(get=lambda:'Μη καταχωρισμένα'))
        self.owner._documents={self.doc:self.erp.detail(self.company,self.doc)[0]}
    def test_context_any_column_targets_clicked_document_without_selection_change(self):
        from app.ui.quick_account import extend_menu
        tree=Mock();tree.identify_row.return_value=str(self.doc);tree.identify_region.return_value='cell';self.owner.tree=tree
        menu=Mock()
        with patch('app.ui.quick_account.open_account') as open_dialog:
            extend_menu(self.owner,SimpleNamespace(x=4,y=5),tree,menu)
            menu.add_command.assert_called_once();menu.add_command.call_args.kwargs['command']()
            open_dialog.assert_called_once_with(self.owner,self.doc)
            tree.selection_set.assert_not_called()
    def test_save_updates_card_and_pending_and_rejects_company_change(self):
        from app.ui.quick_account import open_account
        win=open_account(self.owner,self.doc);win.account_var.set('64.09.0000');win.save_account()
        self.assertEqual(self.erp.preparation(self.company,self.doc)['account_code'],'64.09.0000')
        self.owner.refresh.assert_called_once()
        win=open_account(self.owner,self.doc);self.owner.company=self.erp.company('000000009','OTHER')
        with patch('app.ui.quick_account.messagebox.showerror') as error:win.save_account()
        error.assert_called_once()
