"""Actual Tk coverage of the shared P9 Excel column interaction."""
import gc
import importlib.util
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from tests import gui_regressions as regression
from tests.gui_smoke import widgets,wait


class SharedColumnWidgetTests(unittest.TestCase):
    def test_destroy_releases_owned_tcl_variables_even_if_frame_is_retained(self):
        import weakref
        variables=[weakref.ref(var) for var in self.widget.variables.values()]
        self.widget.destroy()
        self.assertTrue(all(var() is None for var in variables))

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.ui.excel_mapping'),
                             'The shared column control is not implemented')
        from app.ui.excel_mapping import ColumnMapping
        self.root=tk.Tk()
        self.widget=ColumnMapping(self.root,{'vat':'ΑΦΜ','invoice':'Παραστατικό'},unique=True)
        self.widget.pack()

    def tearDown(self):
        self.root.destroy();self.widget=None;self.root=None
        gc.collect()

    def test_shared_renderer_rejects_duplicate_ebs_columns_and_retains_raw_aliases(self):
        self.widget.set_headers({0:'ΑΦΜ',1:'Εναλ. παρ/κό',2:'Παρ/κό'},
                                {'vat':0,'invoice':1},excluded_labels=('Παρ/κό',))
        self.assertEqual(self.widget.mapping(),{'vat':0,'invoice':1})
        self.assertNotIn('3: Παρ/κό',self.widget.lookup)
        self.widget.variables['invoice'].set('1: ΑΦΜ')
        with self.assertRaises(ValueError):self.widget.mapping()
        from app.ui.excel_mapping import ColumnMapping
        raw=ColumnMapping(self.root,{'invoice':'Παραστατικό','number':'Αριθμός'})
        raw.set_headers({0:'Invoice Number'},{'invoice':0,'number':0})
        self.assertEqual(raw.mapping(),{'invoice':0,'number':0})


class ReconciliationExcelInteractionTests(unittest.TestCase):
    # Reuse the mature cleanup without exposing its 90+ test methods to discovery.
    setUpClass=classmethod(regression.DesktopRegressions.setUpClass.__func__)
    tearDownClass=classmethod(regression.DesktopRegressions.tearDownClass.__func__)
    setUp=regression.DesktopRegressions.setUp
    tearDown=regression.DesktopRegressions.tearDown
    button=regression.DesktopRegressions.button
    count=regression.DesktopRegressions.count

    def test_known_ebs_mapping_uses_shared_control_and_reuses_existing_window(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        from tests.fixtures import workbook
        path=self.folder/'ebs.xlsx'
        workbook(path,[['Note'],['Ημ/νία','Παρ/κό','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],
                       ['2026-10-21','INTERNAL','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        book=EBSReconciliation(self.app.erp).layout(path)
        win=tk.Toplevel(self.root);ttk.Label(win,text='Source role chooser').pack()
        reused=self.app.reconciliation.import_dialog(book,window=win)
        self.root.update()
        self.assertIs(reused,win)
        self.assertEqual(sum(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()),1)
        from app.ui.excel_mapping import ColumnMapping
        self.assertEqual(sum(isinstance(w,ColumnMapping) for w in widgets(win)),1)
        self.assertEqual(win.mapping_vars['invoice'].get(),'3: Εναλ. παρ/κό')
        self.assertNotEqual(win.pages.select(),str(win.mapping_page))
        self.assertFalse(any(isinstance(w,ttk.Button) and w.cget('text')=='Εμφάνιση στηλών' for w in widgets(win)))
        self.assertFalse(any(isinstance(w,ttk.Button) and 'Εισαγωγή Excel' in str(w.cget('text')) for w in widgets(self.app.reconciliation_tab)))
        self.assertIs(self.app.preview_window,win)

    def test_destroyed_reconciliation_window_removes_owned_variable_traces(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        from tests.fixtures import workbook
        path=self.folder/'ebs.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο'],
                       ['2026-10-21','ΔΟΚ/1','000000001','0.10','0.02','0.12']])
        win=self.app.reconciliation.import_dialog(EBSReconciliation(self.app.erp).layout(path))
        names={str(widget.cget(option)) for widget in widgets(win)
               for option in ('textvariable','variable') if option in widget.keys() and widget.cget(option)}
        def traces(name):
            return [win.tk.splitlist(entry) for entry in win.tk.splitlist(win.tk.call('trace','info','variable',name))]
        active={name:traces(name) for name in names if traces(name)}
        self.assertTrue(active)
        commands=[command for entries in active.values() for _,command in entries]
        self.assertTrue(all(win.tk.call('info','commands',command) for command in commands))
        # A child's Destroy event must leave the open dialog's callbacks working.
        child=ttk.Frame(win);child.destroy()
        self.assertEqual({name:traces(name) for name in active},active)
        win.packet={'synthetic':True};win.company_ok_var.set(True)
        self.assertIsNone(win.packet)
        win.destroy()
        self.assertIsNone(self.app.preview_window)
        for name in active:
            with self.subTest(variable=name):self.assertEqual(traces(name),[])
        for command in commands:
            with self.subTest(command=command):self.assertFalse(win.tk.call('info','commands',command))

    def test_missing_column_stays_in_one_window_and_partial_import_does_not_authorize_absence(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.infrastructure.importers.excel import preview
        from tests.fixtures import workbook
        self.app.erp.commit_import(self.app.company,preview(self.folder/'inputs/separate.xlsx'),confirmed=True)
        self.app.refresh()
        path=self.folder/'ebs.xlsx'
        workbook(path,[['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','Unknown tax','Σύνολο'],
                       ['2026-10-21','ΔΟΚ/999','000000001','0.10','0.02','0.12']])
        win=self.app.reconciliation.import_dialog(EBSReconciliation(self.app.erp).layout(path))
        self.assertEqual(win.pages.select(),str(win.mapping_page))
        win.mapping_vars['tax'].set('5: Unknown tax')
        self.assertIs(self.app.preview_window,win)
        self.assertEqual(sum(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()),1)
        self.assertEqual(win.apply_button.cget('text'),'Εφαρμογή')
        labels=[str(w.cget('text')) for w in widgets(win) if isinstance(w,ttk.Checkbutton)]
        self.assertFalse(any('Πλήρης κατάλογος' in label or 'Επιβεβαιώνω' in label or 'Αποθήκευση αντιστοίχισης' in label for label in labels))
        win.apply_button.invoke();wait(self.root,lambda:not self.app.busy)
        self.assertFalse(win.winfo_exists())
        service=EBSReconciliation(self.app.erp);evidence=service.results(self.app.company)
        self.assertEqual(self.count('documents'),2)
        self.assertEqual({row['status'] for row in evidence.values()},{'not_found'})
        with self.assertRaises(ValueError):service.assert_rpa(self.app.company,list(evidence),required=True)

    def test_attempt_confirmation_in_reconciliation_uses_existing_explicit_action(self):
        tab=self.app.reconciliation
        with patch.object(tab,'chosen',return_value=42),patch.object(tab.service,'results',return_value={42:dict(match_kind='attempt',status='review')}),patch.object(self.app.rpa_panel,'confirm_document') as confirm,patch('app.ui.ebs_reconciliation.messagebox.askyesno',return_value=False) as popup:
            tab.confirm();confirm.assert_called_once_with(42);popup.assert_not_called()


if __name__=='__main__':unittest.main()
