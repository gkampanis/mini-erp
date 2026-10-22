"""Focused desktop regression checks; run explicitly with a graphical display.

DISPLAY=:99 /usr/bin/python3 -m tests.gui_regressions
Only synthetic fixtures are used. Dialog responses are automated inside tests.
"""
from pathlib import Path
import gc
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app.application.service import ERP
from app.ui.desktop import Desktop
from tests.fixtures import demos, workbook, HEADERS, ROW
from tests.gui_smoke import wait, widgets


class DesktopRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One Tcl interpreter avoids collecting old Tk interpreters inside later workers.
        cls.display_root = tk.Tk()
        cls.display_root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.display_root.destroy()
        gc.collect()

    def setUp(self):
        # Test cases intentionally create/destroy desktop forms in one process. Collect
        # previous UI closure cycles on the Tk owner thread before any new worker runs.
        gc.collect()
        self.threads_before = set(threading.enumerate())
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        demos(self.folder/'inputs')
        service = ERP(self.folder/'data')
        service.company('000000000', 'ΣΥΝΘΕΤΙΚΗ ΕΤΑΙΡΕΙΑ — REGRESSION')
        service.close()
        self.root = tk.Toplevel(self.display_root)
        self.app = Desktop(self.root, self.folder/'data')
        self.errors = []
        self.releases = []
        self.display_root.report_callback_exception = lambda *args: self.errors.append(str(args))
        self.root.update()

    def tearDown(self):
        for release in self.releases:
            release.set()
        try:
            with patch('app.ui.desktop.messagebox.showerror'):
                wait(self.root, lambda: not self.app.busy)
            self.assertEqual(self.errors, [], 'Unexpected Tk callback errors')
        finally:
            # A worker can enqueue its result just before its thread returns. Join
            # workers started by this case before releasing any Tcl-owned objects.
            for worker in set(threading.enumerate()) - self.threads_before:
                if worker is not threading.current_thread():
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive(), 'GUI worker survived test teardown')
            for timer in self.root.tk.call('after', 'info'):
                self.root.after_cancel(timer)
            self.app.close()
            self.temp.cleanup()
            # The interpreter's exception callback and app callbacks otherwise retain
            # whole cases (StringVars included) until automatic GC in a later worker.
            self.display_root.report_callback_exception = self.display_root.__class__.report_callback_exception.__get__(self.display_root)
            self.app = None
            self.root = None
            self.releases = []
            gc.collect()

    def button(self, parent, label):
        return next(w for w in widgets(parent)
                    if isinstance(w, ttk.Button) and str(w.cget('text')) == label)

    def table(self, parent, columns):
        return next(w for w in widgets(parent)
                    if isinstance(w, ttk.Treeview) and tuple(w['columns']) == columns)

    def count(self, table):
        return self.app.erp.db.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def open_preview(self, filename='separate.xlsx'):
        with patch('app.ui.desktop.filedialog.askopenfilename', return_value=str(self.folder/'inputs'/filename)):
            self.app.choose_excel()
        wait(self.root, lambda: not self.app.busy)
        self.assertTrue(self.app._has_preview())
        return self.app.preview_window

    def commit(self, preview):
        with patch('app.ui.desktop.messagebox.askyesno', return_value=True):
            self.button(preview, 'Επιβεβαιώνω εισαγωγή').invoke()
        wait(self.root, lambda: not self.app.busy)

    def import_fixture(self, filename):
        self.commit(self.open_preview(filename))
        self.close_children()

    def close_children(self):
        for child in list(self.root.winfo_children()):
            if isinstance(child, tk.Toplevel):
                child.destroy()
        self.root.update()

    def test_cancel_and_single_active_preview_do_not_write(self):
        preview = self.open_preview()
        self.assertTrue(self.app.import_button.instate(['disabled']))
        with patch('app.ui.desktop.filedialog.askopenfilename') as choose:
            self.app.choose_excel()
            choose.assert_not_called()
        self.assertIs(self.app.preview_window, preview)
        self.assertEqual(sum(isinstance(w, tk.Toplevel) for w in self.root.winfo_children()), 1)
        with patch('app.ui.desktop.messagebox.askyesno', return_value=False):
            self.button(preview, 'Επιβεβαιώνω εισαγωγή').invoke()
        self.assertTrue(preview.winfo_exists())
        self.assertEqual((self.count('documents'), self.count('import_jobs')), (0, 0))
        self.button(preview, 'Ακύρωση').invoke()
        self.root.update()
        self.assertFalse(self.app._has_preview())
        self.assertTrue(self.app.import_button.instate(['!disabled']))
        self.assertEqual((self.count('documents'), self.count('import_jobs')), (0, 0))

    def test_changed_mapping_requires_recheck_before_commit(self):
        preview = self.open_preview()
        name_column = next(w for w in widgets(preview)
                           if isinstance(w, ttk.Combobox) and w.get() == '2: Επωνυμία')
        name_column.set('—')
        with patch('app.ui.desktop.messagebox.showwarning') as warning, \
             patch('app.ui.desktop.messagebox.askyesno') as confirm:
            self.button(preview, 'Επιβεβαιώνω εισαγωγή').invoke()
            warning.assert_called_once()
            confirm.assert_not_called()
        self.assertTrue(preview.winfo_exists())
        self.assertEqual(self.count('import_jobs'), 0)
        self.button(preview, 'Επανέλεγχος αντιστοίχισης').invoke()
        wait(self.root, lambda: not self.app.busy)
        checked = self.app.preview_window
        self.assertIsNot(checked, preview)
        self.assertTrue(checked.winfo_exists())
        self.commit(checked)
        self.assertEqual((self.count('documents'), self.count('import_jobs')), (2, 1))
        self.assertEqual(self.app.erp.search(self.app.company, '000000001')[0]['name'], 'Χωρίς επωνυμία')

    def test_busy_prevents_discarding_preview_and_keeps_progress(self):
        preview = self.open_preview()
        release = threading.Event()
        self.releases.append(release)
        self.assertTrue(self.app.run_worker(lambda: release.wait(5), lambda _: None))
        self.assertFalse(self.app.run_worker(lambda: None, lambda _: None))
        message = self.app.status.get()
        self.app.refresh()
        self.assertEqual(self.app.status.get(), message)
        with patch('app.ui.desktop.messagebox.askyesno') as confirm:
            self.button(preview, 'Επιβεβαιώνω εισαγωγή').invoke()
            self.button(preview, 'Επανέλεγχος αντιστοίχισης').invoke()
            confirm.assert_not_called()
        self.assertIs(self.app.preview_window, preview)
        self.assertTrue(preview.winfo_exists())
        self.assertEqual(self.count('import_jobs'), 0)
        self.assertTrue(self.app.import_button.instate(['disabled']))
        release.set()
        wait(self.root, lambda: not self.app.busy)
        self.assertTrue(self.app.import_button.instate(['disabled']))  # preview still owns import
        self.button(preview, 'Ακύρωση').invoke()
        self.assertTrue(self.app.import_button.instate(['!disabled']))

    def test_worker_failure_reports_error_and_restores_controls(self):
        with patch('app.ui.desktop.preview', side_effect=ValueError('Συνθετικό σφάλμα ανάγνωσης')), \
             patch('app.ui.desktop.messagebox.showerror') as error, \
             patch('app.ui.desktop.filedialog.askopenfilename', return_value=str(self.folder/'inputs/separate.xlsx')):
            self.app.choose_excel()
            wait(self.root, lambda: not self.app.busy)
            error.assert_called_once()
            self.assertIn('Συνθετικό σφάλμα', error.call_args.args[1])
        self.assertFalse(self.app._has_preview())
        self.assertTrue(self.app.import_button.instate(['!disabled']))
        self.assertEqual((self.count('documents'), self.count('import_jobs')), (0, 0))

    def test_rejections_visible_in_preview_and_persisted_review(self):
        preview = self.open_preview()
        rejected = self.table(preview, ('row', 'reason'))
        children = rejected.get_children()
        self.assertEqual(len(children), 1)
        values = rejected.item(children[0], 'values')
        self.assertEqual(str(values[0]), '4')
        self.assertIn('ΑΦΜ', values[1])
        self.commit(preview)
        self.close_children()
        self.assertEqual(len(self.app.review_tree.get_children()), 1)
        job_id = self.app.review_tree.get_children()[0]
        self.app.review_tree.selection_set(job_id)
        self.app.open_review()
        report = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        issues = self.table(report, ('type', 'row', 'reason'))
        self.assertEqual(len(issues.get_children()), 1)
        issue = issues.item(issues.get_children()[0], 'values')
        self.assertEqual((issue[0], str(issue[1])), ('Εξαίρεση', '4'))
        self.assertIn('ΑΦΜ', issue[2])
        self.assertEqual(self.app.erp.import_reviews(self.app.company)[0]['rejected_count'], 1)
        self.close_children()
        bad = ['BAD', *ROW[1:]]
        workbook(self.folder/'inputs/invalid.xlsx', [HEADERS, bad])
        invalid = self.open_preview('invalid.xlsx')
        self.assertTrue(self.button(invalid, 'Επιβεβαιώνω εισαγωγή').instate(['disabled']))
        self.assertEqual(len(self.table(invalid, ('row', 'reason')).get_children()), 1)
        self.button(invalid, 'Ακύρωση').invoke()
        self.assertEqual(self.count('import_jobs'), 1)

    def test_sort_filter_detail_and_explicit_group_preparation(self):
        self.import_fixture('separate.xlsx')
        self.import_fixture('combined.xlsx')
        self.app.sort_documents('gross_minor')
        sorted_ids = [int(i) for i in self.app.tree.get_children()]
        self.assertEqual([self.app._documents[i]['gross_minor'] for i in sorted_ids], [12, 1240, 12400])
        self.app.query.set('000000003')
        self.app.refresh()
        document_id = int(self.app.tree.get_children()[0])
        self.app.tree.selection_set(str(document_id))
        with patch.object(self.app.erp, 'detail', wraps=self.app.erp.detail) as detail:
            self.app.open_detail()
            self.assertTrue(detail.call_args_list)
            self.assertTrue(all(call.args == (self.app.company, document_id) for call in detail.call_args_list))
        win = self.app._details[document_id]
        self.assertIn('Γ/3', win.title())
        self.app.open_detail()
        self.assertIs(self.app._details[document_id], win)  # no duplicate detail form
        group = next(w for w in widgets(win) if isinstance(w, ttk.Combobox))
        entries = [w for w in widgets(win) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)]
        account, note = entries
        group.set('2 · Αγορές')
        account.insert(0, '20.00.00')
        note.insert(0, 'Συνθετικός έλεγχος αγοράς')
        approve = self.button(win, 'Έγκριση τοπικής προετοιμασίας')
        with patch('app.ui.desktop.messagebox.showwarning') as warning, \
             patch('app.ui.desktop.messagebox.askyesno') as confirm:
            approve.invoke()
            warning.assert_called_once()
            confirm.assert_not_called()
        self.assertIsNone(self.app.erp.preparation(self.app.company, document_id))
        checkbox = next(w for w in widgets(win) if isinstance(w, ttk.Checkbutton))
        checkbox.invoke()
        with patch('app.ui.desktop.messagebox.askyesno', return_value=False):
            approve.invoke()
        self.assertIsNone(self.app.erp.preparation(self.app.company, document_id))
        with patch('app.ui.desktop.messagebox.askyesno', return_value=True):
            approve.invoke()
        saved = self.app.erp.preparation(self.app.company, document_id)
        self.assertEqual((saved['nature_group'], saved['account_code']), ('2', '20.00.00'))
        self.assertEqual(saved['note'], 'Συνθετικός έλεγχος αγοράς')
        self.app.query.set('')
        self.app.state_filter.set('Με τοπική έγκριση')
        self.app.group_filter.set('Ομάδα 2 · Αγορές')
        self.app.refresh()
        self.assertEqual(self.app.tree.get_children(), (str(document_id),))
        self.app.tree.selection_set(str(document_id))
        self.app.open_detail()
        win = self.app._details[document_id]
        group = next(w for w in widgets(win) if isinstance(w, ttk.Combobox))
        account = next(w for w in widgets(win) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox))
        self.assertEqual((group.get(), account.get()), ('2 · Αγορές', '20.00.00'))
        # Reclassify the same synthetic transaction only through another explicit approval.
        group.set('6 · Έξοδα')
        account.delete(0, 'end')
        account.insert(0, '64.00.00')
        next(w for w in widgets(win) if isinstance(w, ttk.Checkbutton)).invoke()
        with patch('app.ui.desktop.messagebox.askyesno', return_value=True):
            self.button(win, 'Έγκριση τοπικής προετοιμασίας').invoke()
        self.app.group_filter.set('Ομάδα 2 · Αγορές')
        self.app.refresh()
        self.assertEqual(self.app.tree.get_children(), ())
        self.app.group_filter.set('Ομάδα 6 · Έξοδα')
        self.app.refresh()
        self.assertEqual(self.app.tree.get_children(), (str(document_id),))
        self.app.state_filter.set('Χωρίς προετοιμασία')
        self.app.refresh()
        self.assertEqual(self.app.tree.get_children(), ())
        self.app.group_filter.set('Όλες οι ομάδες')
        self.app.refresh()
        self.assertEqual(len(self.app.tree.get_children()), 2)
        _, events = self.app.erp.detail(self.app.company, document_id)
        self.assertEqual(sum(e['action'] == 'document_prepared' for e in events), 2)
        self.assertTrue(all(row['status'] == 'needs_review' for row in self.app.erp.search(self.app.company)))
        self.assertEqual(self.count('documents'), 3)

    def test_closing_with_preview_has_no_callbacks_or_writes(self):
        self.open_preview()
        self.assertEqual(self.count('import_jobs'),0)
        self.app.close()
        self.display_root.update()
        self.assertEqual(self.errors,[])
        check = ERP(self.folder/'data')
        try:
            self.assertEqual(check.db.execute('SELECT count(*) FROM import_jobs').fetchone()[0],0)
        finally:
            check.close()

    def test_small_window_keeps_primary_actions_visible(self):
        self.root.geometry('960x650')
        self.root.update()
        action = self.button(self.root,'Στοιχεία & προετοιμασία')
        self.assertGreater(action.winfo_height(),1)
        self.assertLessEqual(action.winfo_rooty()+action.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        preview = self.open_preview()
        preview.geometry('900x620')
        self.root.update()
        confirm = self.button(preview,'Επιβεβαιώνω εισαγωγή')
        self.assertGreater(confirm.winfo_height(),1)
        self.assertLessEqual(confirm.winfo_rooty()+confirm.winfo_height(),preview.winfo_rooty()+preview.winfo_height())

    def test_preparation_database_error_keeps_form_and_original_record(self):
        import sqlite3
        self.import_fixture('combined.xlsx')
        document_id = self.app.tree.get_children()[0]
        self.app.tree.selection_set(document_id)
        self.app.open_detail()
        win = self.app._details[int(document_id)]
        group = next(w for w in widgets(win) if isinstance(w,ttk.Combobox))
        group.set('6 · Έξοδα')
        account = next(w for w in widgets(win) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
        account.insert(0,'64.03')
        next(w for w in widgets(win) if isinstance(w,ttk.Checkbutton)).invoke()
        with patch.object(self.app.erp,'prepare_document',side_effect=sqlite3.OperationalError('database is locked')), \
             patch('app.ui.desktop.messagebox.askyesno',return_value=True), \
             patch('app.ui.desktop.messagebox.showerror') as error:
            self.button(win,'Έγκριση τοπικής προετοιμασίας').invoke()
            error.assert_called_once()
        self.assertTrue(win.winfo_exists())
        self.assertIsNone(self.app.erp.preparation(self.app.company,int(document_id)))
        self.assertEqual(self.errors,[])

    def test_double_click_details_show_inline_pdf_and_keep_preparation(self):
        from tests.test_workspace import synthetic_pdf
        self.import_fixture('combined.xlsx')
        document=int(self.app.tree.get_children()[0])
        self.app.erp.attach_pdf(self.app.company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
        self.app.tree.selection_set(str(document));self.app.open_detail()
        win=self.app._details[document];pane=win.pdf_pane
        wait(self.root,lambda:pane.image is not None and not self.app.busy)
        self.assertTrue(pane.canvas.find_all())
        self.assertIn('1 από 1',pane.state.get())
        self.assertEqual(len(pane.files.get_children()),1)
        self.assertIsNone(self.app.erp.preparation(self.app.company,document))
        self.assertTrue(self.button(win,'Έγκριση τοπικής προετοιμασίας').winfo_exists())

    def test_aade_settings_mask_and_secure_save_with_synthetic_vault(self):
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        win=self.app.open_aade()
        entries=[w for w in widgets(win) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox)]
        username,key=win.api_username_entry,win.api_key_entry
        self.assertTrue(key.cget('show'))
        username.insert(0,'synthetic-ui-user');key.insert(0,'synthetic-ui-key')
        self.button(win,'Αποθήκευση κωδικών').invoke()
        self.assertEqual(key.get(),'')
        self.assertEqual(self.app.erp.mydata_credentials(self.app.company)['key'],'synthetic-ui-key')
        self.assertNotIn('synthetic-ui-key','\n'.join(self.app.erp.db.iterdump()))

    def test_rpa_tab_queues_selected_approved_document_and_simulates(self):
        self.import_fixture('combined.xlsx')
        document=int(self.app.tree.get_children()[0])
        self.app.erp.prepare_document(self.app.company,document,'6','64.03',confirmed=True)
        self.app.refresh();self.app.tree.selection_set(str(document))
        panel=self.app.rpa_panel
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):panel.queue_selected()
        self.assertIsNotNone(panel.job)
        panel.start()
        wait(self.root,lambda:not self.app.busy)
        meta,items=panel.rpa.items(self.app.company,panel.job)
        self.assertEqual(meta['status'],'completed');self.assertEqual(items[0]['status'],'simulated')
        self.assertIn('Προσομοίωση',panel.state.get())

    def test_one_excel_register_card_and_bulk_accounts_share_document_ids(self):
        self.import_fixture('separate.xlsx')
        ids=set(self.app.tree.get_children())
        self.assertEqual(len(ids),2)
        self.assertNotIn('RPA → EBS',[self.app.notebook.tab(t,'text') for t in self.app.notebook.tabs()])
        register=self.app.open_counterparties();self.assertEqual(len(register.card_tree.get_children()),2)
        register.destroy()
        from app.ui.counterparties import open_detail
        cp=self.app.erp.search(self.app.company,'000000001')[0]['counterparty_id']
        card=open_detail(self.app,cp)
        card.account_fields[0].set('20.01');card.account_fields[1].set('64.03');card.account_fields[2].set('6 · Έξοδα')
        with patch('app.ui.counterparties.messagebox.askyesno',return_value=True):self.button(card,'Αποθήκευση καρτέλας').invoke()
        self.app.query.set('000000001');self.app.refresh()
        document=int(self.app.tree.get_children()[0])
        self.assertEqual(self.app._documents[document]['account_code'],'64.03')
        self.assertEqual(self.app._documents[document]['preparation_state'],'Πρόταση καρτέλας')
        self.assertIsNone(self.app.erp.preparation(self.app.company,document))
        accounts=self.app.rpa_panel.accounts()
        fields=[w for w in widgets(accounts) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox)]
        self.assertIn('64.03',[w.get() for w in fields])
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):self.button(accounts,'Έγκριση λογαριασμών').invoke()
        self.assertEqual(self.app.erp.preparation(self.app.company,document)['account_code'],'64.03')
        self.assertEqual(self.count('documents'),2)
        self.app.reset_filters();self.assertEqual(set(self.app.tree.get_children()),ids)

    def test_aade_read_updates_same_excel_row_and_shows_match(self):
        from tests.test_workspace import MemoryVault
        from tests.test_workflow import response
        from app.infrastructure.aade.client import parsed_page
        self.import_fixture('separate.xlsx');document=self.app.erp.search(self.app.company,'000000001')[0]['id']
        with self.app.erp.db:self.app.erp.db.execute("UPDATE companies SET vat='000000008' WHERE id=?",(self.app.company,))
        self.app.erp.credential_store=MemoryVault()
        self.app.erp.save_mydata_credentials(self.app.company,'production','synthetic-user','synthetic-key',confirmed=True)
        win=self.app.open_aade();win.period_vars[0].set('2026-10-01');win.period_vars[1].set('2026-10-31');win.kind_var.set('Ληφθέντα')
        raw=response(receiver='000000008')
        with patch('app.infrastructure.aade.client.Client.fetch',return_value=[(raw,parsed_page(raw))]) as fetch:
            win.fetch_aade();wait(self.root,lambda:not self.app.busy);fetch.assert_called_once()
        self.assertEqual(len(win.records_tree.get_children()),1)
        self.assertIn('Συμφωνεί με Excel',win.records_tree.item(win.records_tree.get_children()[0],'values'))
        self.assertEqual(self.app._documents[document]['aade_state'],'Συμφωνεί')
        self.assertEqual(self.count('documents'),2)

    def test_mixed_list_simulation_excludes_purchases_without_second_import(self):
        self.import_fixture('separate.xlsx')
        ids=[r['id'] for r in self.app.rpa_panel.workspace.rows(self.app.company)]
        self.app.rpa_panel.workspace.approve_many(self.app.company,[dict(document=ids[0],group='2',account='20.01'),dict(document=ids[1],group='6',account='64.03')],confirmed=True)
        self.app.refresh()
        self.assertEqual(self.app._documents[ids[0]]['ebs_state'],'Αγορές · εκτός EBS')
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True) as confirm:
            self.app.rpa_panel.simulate()
            self.assertIn('1 αγορές ομάδας 2 εξαιρέθηκαν',confirm.call_args.args[1])
        wait(self.root,lambda:not self.app.busy)
        items=self.app.rpa_panel.rpa.items(self.app.company,self.app.rpa_panel.job)[1]
        self.assertEqual([i['document_id'] for i in items],[ids[1]])
        self.assertEqual(self.count('documents'),2)
        self.assertEqual(self.app.erp.preparation(self.app.company,ids[0])['nature_group'],'2')


if __name__ == '__main__':
    unittest.main(verbosity=2)
