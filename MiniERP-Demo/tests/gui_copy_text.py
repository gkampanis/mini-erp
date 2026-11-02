"""Opt-in GUI coverage: python -m unittest tests.gui_copy_text."""
import tkinter as tk
import unittest
from unittest.mock import patch

from app.ui.copy_text import copy_text
from app.ui.text_editing import perform


class CopyTextGUI(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk()
        self.addCleanup(self.root.destroy)
        self.value=copy_text(self.root,'ΠΙΣΤΩΤΗΣ ΑΦΜ 123456789 · 64.00.0000',width=48)
        self.value.pack();self.root.update()
        self.value.focus_force();self.root.update()

    def test_selection_ctrl_c_and_edit_attempts(self):
        value=self.value;original=value.get()
        value.selection_range(0,8)
        value.event_generate('<Control-c>');value.event_generate('<KeyRelease-c>');self.root.update()
        self.assertEqual(self.root.clipboard_get(),original[:8])
        self.root.clipboard_clear();self.root.clipboard_append('replacement')
        for event in ('<<Paste>>','<<Cut>>','<BackSpace>','<Delete>','<KeyPress-z>'):
            value.event_generate(event);self.root.update()
            self.assertEqual(value.get(),original)
        perform(value,'select');self.assertEqual(int(value.index('sel.last')),len(original))

    def test_right_click_menu_copies_and_disables_mutations(self):
        value=self.value;value.selection_range(0,8)
        # Avoid a blocking native popup; invoke the actual installed class binding.
        with patch.object(tk.Menu,'tk_popup'),patch.object(tk.Menu,'grab_release'):
            value.event_generate('<Button-3>',x=4,y=4);self.root.update()
        menu=next(child for child in self.root.winfo_children() if isinstance(child,tk.Menu))
        self.assertEqual(menu.entrycget(1,'state'),'disabled')
        self.assertEqual(menu.entrycget(2,'state'),'disabled')
        menu.invoke(0);self.root.update()
        self.assertEqual(self.root.clipboard_get(),value.get()[:8])
        menu.invoke(3);self.assertTrue(value.selection_present())


class DialogCopyGUI(unittest.TestCase):
    def test_quick_account_identity_and_current_account_are_readonly_copy_fields(self):
        from tests.gui_quick_account import QuickAccountGUI
        from app.ui.quick_account import open_account
        fixture=QuickAccountGUI();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        win=open_account(fixture.owner,fixture.doc)
        fields=[]
        def visit(widget):
            if widget.winfo_class()=='TEntry' and str(widget.cget('state'))=='readonly':fields.append(widget)
            for child in widget.winfo_children():visit(child)
        visit(win)
        card=fixture.erp.detail(fixture.company,fixture.doc)[0]
        self.assertEqual(len(fields),3)
        self.assertEqual(fields[0].get(),card['name'])
        self.assertEqual(fields[1].get(),'ΑΦΜ '+card['vat'])
        self.assertTrue(fields[2].get().startswith('Τρέχων λογαριασμός: '))


    def test_vat_dialog_summary_values_are_copyable_but_account_remains_editable(self):
        from tests.gui_quick_account import QuickAccountGUI
        from app.ui.vat_accounts import open_rules
        fixture=QuickAccountGUI();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        requirement=dict(counterparty_id=fixture.cp,name='COPY CREDITOR',document=fixture.doc,
                         analysis=dict(lines=[dict(vat_category=1,vat_exemption=None,net_minor=10000,tax_minor=2400)]))
        win=open_rules(fixture.owner,[requirement]);fixture.root_ui.update()
        fields=[]
        def visit(widget):
            if widget.winfo_class()=='TEntry':fields.append(widget)
            for child in widget.winfo_children():visit(child)
        visit(win)
        readonly=[field for field in fields if str(field.cget('state'))=='readonly']
        self.assertEqual([field.get() for field in readonly],['COPY CREDITOR','24%','100,00','24,00'])
        editable=[field for field in fields if str(field.cget('state'))=='normal']
        self.assertEqual(len(editable),1)
        editable[0].insert(0,'64.00.0000');self.assertEqual(editable[0].get(),'64.00.0000')


    def test_mixed_vat_dialog_omits_zero_informational_line_account(self):
        from tests.gui_quick_account import QuickAccountGUI
        from app.ui.vat_accounts import open_rules
        fixture=QuickAccountGUI();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        lines=[dict(vat_category=1,vat_exemption=None,net_minor=10000,tax_minor=2400),
               dict(vat_category=2,vat_exemption=None,net_minor=5000,tax_minor=650),
               dict(vat_category=7,vat_exemption=27,rec_type=6,net_minor=0,tax_minor=0)]
        requirement=dict(counterparty_id=fixture.cp,name='MIXED CREDITOR',document=fixture.doc,
                         analysis=dict(lines=lines))
        win=open_rules(fixture.owner,[requirement]);fixture.root_ui.update()
        self.assertEqual(set(win.vat_forms),{(fixture.cp,1,0),(fixture.cp,2,0)})
        for form in win.vat_forms.values():form['account'].set('64.00.0000')
        win.vat_save()
        self.assertFalse(win.winfo_exists())
        from app.application.vat_lines import VATLines
        rules=VATLines(fixture.erp).rules(fixture.company,fixture.cp)
        self.assertEqual({rule['vat_category'] for rule in rules},{1,2})
        fixture.owner.refresh.assert_called_once()


if __name__=='__main__':unittest.main()




