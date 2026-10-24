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
        self.initial_state=self.app.state_filter.get()
        # Existing scenarios exercise the complete document list. The new
        # default pending workspace is covered separately below.
        self.app.state_filter.set('Όλα τα παραστατικά');self.app.refresh()
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
            owners=(self.display_root,self.root,*widgets(self.root)) if self.root.winfo_exists() else (self.display_root,)
            for timer in self.root.tk.call('after', 'info'):
                script=self.root.tk.call('after','info',timer)[0]
                # Native ttk scrolling timers can contain Tcl argument tuples.
                # Delete Python callbacks through their registering widget only.
                owner=next((w for w in owners if script in (w._tclCommands or [])),None)
                if owner is not None:owner.after_cancel(timer)
                else:self.root.tk.call('after','cancel',timer)
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
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.app.erp,self.app.company)
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
        for key,button in self.app.rpa_panel.buttons.items():
            if key in ('pause','resume','stop','accounts','simulation'):
                self.assertFalse(button.winfo_ismapped());continue
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_width(),button.winfo_reqwidth())
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

    def test_mass_download_links_and_renders_without_individual_controls(self):
        from tests.test_workspace import synthetic_pdf,MemoryVault
        self.import_fixture('combined.xlsx')
        self.app.erp.credential_store=MemoryVault()
        self.app.erp.save_mydata_credentials(self.app.company,'test','synthetic','synthetic',confirmed=True)
        document=int(self.app.tree.get_children()[0])
        self.app.tree.selection_set(str(document));self.app.open_detail()
        pane=self.app._details[document].pdf_pane
        def retrieve(sync,company,*args,**kwargs):
            sync.erp.attach_pdf(company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
            return {'import':{'inserted':0,'duplicates':0,'rejected':[]},'pdf':{'saved':1,'pending':0}}
        win=self.app.open_acquisition()
        with patch('app.application.sync.Sync.run',retrieve),patch('tkinter.simpledialog.askstring') as manual:
            win.sync_expenses();wait(self.root,lambda:pane.image is not None and not self.app.busy)
            manual.assert_not_called()
        captions=[w.cget('text') for w in widgets(pane.parent) if isinstance(w,ttk.Button)]
        self.assertIn('Άνοιγμα Παραστατικού',captions)
        self.assertNotIn('Προσθήκη PDF',captions);self.assertNotIn('ΑΑΔΕ → Λήψη PDF',captions)
        self.assertFalse(any(isinstance(w,ttk.Combobox) for w in widgets(pane.parent)))
        self.assertEqual(len(pane.files.get_children()),1);self.assertTrue(pane.canvas.find_all())

    def test_settings_group_components_and_export_private_crashlog(self):
        from app.infrastructure.crashlog import record
        try:raise RuntimeError('private supplier api-key=DO-NOT-EXPORT')
        except RuntimeError as error:record(self.app.directory,error,'worker')
        win=self.app.open_settings();self.root.update()
        tabs=win.settings_tabs
        self.assertEqual([tabs.tab(t,'text') for t in tabs.tabs()],['Συνδέσεις','PDF και λήψεις','Υποστήριξη'])
        tabs.select(1);self.root.update()
        self.assertTrue(self.button(win,'Εγκατάσταση Camoufox (προαιρετικό)').winfo_viewable())
        target=self.folder/'support.txt';tabs.select(2);self.root.update()
        with patch('app.ui.settings.filedialog.asksaveasfilename',return_value=str(target)),patch('app.ui.settings.messagebox.showinfo'):
            self.button(win,'Αποθήκευση crashlog για αποστολή').invoke()
        content=target.read_text();self.assertIn('RuntimeError',content);self.assertNotIn('DO-NOT-EXPORT',content)
        self.assertEqual(self.app.erp.db.execute('SELECT count(*) FROM documents').fetchone()[0],0)

    def test_camoufox_requires_explicit_selection_before_any_recovery(self):
        win=self.app.open_aade()
        with patch('app.ui.aade_dialog.messagebox.showinfo') as info,patch('app.application.camoufox_pdf.run') as recover:
            self.button(win,'Ανάκτηση εκκρεμών με Camoufox (προαιρετικό)').invoke()
            info.assert_called_once();recover.assert_not_called()

    def test_text_fields_support_shortcuts_context_menu_and_greek_layout(self):
        from types import SimpleNamespace
        from app.ui.text_editing import shortcut
        win=tk.Toplevel(self.root)
        entries=[ttk.Entry(win),tk.Entry(win),ttk.Entry(win,show='●'),tk.Text(win,height=2),ttk.Combobox(win),tk.Spinbox(win),ttk.Spinbox(win)]
        for field in entries:
            if not isinstance(field,tk.Text):field.delete(0,'end')
            field.pack()
        win.update();sample='Συνθετικό κείμενο'
        for field in entries:
            field.focus_force();self.root.update()
            field.clipboard_clear();field.clipboard_append(sample)
            field.event_generate('<Control-v>');self.root.update()
            self.assertEqual(field.get('1.0','end-1c') if isinstance(field,tk.Text) else field.get(),sample)
            field.event_generate('<Control-a>');field.event_generate('<Control-x>');self.root.update()
            self.assertEqual(field.get('1.0','end-1c') if isinstance(field,tk.Text) else field.get(),'')
            # Native password fields may copy masking glyphs; paste must accept external text.
            field.clipboard_clear();field.clipboard_append(sample)
            shortcut(SimpleNamespace(widget=field,keysym='Greek_omega'));self.root.update()
            self.assertEqual(field.get('1.0','end-1c') if isinstance(field,tk.Text) else field.get(),sample)
        field=entries[0];field.delete(0,'end');field.focus_force();self.root.update()
        field.event_generate('<Button-3>',x=4,y=4);self.root.update()
        menu=next(w for w in self.display_root.winfo_children() if isinstance(w,tk.Menu))
        self.assertEqual(menu.entrycget(1,'label'),'Επικόλληση')
        menu.invoke(1);menu.unpost();self.root.update();self.assertEqual(field.get(),sample)
        readonly=ttk.Entry(win);readonly.insert(0,'Σταθερό');readonly.configure(state='readonly');readonly.pack()
        readonly.selection_range(0,'end');shortcut(SimpleNamespace(widget=readonly,keysym='c'))
        self.assertEqual(readonly.clipboard_get(),'Σταθερό')
        shortcut(SimpleNamespace(widget=readonly,keysym='v'));self.assertEqual(readonly.get(),'Σταθερό')
        source=tk.Text(win,height=2);source.insert('1.0','Αμετάβλητη προέλευση');source.configure(state='disabled');source.pack()
        shortcut(SimpleNamespace(widget=source,keysym='a'));shortcut(SimpleNamespace(widget=source,keysym='c'))
        self.assertEqual(source.clipboard_get(),'Αμετάβλητη προέλευση')
        shortcut(SimpleNamespace(widget=source,keysym='v'));self.assertEqual(source.get('1.0','end-1c'),'Αμετάβλητη προέλευση')

    def test_document_and_card_only_offer_automatic_lookup_and_shared_settings(self):
        self.import_fixture('combined.xlsx')
        document=int(self.app.tree.get_children()[0]);self.app.tree.selection_set(str(document));self.app.open_detail()
        detail=self.app._details[document]
        captions=[w.cget('text') for w in widgets(detail) if isinstance(w,ttk.Button)]
        self.assertNotIn('Άντληση από σύνδεσμο',captions);self.assertNotIn('ΑΑΔΕ → Λήψη PDF',captions);self.assertIn('Άνοιγμα Παραστατικού',captions)
        from app.ui.counterparties import open_detail
        row,_=self.app.erp.detail(self.app.company,document);card=open_detail(self.app,row['counterparty_id'])
        captions=[w.cget('text') for w in widgets(card) if isinstance(w,ttk.Button)]
        self.assertNotIn('Κωδικοί Μητρώου',captions);self.assertIn('Άντληση στοιχείων από ΑΦΜ',captions)
        settings=self.app.open_settings()
        self.assertTrue(self.button(settings,'Μητρώο ΑΑΔΕ · ειδικοί κωδικοί').winfo_exists())

    def test_month_acquisition_uses_complete_calendar_month_without_date_entries(self):
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        self.assertTrue(self.app.acquire_button.winfo_exists())
        self.app.month_filter.set('Μάιος 2025');self.app.month_changed()
        win=self.app.open_acquisition();win.year_var.set('2024');win.month_var.set('Φεβρουάριος')
        self.assertEqual(win.selected_period(),('2024-02-01','2024-02-29'))
        labels=[w.cget('text') for w in widgets(win) if isinstance(w,ttk.Label)]
        self.assertNotIn('Από',labels);self.assertNotIn('Έως',labels)
        result={'import':{'inserted':0,'duplicates':0,'rejected':[]},'pdf':{'saved':0,'pending':0}}
        with patch('app.application.sync.Sync.run',return_value=result) as sync:
            win.sync_expenses();wait(self.root,lambda:not self.app.busy)
        self.assertEqual(sync.call_args.args[2:4],('2024-02-01','2024-02-29'))
        self.assertEqual(sync.call_args.kwargs['methods'],['RequestDocs','RequestTransmittedDocs'])
        self.assertEqual(self.app.month_filter.get(),'Φεβρουάριος 2024')

    def test_month_acquisition_opens_on_selected_main_month_with_both_directions_default(self):
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        self.app.month_filter.set('Μάιος 2025');self.app.month_changed()
        win=self.app.open_acquisition()
        self.assertEqual(win.selected_period(),('2025-05-01','2025-05-31'))
        self.assertEqual(win.kind_var.get(),'Ληφθέντα και εκδοθέντα')
        win.destroy();general=self.app.open_aade()
        self.assertEqual(general.kind_var.get(),'Ληφθέντα και εκδοθέντα')

    def test_supplier_tab_bulk_update_reaches_same_document_ids(self):
        self.import_fixture('separate.xlsx')
        titles=[self.app.notebook.tab(t,'text') for t in self.app.notebook.tabs()]
        self.assertEqual(titles[titles.index('Έλεγχοι εισαγωγής')+1],'Προμηθευτές')
        self.app.notebook.select(self.app.suppliers_tab);self.root.update()
        tab=self.app.suppliers;tab.tree.selection_set(tab.tree.get_children());original=set(self.app.tree.get_children())
        win=tab.bulk();win.account_var.set('64.09')
        with patch('app.ui.suppliers.messagebox.askyesno') as confirm:
            self.button(win,'OK').invoke();confirm.assert_not_called()
        self.assertEqual(set(self.app.tree.get_children()),original)
        self.assertTrue(all(self.app._documents[int(d)]['account_code']=='64.09' for d in original))
        self.assertTrue(all(self.app.erp.preparation(self.app.company,int(d)) for d in original))

    def test_pause_cancels_scheduled_item_and_resume_does_not_repeat_simulation(self):
        self.import_fixture('separate.xlsx');panel=self.app.rpa_panel
        ids=[int(d) for d in self.app.tree.get_children()]
        panel.workspace.approve_many(self.app.company,[dict(document=d,group='6',account='64.03') for d in ids],confirmed=True)
        self.app.tree.selection_set([str(d) for d in ids]);panel.queue_selected()
        self.assertFalse(panel.buttons['resume'].instate(['disabled']))
        panel.start();wait(self.root,lambda:not self.app.busy and panel.rpa.progress(self.app.company,panel.job)['simulated']==1)
        panel.pause();self.assertEqual(panel.rpa.items(self.app.company,panel.job)[0]['status'],'paused')
        self.assertTrue(panel.buttons['pause'].instate(['disabled']));self.assertFalse(panel.buttons['resume'].instate(['disabled']))
        elapsed=[];self.root.after(450,lambda:elapsed.append(True));wait(self.root,lambda:bool(elapsed))
        self.assertEqual(panel.rpa.progress(self.app.company,panel.job)['simulated'],1)
        panel.start();wait(self.root,lambda:not self.app.busy and not panel.running)
        self.assertEqual(panel.rpa.progress(self.app.company,panel.job)['simulated'],2)
        self.assertTrue(panel.buttons['resume'].instate(['disabled']));self.assertIn('Καμία ενέργεια στο EBS',panel.state.get())

    def test_open_document_uses_verified_source_url_or_archived_pdf(self):
        from app.application.mydata import MyData
        from app.infrastructure.aade.client import parsed_page
        from tests.test_workflow import response
        from tests.test_workspace import synthetic_pdf
        self.import_fixture('separate.xlsx');document=self.app.erp.search(self.app.company,'000000001')[0]['id']
        raw=response();MyData(self.app.erp).persist(self.app.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
        self.app.tree.selection_set(str(document));self.app.open_detail();pane=self.app._details[document].pdf_pane
        with patch('webbrowser.open',return_value=True) as browser:
            pane.open_document();browser.assert_called_once_with('https://example.com/synthetic.pdf')
        self.app.erp.attach_pdf(self.app.company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
        with patch('sys.platform','linux'),patch('webbrowser.open',return_value=True) as browser:
            pane.open_document();self.assertTrue(browser.call_args.args[0].startswith('file:'))

    def test_history_visual_confirmation_updates_only_operator_verified_counter(self):
        self.import_fixture('combined.xlsx');panel=self.app.rpa_panel;document=int(self.app.tree.get_children()[0])
        self.app.erp.prepare_document(self.app.company,document,'6','64.03',confirmed=True)
        panel.job=panel.rpa.create(self.app.company,[document],mode='fill_only',confirmed=True)
        item=panel.rpa.items(self.app.company,panel.job)[1][0]
        with self.app.erp.db:self.app.erp.db.execute("UPDATE rpa_items SET status='save_invoked' WHERE id=?",(item['id'],))
        win=panel.history();tree=next(w for w in widgets(win) if isinstance(w,ttk.Treeview));tree.selection_set(str(item['id']))
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True),patch('app.ui.rpa_panel.simpledialog.askstring',return_value='Οπτικός έλεγχος συνθετικής εγγραφής'):
            self.button(win,'Χειροκίνητος έλεγχος προσπάθειας').invoke()
        self.assertEqual(panel.rpa.progress(self.app.company,panel.job)['verified_in_ebs'],1)
        self.assertEqual(panel.rpa.progress(self.app.company,panel.job)['automatically_verified'],0)

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
        self.assertIn('Έλεγχος χωρίς καταχώριση',panel.state.get())

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
        self.assertEqual(self.app._documents[document]['preparation_state'],'Εγκεκριμένο')
        self.assertEqual(self.app.erp.preparation(self.app.company,document)['account_code'],'64.03')
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
        win=self.app.open_aade();win.year_var.set('2026');win.month_var.set('Οκτώβριος');win.kind_var.set('Ληφθέντα')
        raw=response(receiver='000000008')
        with patch('app.infrastructure.aade.client.Client.fetch',return_value=[(raw,parsed_page(raw))]) as fetch:
            win.fetch_aade();wait(self.root,lambda:not self.app.busy);fetch.assert_called_once()
        self.assertEqual(len(win.records_tree.get_children()),1)
        self.assertIn('Συμφωνεί με εγγραφή',win.records_tree.item(win.records_tree.get_children()[0],'values'))
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

    def test_main_month_filter_limits_editing_and_rpa_queue(self):
        from app.infrastructure.importers.excel import preview
        rows=[]
        for index,day in enumerate(('2026-09-30','2026-10-01','2025-09-30')):
            row=list(ROW);row[3]=str(index+100);row[4]=day;row[8]=str(90000000+index);rows.append(row)
        workbook(self.folder/'months.xlsx',[HEADERS,*rows])
        self.app.erp.commit_import(self.app.company,preview(self.folder/'months.xlsx'),confirmed=True)
        from tests.fixtures import reconcile_empty
        reconcile_empty(self.app.erp,self.app.company)
        self.app.refresh();self.assertEqual(self.app.month_filter.get(),'Οκτώβριος 2026')
        self.app.month_filter.set('Σεπτέμβριος 2026');self.app.refresh()
        ids=[int(key) for key in self.app.tree.get_children()];self.assertEqual(len(ids),1)
        self.assertEqual(self.app._documents[ids[0]]['issue_date'],'2026-09-30')
        accounts=self.app.rpa_panel.accounts()
        fields=[w for w in widgets(accounts) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox)]
        self.assertEqual(len(fields),1);fields[0].insert(0,'64.03')
        self.assertIs(self.app.rpa_panel.accounts(),accounts)
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):self.button(accounts,'Έγκριση λογαριασμών').invoke()
        self.assertEqual(self.count('document_preparations'),1)
        self.assertEqual(self.app.rpa_panel.ids(),ids)
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):self.app.rpa_panel.simulate()
        wait(self.root,lambda:not self.app.busy and not self.app.rpa_panel.running)
        items=self.app.rpa_panel.rpa.items(self.app.company,self.app.rpa_panel.job)[1]
        self.assertEqual([r['document_id'] for r in items],ids)
        self.app.reset_filters();self.assertEqual(self.app.month_filter.get(),'Σεπτέμβριος 2026')
        self.app.month_filter.set('Όλοι οι μήνες');self.app.refresh()
        self.assertEqual(len(self.app.tree.get_children()),3)
        self.assertEqual(self.count('documents'),3)

    def test_missing_accounts_lead_to_single_clear_form_without_queue(self):
        self.import_fixture('separate.xlsx');panel=self.app.rpa_panel
        with patch('app.ui.rpa_panel.messagebox.showinfo') as info:panel.simulate()
        self.assertIn('2 παραστατικά',info.call_args.args[1])
        self.assertEqual(self.count('rpa_jobs'),0)
        self.assertEqual(len(self.app.tree.selection()),2)
        win=panel._accounts
        fields=[w for w in widgets(win) if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox)]
        self.assertEqual(len(fields),2)
        self.assertFalse(any(isinstance(w,ttk.Button) and w.cget('text')=='Εφαρμογή σε όλα εδώ' for w in widgets(win)))
        self.assertEqual(panel.buttons['simulation'].cget('text'),'Έλεγχος χωρίς καταχώριση')

    def test_pdf_cell_opens_archived_file_and_no_visible_sent_status(self):
        from types import SimpleNamespace
        from tests.test_workspace import synthetic_pdf
        self.import_fixture('combined.xlsx');document=int(self.app.tree.get_children()[0])
        self.app.erp.attach_pdf(self.app.company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
        self.app.refresh();self.root.update()
        self.assertNotIn('ebs_state',self.app.tree['columns'])
        self.app.tree.xview_moveto(1);self.root.update()
        box=self.app.tree.bbox(str(document),'pdf_state');self.assertTrue(box)
        with patch('sys.platform','linux'),patch('webbrowser.open',return_value=True) as browser:
            self.app.pdf_click(SimpleNamespace(x=box[0]+5,y=box[1]+5))
            self.assertTrue(browser.call_args.args[0].startswith('file:'))
        self.assertEqual(self.app._details,{})
        self.assertEqual(self.count('rpa_jobs'),0)
        self.app.open_detail();labels=[w.cget('text') for w in widgets(self.app._details[document]) if isinstance(w,ttk.Label)]
        self.assertNotIn('EBS',labels);self.assertNotIn('Δεν στάλθηκε',labels)
        self.root.update();wait(self.root,lambda:not self.app.busy)

    def test_inactive_supplier_tab_does_not_reload_on_search_or_sort(self):
        self.import_fixture('separate.xlsx')
        with patch.object(self.app.suppliers,'refresh',wraps=self.app.suppliers.refresh) as refresh:
            self.app.refresh();self.app.sort_documents('name');refresh.assert_not_called()
            self.app.notebook.select(self.app.suppliers_tab);self.root.update()
            self.assertGreater(refresh.call_count,0)
        self.assertEqual(len(self.app.suppliers.tree.get_children()),2)

    def ebs_fixture_dialog(self,*,vat='000000001',source_date='2026-10-21'):
        from app.application.ebs_reconciliation import EBSReconciliation
        from tests.test_ods import ods
        from xml.sax.saxutils import escape
        headers=['Ημ/νία','Παρ/κό','Εναλ. παρ/κό','Συναλλασσόμενος','Α.Φ.Μ.','Τίτλος','Κατ.','Αξία','ΦΠΑ','Σύνολο']
        values=[source_date,'ΤΕΔ-00001','ΔΟΚ/1','SYN - ΣΥΝΘΕΤΙΚΟΣ',vat,'Συνθετική εγγραφή','2','0,10','0,02','0,12']
        rows=''.join('<table:table-row>'+''.join('<table:table-cell office:value-type="string"><text:p>'+escape(v)+'</text:p></table:table-cell>' for v in row)+'</table:table-row>' for row in (headers,values))
        path=self.folder/'synthetic-ebs.ods';ods(path,rows)
        book=EBSReconciliation(self.app.erp).layout(path)
        self.app.notebook.select(self.app.reconciliation_tab);self.root.update()
        return self.app.reconciliation.import_dialog(book)

    def test_reconciliation_ods_mapping_preview_values_and_real_rpa_selection(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        self.import_fixture('separate.xlsx');win=self.ebs_fixture_dialog()
        win.geometry('920x650');self.root.update()
        self.assertTrue(win.apply_button.winfo_ismapped())
        self.assertLessEqual(win.apply_button.winfo_rooty()+win.apply_button.winfo_height(),win.winfo_rooty()+win.winfo_height())
        self.assertEqual(win.mapping_vars['invoice'].get(),'3: Εναλ. παρ/κό')
        self.assertEqual({k:v.get() for k,v in win.mapping_vars.items()},{'date':'1: Ημ/νία','invoice':'3: Εναλ. παρ/κό','vat':'5: Α.Φ.Μ.','net':'8: Αξία','tax':'9: ΦΠΑ','gross':'10: Σύνολο'})
        self.assertNotIn('2: Παρ/κό',win.column_labels);self.assertNotIn('7: Κατ.',win.column_labels)
        self.assertIn('1: Ημ/νία',win.column_labels);self.assertEqual(len(win.column_labels),6)
        win.mapping_vars['tax'].set('—')
        with patch.object(self.app,'run_worker') as worker:win.check();worker.assert_not_called()
        win.mapping_vars['tax'].set('9: ΦΠΑ')
        win.company_ok_var.set(True);win.complete_var.set(True);win.check()
        wait(self.root,lambda:not self.app.busy)
        self.assertTrue(win.apply_button.instate(['!disabled']))
        self.assertEqual(win.packet['mapping'],{'date':0,'invoice':2,'vat':4,'net':7,'tax':8,'gross':9})
        self.assertEqual(win.packet['rows'][0]['raw'][6],'2')
        self.assertEqual(win.packet['rows'][0]['raw'][0],'2026-10-21')
        self.assertEqual(win.packet['rows'][0]['normalized']['date'],'2026-10-21')
        self.assertNotIn('invoice_type',win.packet['rows'][0]['normalized'])
        self.assertEqual(self.count('rpa_jobs'),0)
        with patch('app.ui.ebs_reconciliation.messagebox.askyesno') as confirm:
            win.apply_button.invoke();wait(self.root,lambda:not self.app.busy);confirm.assert_not_called()
        self.assertEqual(self.app.notebook.select(),str(self.app.documents_tab))
        from app.ui.desktop import STATES
        self.assertEqual(self.app.state_filter.get(),STATES[3])
        rows=EBSReconciliation(self.app.erp).results(self.app.company)
        registered=[r['id'] for r in rows.values() if r['status']=='registered'];pending=[r['id'] for r in rows.values() if r['status']=='not_registered']
        self.assertEqual((len(registered),len(pending)),(1,1))
        tab=self.app.reconciliation;tab.tree.selection_set(str(registered[0]));comparison=tab.details()
        labels=[comparison.comparison_tree.item(i,'values')[0] for i in comparison.comparison_tree.get_children()]
        self.assertTrue({'Καθαρή €','ΦΠΑ €','Σύνολο €'}<=set(labels));self.assertIn('Ημερομηνία',labels);comparison.destroy()
        tab.pending();self.root.update()
        self.assertEqual([int(i) for i in self.app.tree.get_children()],pending)
        self.app.erp.prepare_document(self.app.company,pending[0],'6','64.03',confirmed=True)
        self.app.refresh()
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):self.app.rpa_panel.simulate()
        wait(self.root,lambda:not self.app.busy and not self.app.rpa_panel.running)
        items=self.app.rpa_panel.rpa.items(self.app.company,self.app.rpa_panel.job)[1]
        self.assertEqual([i['document_id'] for i in items],pending)
        self.assertEqual(items[0]['payload']['account'],'64.03')
        self.assertEqual(self.count('documents'),2)

    def test_reconciliation_changing_fields_invalidates_inflight_preview(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        self.import_fixture('separate.xlsx');win=self.ebs_fixture_dialog()
        win.company_ok_var.set(True)
        entered=threading.Event();release=threading.Event();self.releases.append(release)
        original=EBSReconciliation.preview
        def delayed(service,*args,**kwargs):
            entered.set();release.wait(5);return original(service,*args,**kwargs)
        with patch.object(EBSReconciliation,'preview',delayed):
            win.check();wait(self.root,entered.is_set)
            win.mapping_vars['invoice'].set('—');release.set();wait(self.root,lambda:not self.app.busy)
        self.assertIsNone(win.packet);self.assertTrue(win.apply_button.instate(['disabled']))
        self.assertEqual(self.count('rpa_jobs'),0)

    def test_reconciliation_invalid_vat_shows_cell_and_values_without_a_generic_popup(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        self.import_fixture('separate.xlsx');win=self.ebs_fixture_dialog(vat='123')
        runs_before=self.count('ebs_reconciliation_runs')
        win.company_ok_var.set(True);win.complete_var.set(True)
        with patch('app.ui.desktop.messagebox.showerror') as popup:
            win.check();wait(self.root,lambda:not self.app.busy);popup.assert_not_called()
        self.assertTrue(win.packet['can_commit']);self.assertTrue(win.apply_button.instate(['!disabled']))
        values=win.validation_tree.item(win.validation_tree.get_children()[0],'values')
        self.assertEqual(values[:7],('2','2026-10-21','ΔΟΚ/1','123','0,10','0,02','0,12'))
        self.assertIn('E2',values[-1]);self.assertIn('Α.Φ.Μ.',values[-1]);self.assertIn('με ελλείψεις',win.status_var.get())
        self.assertEqual(len(win.results_tree.get_children()),2)
        self.assertEqual(self.count('ebs_reconciliation_runs'),runs_before);self.assertEqual(self.count('rpa_jobs'),0)
        with patch('app.ui.ebs_reconciliation.messagebox.askyesno',return_value=True):win.apply_button.invoke()
        wait(self.root,lambda:not self.app.busy)
        service=EBSReconciliation(self.app.erp)
        states=service.results(self.app.company)
        self.assertEqual(sum(r['status']=='not_registered' for r in states.values()),1)
        self.assertEqual(sum(r['status']=='review' for r in states.values()),1)
        with self.assertRaises(ValueError):service.assert_rpa(self.app.company,list(service.results(self.app.company)),required=True)
        service.assert_rpa(self.app.company,[d for d,r in states.items() if r['status']=='not_registered'],required=True)
        self.assertEqual(self.count('documents'),2);self.assertEqual(self.count('rpa_jobs'),0)

    def test_reconciliation_filters_sort_and_open_document_keep_same_identity(self):
        self.import_fixture('separate.xlsx')
        tab=self.app.reconciliation;self.app.notebook.select(self.app.reconciliation_tab);self.root.update()
        self.assertEqual(len(tab.tree.get_children()),2)
        tab.query.set('000000001');tab.refresh();self.assertEqual(len(tab.tree.get_children()),1)
        document=int(tab.tree.get_children()[0]);tab.sort_by('net_minor');tab.sort_by('invoice')
        tab.tree.selection_set(str(document));tab.open();self.assertTrue(self.app._details[document].winfo_exists())
        self.assertEqual(self.count('documents'),2)

    def test_reconciliation_detects_source_month_and_required_date_mapping(self):
        self.import_fixture('separate.xlsx');win=self.ebs_fixture_dialog(source_date='2026-09-22')
        self.assertEqual(tuple(v.get() for v in win.period_vars),('2026','Σεπτέμβριος'))
        self.assertEqual(set(win.mapping_vars),{'date','invoice','vat','net','tax','gross'})
        win.company_ok_var.set(True);win.complete_var.set(True);win.check();wait(self.root,lambda:not self.app.busy)
        self.assertEqual(win.packet['start'],'2026-09-01');self.assertEqual(win.packet['results'],{})

    def test_default_pending_workspace_and_shared_period_remain_visible_on_every_view(self):
        from app.ui.desktop import STATES
        self.assertEqual(self.initial_state,STATES[3])
        self.app.state_filter.set(STATES[3]);self.app.refresh()
        self.assertIn('Άντληση ΑΑΔΕ',self.app.result_count.get())
        titles=[self.app.notebook.tab(t,'text') for t in self.app.notebook.tabs()]
        self.assertEqual(titles[:5],['Μη καταχωρισμένα στο EBS','Έξοδα','Αγορές','Έσοδα','Δελτία Αποστολής'])
        self.assertEqual(titles[titles.index('Έλεγχοι εισαγωγής')+1],'Προμηθευτές')
        for tab in self.app.notebook.tabs():
            self.app.notebook.select(tab);self.root.update()
            self.assertTrue(self.app.month_box.winfo_ismapped());self.assertTrue(self.app.company_box.winfo_ismapped())

    def test_empty_pdf_has_no_empty_table_or_page_controls_and_saved_pdf_recovers(self):
        from tests.test_workspace import synthetic_pdf
        self.import_fixture('combined.xlsx');document=int(self.app.tree.get_children()[0]);self.app.open_detail(document)
        pane=self.app._details[document].pdf_pane;self.root.update()
        self.assertFalse(pane.files.winfo_ismapped());self.assertFalse(pane.controls.winfo_ismapped());self.assertFalse(pane.canvas_frame.winfo_ismapped())
        self.assertIn('ΑΑΔΕ',pane.state.get())
        self.app.erp.attach_pdf(self.app.company,document,'synthetic.pdf',data=synthetic_pdf(),confirmed=True)
        pane.refresh_if_changed();wait(self.root,lambda:pane.image is not None and not self.app.busy)
        self.assertTrue(pane.files.winfo_ismapped());self.assertTrue(pane.canvas_frame.winfo_ismapped())
        self.assertTrue(pane.previous.instate(['disabled']));self.assertTrue(pane.next.instate(['disabled']))

    def test_views_share_document_identity_and_never_create_a_queue(self):
        from app.application.mydata import MyData
        from app.infrastructure.aade.client import parsed_page
        from tests.test_workflow import response
        service=MyData(self.app.erp)
        for mark,code,outgoing in [('80000001','1.1',False),('80000002','10.1',False),('80000003','1.1',True),('80000004','14.1',True)]:
            raw=response(mark=mark,number=mark,issuer='000000000' if outgoing else '000000001',receiver='000000002' if outgoing else '000000000')
            raw=raw.replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType><isDeliveryNote>true</isDeliveryNote>'.encode())
            service.persist(self.app.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))],'RequestTransmittedDocs' if outgoing else 'RequestDocs')
            service.import_documents(self.app.company,'production','2026-10-01','2026-10-31',confirmed=True,direction='outgoing' if outgoing else 'incoming')
        self.app.refresh();views=self.app.document_views
        self.assertEqual(len(views['expenses'].rows),2);self.assertEqual(len(views['income'].rows),1);self.assertEqual(len(views['movement'].rows),4)
        document=next(iter(views['expenses'].rows));self.assertIn(document,views['movement'].rows)
        movement=views['movement'];movement.kind.set('Ποσοτικές παραλαβές');movement.refresh()
        self.assertEqual(len(movement.rows),1);self.assertEqual(next(iter(movement.rows.values()))['invoice_type'],'10.1')
        income=views['income'];self.app.notebook.select(income.parent);self.root.update();income.query.set('80000003');income.refresh();chosen=next(iter(income.rows))
        income.tree.selection_set(str(chosen));income.detail();self.assertIn(chosen,self.app._details)
        self.assertNotIn('account_code',income.tree['columns']);self.assertNotIn('reconciliation',income.tree['columns'])
        self.assertFalse(any(isinstance(w,ttk.Notebook) for w in widgets(self.app._details[chosen])))
        self.app.notebook.select(views['expenses'].parent);self.root.update()
        views['expenses'].tree.selection_set(str(document));views['expenses'].detail()
        notebooks=[w for w in widgets(self.app._details[document]) if isinstance(w,ttk.Notebook)]
        self.assertIn('Προετοιμασία EBS',[notebooks[0].tab(t,'text') for t in notebooks[0].tabs()])
        self_expense=next(r['id'] for r in views['expenses'].rows.values() if r['self_recorded_expense'])
        self.app.open_detail(self_expense)
        self.assertTrue(any(isinstance(w,ttk.Notebook) for w in widgets(self.app._details[self_expense])))
        self.assertEqual(self.count('documents'),4);self.assertEqual(self.count('rpa_jobs'),0)

    def test_default_rpa_scope_honors_selection_for_simulation_and_execution(self):
        self.import_fixture('separate.xlsx');ids=list(self.app._documents)
        for document in ids:self.app.erp.prepare_document(self.app.company,document,'6','64.03',confirmed=True)
        self.app.refresh();panel=self.app.rpa_panel
        self.app.tree.selection_set(str(ids[0]));self.assertEqual(panel.ids(),[ids[0]])
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True):panel.simulate()
        wait(self.root,lambda:not self.app.busy and not panel.running)
        _,items=panel.rpa.items(self.app.company,panel.job)
        self.assertEqual([i['document_id'] for i in items],[ids[0]])
        self.assertEqual(panel.ids(),[ids[0]])
        self.assertFalse(panel.execution_controls.winfo_ismapped())

    def test_company_switch_is_scoped_and_waits_for_open_document_windows(self):
        self.import_fixture('combined.xlsx');company=self.app.company
        other=self.app.erp.company('000000009','ΑΛΛΗ ΣΥΝΘΕΤΙΚΗ');self.app.refresh()
        label=next(k for k,v in self.app.company_choices.items() if v==other)
        self.app.open_detail(next(iter(self.app._documents)))
        self.app.company_filter.set(label);self.app.company_changed();self.assertEqual(self.app.company,company)
        self.close_children();self.app.company_filter.set(label);self.app.company_changed()
        self.assertEqual(self.app.company,other);self.assertEqual(self.app._documents,{})
        self.assertTrue(all(not v.rows for v in self.app.document_views.values()))

    def test_partial_matching_is_saved_excluded_and_confirmed_inline_without_popups(self):
        from app.application.ebs_reconciliation import EBSReconciliation
        from app.ui.desktop import STATES
        self.import_fixture('separate.xlsx');win=self.ebs_fixture_dialog()
        # Change only the frozen synthetic source, never the customer workbook.
        from tests.test_ods import ods
        from xml.sax.saxutils import escape
        headers=['Ημ/νία','Εναλ. παρ/κό','Α.Φ.Μ.','Αξία','ΦΠΑ','Σύνολο']
        values=['2026-10-21','ΔΟΚ-0001','000000001','0,10','0,02','0,12']
        path=self.folder/'partial.ods'
        ods(path,''.join('<table:table-row>'+''.join('<table:table-cell office:value-type="string"><text:p>'+escape(v)+'</text:p></table:table-cell>' for v in row)+'</table:table-row>' for row in (headers,values)))
        win.destroy();service=EBSReconciliation(self.app.erp);book=service.layout(path)
        win=self.app.reconciliation.import_dialog(book);win.company_ok_var.set(True);win.complete_var.set(True)
        win.check();wait(self.root,lambda:not self.app.busy)
        with patch('app.ui.ebs_reconciliation.messagebox.askyesno') as popup:
            win.apply_button.invoke();wait(self.root,lambda:not self.app.busy);popup.assert_not_called()
        rows=service.results(self.app.company);partial=next(r for r in rows.values() if r['match_kind']=='normalized')
        self.assertNotIn(str(partial['id']),self.app.tree.get_children())
        self.assertEqual(len(self.app.tree.get_children()),1)
        with self.assertRaises(ValueError):service.assert_rpa(self.app.company,[partial['id']],required=True)
        tab=self.app.reconciliation;self.app.notebook.select(self.app.reconciliation_tab);self.root.update()
        tab.tree.selection_set(str(partial['id']));self.root.update()
        self.assertEqual(tab.confirm_button.cget('text'),'Επιβεβαίωση αντιστοίχισης')
        comparison=tab.details();changed=[comparison.comparison_tree.item(i,'values')[0] for i in comparison.comparison_tree.get_children() if 'difference' in comparison.comparison_tree.item(i,'tags')]
        self.assertEqual(changed,['Παραστατικό']);comparison.destroy()
        with patch('app.ui.ebs_reconciliation.messagebox.askyesno') as popup:
            tab.confirm_button.invoke();self.root.update();popup.assert_not_called()
        self.assertEqual(service.results(self.app.company)[partial['id']]['match_kind'],'normalized_confirmed')
        self.assertEqual(self.count('rpa_jobs'),0)

    def test_ready_expenses_continue_when_another_invoice_has_no_account_approval(self):
        self.import_fixture('separate.xlsx');ids=list(self.app._documents)
        self.app.erp.prepare_document(self.app.company,ids[0],'6','64.03',confirmed=True)
        self.app.refresh();panel=self.app.rpa_panel
        with patch('app.ui.rpa_panel.messagebox.askyesno',return_value=True),patch.object(panel,'accounts') as accounts:
            panel.simulate();wait(self.root,lambda:not self.app.busy and not panel.running)
            accounts.assert_not_called()
        _,items=panel.rpa.items(self.app.company,panel.job)
        self.assertEqual([i['document_id'] for i in items],[ids[0]])
        self.assertEqual(items[0]['status'],'simulated')
        self.assertIsNone(self.app.erp.preparation(self.app.company,ids[1]))

    def test_purchase_context_menu_counts_all_months_applies_and_undoes_without_popups(self):
        from types import SimpleNamespace
        from tests.test_supplier_purchases import synthetic_vat
        from app.ui.desktop import STATES
        rows=[]
        for number,day in [('1','2026-09-21'),('2','2026-10-21')]:
            row=list(ROW);row[0]=synthetic_vat();row[3]=number;row[4]=day;row[8]=str(70000000+int(number));rows.append(row)
        workbook(self.folder/'inputs/purchases.xlsx',[HEADERS,*rows]);self.import_fixture('purchases.xlsx')
        self.app.state_filter.set(STATES[3]);self.app.refresh();self.root.update()
        item=self.app.tree.get_children()[0];x,y,w,h=self.app.tree.bbox(item,'name')
        event=SimpleNamespace(x=x+5,y=y+h//2,x_root=x+5,y_root=y+h//2)
        with patch('tkinter.Menu.tk_popup'),patch('app.ui.desktop.messagebox.askyesno') as popup:
            self.app.purchase_menu(event,self.app.tree)
            self.assertIn('2 εκκρεμή',self.app._purchase_menu.entrycget(0,'label'))
            self.app._purchase_menu.invoke(0);self.root.update();popup.assert_not_called()
        self.assertFalse(self.app.tree.get_children());self.assertTrue(self.app.purchase_undo_button.winfo_ismapped())
        purchases=self.app.document_views['purchases'];self.assertEqual(len(purchases.rows),1)
        self.app.month_filter.set('Όλοι οι μήνες');self.app.refresh();self.assertEqual(len(purchases.rows),2)
        self.assertFalse(self.app.document_views['expenses'].rows)
        self.app.notebook.select(purchases.parent);self.root.update();purchases.query.set(synthetic_vat());purchases.refresh()
        document=next(iter(purchases.rows));purchases.tree.selection_set(str(document))
        with patch.object(self.app,'open_pdf') as pdf:purchases.pdf();pdf.assert_called_once_with(document)
        self.app.purchase_undo_button.invoke();self.assertFalse(purchases.rows)
        self.assertEqual(len(self.app.tree.get_children()),2);self.assertEqual(self.count('document_preparations'),0)

    def test_income_pdf_download_occurs_only_on_explicit_individual_open(self):
        from tests.test_workspace import synthetic_pdf
        self.import_fixture('separate.xlsx');document=next(iter(self.app._documents))
        with self.app.erp.db:self.app.erp.db.execute("UPDATE documents SET direction='outgoing' WHERE id=?",(document,))
        self.app.refresh()
        def download(service,company,chosen):
            service.erp.attach_pdf(company,chosen,'synthetic-income.pdf',data=synthetic_pdf(),confirmed=True)
            return dict(cached=False)
        with patch('app.application.sync.Sync.document_pdf',autospec=True,side_effect=download) as fetch,patch('webbrowser.open',return_value=True),patch('os.startfile',create=True):
            self.app.refresh();fetch.assert_not_called()
            self.app.open_pdf(document);wait(self.root,lambda:not self.app.busy)
            fetch.assert_called_once()
            self.assertEqual(len(self.app.erp.attachments(self.app.company,document)),1)
            self.app.open_pdf(document);fetch.assert_called_once()

    def test_bulk_name_lookup_runs_in_background_can_stop_and_prevents_duplicate_start(self):
        from app.application.registry import Registry
        from app.ui.registry import fill_missing
        from tests.test_supplier_purchases import synthetic_vat
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        with self.app.erp.db:
            self.app.erp.db.execute("UPDATE companies SET vat='000000008' WHERE id=?",(self.app.company,))
            for number in (1,2):self.app.erp.db.execute('INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?)',(self.app.company,synthetic_vat(number),' '))
        Registry(self.app.erp).save_credentials(self.app.company,'synthetic','synthetic',confirmed=True)
        entered=threading.Event();release=threading.Event();self.releases.append(release);calls=[]
        def lookup(user,key,caller,called):
            calls.append(called);entered.set();release.wait(5);return dict(afm=called,onomasia='ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        # Default transport is bound at definition, so pass the fake through the batch service.
        original=Registry.fill_missing
        def batch(service,company,**kwargs):return original(service,company,transport=lookup,**kwargs)
        with patch.object(Registry,'fill_missing',batch),patch('app.ui.registry.messagebox.askyesno') as popup:
            win=fill_missing(self.app);wait(self.root,entered.is_set)
            self.assertIsNone(fill_missing(self.app));self.assertTrue(self.app.busy)
            win.cancel_event.set();release.set();wait(self.root,lambda:not self.app.busy)
            popup.assert_not_called()
        self.assertEqual(len(calls),1);self.assertIn('Συμπληρώθηκαν: 1',win.status_var.get());self.assertIn('Παραλείφθηκαν: 1',win.status_var.get())
        self.assertEqual(self.count('provider_attempts'),0)

    def test_main_column_sort_and_filters_do_not_reload_data_or_lose_selection(self):
        self.import_fixture('separate.xlsx');self.app.refresh();tree=self.app.tree
        selected=tree.get_children()[0];tree.selection_set(selected);tree.focus(selected)
        tree.column('vat',width=180);self.root.update_idletasks();vat_width=tree.column('vat','width')
        before={key:self.app._documents[key]['gross_minor'] for key in self.app._documents};calls=[]
        self.app.erp.db.set_trace_callback(calls.append)
        try:
            with patch.object(self.app,'refresh') as reload,patch.object(self.app.rpa_panel,'refresh') as rpa:
                self.app.sort_documents('gross_minor');self.root.update()
                self.assertEqual(tree.selection(),(selected,));self.assertEqual(tree.focus(),selected)
                self.app.column_filters.set('gross_minor','<=0,12')
                self.assertEqual(len(tree.get_children()),1)
                self.assertEqual(tree.column('vat','width'),vat_width)
                self.app.column_filters.set('reference','=does-not-exist')
                self.assertFalse(tree.get_children());self.assertTrue(self.app.rpa_panel.buttons['post'].instate(['disabled']))
                self.app.column_filters.clear(notify=True);self.app.reset_filters();self.assertEqual(len(tree.get_children()),2)
                self.app.query.set('ΔΟΚ/1');self.app.filter_documents();self.assertEqual(len(tree.get_children()),1)
                reload.assert_not_called();rpa.assert_not_called()
        finally:self.app.erp.db.set_trace_callback(None)
        self.assertEqual(calls,[]);self.app.reset_filters()
        self.assertEqual(before,{key:self.app._documents[key]['gross_minor'] for key in self.app._documents})

    def test_other_views_filter_and_sort_cached_rows_without_database_queries(self):
        self.import_fixture('separate.xlsx');self.app.refresh()
        for view,parent in [(self.app.document_views['expenses'],self.app.document_views['expenses'].parent),(self.app.reconciliation,self.app.reconciliation_tab)]:
            self.app.notebook.select(parent);self.root.update();calls=[];self.app.erp.db.set_trace_callback(calls.append)
            try:
                view.sort_by('gross_minor');view.column_filters.set('gross_minor','<=0,12')
                self.assertEqual(len(view.tree.get_children()),1)
                view.clear();view.query.set('ΔΟΚ/1')
                view.refresh(view.rows) if view is self.app.reconciliation else view.refresh()
                self.assertEqual(len(view.tree.get_children()),1)
            finally:self.app.erp.db.set_trace_callback(None)
            self.assertEqual(calls,[])

    def test_heading_double_click_never_opens_a_previously_selected_document(self):
        from types import SimpleNamespace
        self.import_fixture('separate.xlsx');self.app.refresh()
        event=SimpleNamespace(x=10,y=5)
        with patch.object(self.app,'open_detail') as opened:
            self.app.document_double_click(event)
            for name in ('expenses','purchases','income','movement'):
                view=self.app.document_views[name];self.app.notebook.select(view.parent);self.root.update();view.double_click(event)
            self.app.notebook.select(self.app.reconciliation_tab);self.root.update();self.app.reconciliation.double_click(event)
            opened.assert_not_called()

    def test_registry_placeholder_batch_shows_request_progress_before_slow_response(self):
        from app.application.registry import Registry
        from app.ui.registry import fill_missing
        from tests.test_supplier_purchases import synthetic_vat
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        with self.app.erp.db:
            self.app.erp.db.execute("UPDATE companies SET vat='000000008' WHERE id=?",(self.app.company,))
            for number,name in [(1,'Χωρίς επωνυμία'),(2,synthetic_vat(2))]:self.app.erp.db.execute('INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,?)',(self.app.company,synthetic_vat(number),name))
        Registry(self.app.erp).save_credentials(self.app.company,'synthetic','synthetic',confirmed=True)
        entered=threading.Event();release=threading.Event();self.releases.append(release);calls=[]
        def lookup(*args):
            calls.append(args[-1]);entered.set();release.wait(5);return dict(afm=args[-1],onomasia='ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        original=Registry.fill_missing
        def batch(service,company,**kwargs):return original(service,company,transport=lookup,**kwargs)
        with patch.object(Registry,'fill_missing',batch):
            win=fill_missing(self.app);wait(self.root,entered.is_set)
            wait(self.root,lambda:'Αναζήτηση 1 από 2' in win.status_var.get())
            self.assertTrue(win.winfo_exists());release.set();wait(self.root,lambda:not self.app.busy)
        self.assertEqual(len(calls),2);self.assertIn('Συμπληρώθηκαν: 2',win.status_var.get())
        self.assertEqual(self.count('provider_attempts'),0)

    def test_registry_missing_credentials_finishes_dialog_with_clear_action(self):
        from app.ui.registry import fill_missing
        from tests.test_workspace import MemoryVault
        self.app.erp.credential_store=MemoryVault()
        with self.app.erp.db:self.app.erp.db.execute("UPDATE companies SET vat='000000008' WHERE id=?",(self.app.company,))
        with patch('app.ui.desktop.messagebox.showerror') as popup:
            win=fill_missing(self.app);wait(self.root,lambda:not self.app.busy);popup.assert_not_called()
        self.assertIn('Λείπουν ειδικοί κωδικοί Μητρώου',win.status_var.get())
        self.assertTrue(self.button(win,'Κλείσιμο').instate(['!disabled']))

    def test_right_click_heading_opens_column_filter_alongside_supplier_menu(self):
        self.import_fixture('separate.xlsx');self.app.refresh();self.root.update()
        tree=self.app.tree;row=tree.get_children()[0];x,y,width,height=tree.bbox(row,'gross_minor')
        tree.event_generate('<Button-3>',x=x+5,y=5);self.root.update()
        win=self.app.column_filters.window;self.assertIsNotNone(win);self.assertTrue(win.winfo_exists())
        entry=next(w for w in widgets(win) if isinstance(w,ttk.Entry));entry.insert(0,'<=0,12')
        self.button(win,'Εφαρμογή').invoke();self.root.update()
        self.assertEqual(len(tree.get_children()),1);self.assertTrue(tree.heading('gross_minor','text').startswith('● '))
        self.assertEqual(self.count('rpa_jobs'),0)


    def test_ebs_screen_mapping_captures_all_fields_without_clicks_and_persists(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from app.infrastructure.ebs_adapter.adapter import FIELDS
        panel=self.app.rpa_panel;win=panel.settings();self.root.update()
        self.assertIs(panel.settings(),win)
        backend=Mock();backend.pg.position.return_value=(-1350,240)
        callbacks=[]
        with patch('app.ui.rpa_panel.sys',SimpleNamespace(platform='win32')),patch('app.infrastructure.ebs_adapter.session.WindowsSession',return_value=backend),patch('app.ui.rpa_panel.messagebox.showinfo'),patch.object(self.root,'after',side_effect=lambda ms,fn:callbacks.append(fn) or 'capture'):
            for field in ('ΑΦΜ πιστωτή','Αριθμός παραστατικού','Ημερομηνία · πρώτο ψηφίο','Κελί λογαριασμού εξόδων','Κελί καθαρής αξίας','Save','Νέο ΤΕΔ'):
                self.button(win,'Καταγραφή '+field).invoke()
                self.assertEqual(str(self.root.state()),'withdrawn')
                callbacks.pop()()
        self.assertEqual(backend.validate_target.call_count,5)
        backend.validate_target.assert_any_call('INVOICE_DATE',(-1350,240))
        self.assertEqual(backend.at_ebs.call_count,2)
        backend.pg.click.assert_not_called();backend.pg.write.assert_not_called()
        self.assertIsNone(panel.workspace.profile(self.app.company))
        self.button(win,'Αποθήκευση ρυθμίσεων').invoke();self.root.update()
        saved=panel.workspace.profile(self.app.company)
        self.assertEqual(saved['profile']['mapping'],{key:[-1350,240] for key,_ in FIELDS})
        self.assertEqual(saved['profile']['save'],[-1350,240]);self.assertIsNone(saved['pilot_at'])
        self.assertEqual(self.count('rpa_jobs'),0)

    def test_ebs_mapping_rejects_wrong_window_and_close_cancels_capture(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        panel=self.app.rpa_panel;win=panel.settings();self.root.update()
        backend=Mock();backend.pg.position.return_value=(500,300)
        backend.validate_target.side_effect=RuntimeError('Το σημείο δεν ανήκει στο Entersoft')
        callbacks=[]
        with patch('app.ui.rpa_panel.sys',SimpleNamespace(platform='win32')),patch('app.infrastructure.ebs_adapter.session.WindowsSession',return_value=backend),patch('app.ui.rpa_panel.messagebox.showinfo'),patch('app.ui.rpa_panel.messagebox.showerror') as error,patch.object(self.root,'after',side_effect=lambda ms,fn:callbacks.append(fn) or 'capture'):
            self.button(win,'Καταγραφή ΑΦΜ πιστωτή').invoke();callbacks.pop()()
            error.assert_called_once();self.assertEqual(str(self.root.state()),'normal')
            with patch.object(self.root,'after_cancel') as cancel:
                self.button(win,'Καταγραφή ΑΦΜ πιστωτή').invoke()
                self.root.tk.call(win.protocol('WM_DELETE_WINDOW'))
                cancel.assert_called_once_with('capture')
                self.assertEqual(str(self.root.state()),'normal')
        self.assertIsNone(panel.workspace.profile(self.app.company))
        backend.pg.click.assert_not_called()

    def test_cell_menu_filters_and_excludes_without_selecting_or_database_refresh(self):
        self.import_fixture('separate.xlsx');self.app.refresh();self.root.update()
        tree=self.app.tree;filters=self.app.column_filters
        rows=list(self.app._documents.values());row=rows[0];other=rows[1]
        tree.selection_set(str(other['id']))
        column=list(tree['displaycolumns']).index('name')
        x,y,w,h=tree.bbox(str(row['id']),'name')
        with patch('tkinter.Menu.tk_popup'),patch.object(self.app,'refresh',side_effect=AssertionError('SQL reload')):
            tree.event_generate('<Button-3>',x=x+5,y=y+5);self.root.update()
            menu=filters.menu
            labels=[menu.entrycget(i,'label') for i in range(menu.index('end')+1) if menu.type(i)=='command']
            self.assertIn('Φίλτρο με αυτή την τιμή',labels)
            index=next(i for i in range(menu.index('end')+1) if menu.type(i)=='command' and menu.entrycget(i,'label')=='Φίλτρο με αυτή την τιμή')
            menu.invoke(index)
            self.assertEqual(list(self.app._documents),[row['id']])
            self.assertEqual(tree.selection(),())  # Hidden selection is never promoted to all visible.
            filters.clear(notify=True);filters.cell('name',row['name'],True)
            self.assertEqual(list(self.app._documents),[other['id']])
            filters.clear(notify=True);self.assertEqual(len(self.app._documents),2)
        self.assertEqual(self.count('rpa_jobs'),0)

    def test_cell_filters_shared_across_supplier_document_and_review_views(self):
        self.import_fixture('separate.xlsx');self.app.refresh()
        views=list(self.app.document_views.values())
        for view in views:
            view.refresh()
            if view.rows:
                row=next(iter(view.rows.values()));view.column_filters.cell('vat',row['vat'])
                self.assertTrue(all(r['vat']==row['vat'] for r in view.rows.values()))
                view.column_filters.clear(notify=True)
        tab=self.app.suppliers;tab.refresh();row=next(iter(tab.rows.values()))
        with patch.object(tab.service,'rows',side_effect=AssertionError('Unnecessary reload')):
            tab.column_filters.cell('vat',row['vat'])
            self.assertEqual(len(tab.rows),1);tab.column_filters.clear(notify=True)
        review=self.app.review_filters
        before=len(self.app.review_tree.get_children());job=next(iter(self.app._review_rows.values()))
        review.cell('filename',job['filename'],True)
        self.assertLess(len(self.app.review_tree.get_children()),before)
        review.clear(notify=True);self.assertEqual(len(self.app.review_tree.get_children()),before)

    def test_posting_actions_use_visible_order_and_never_promote_filter_to_selection(self):
        from types import SimpleNamespace
        self.import_fixture('separate.xlsx');self.app.refresh();panel=self.app.rpa_panel
        visible=[int(k) for k in self.app.tree.get_children()]
        self.app.tree.move(str(visible[1]),'',0);order=[visible[1],visible[0]]
        self.app.tree.selection_set(str(visible[0]))
        with patch('app.ui.rpa_panel.sys',SimpleNamespace(platform='win32')),patch('app.ui.rpa_panel.RPA.posting',return_value=dict(job=123,documents=order,skipped=[],pilot=False)) as create,patch.object(panel,'start') as start,patch.object(self.app,'run_worker',side_effect=lambda f,done:done(f())),patch('app.ui.rpa_panel.messagebox.askyesno') as confirm:
            panel.post();create.assert_called_with(self.app.company,order,limit=40)
            panel.post_selected();create.assert_called_with(self.app.company,[visible[0]],limit=None)
            panel.post_one();create.assert_called_with(self.app.company,[visible[0]],limit=None)
            self.assertEqual(start.call_count,3);confirm.assert_not_called()
            create.reset_mock();self.app.tree.selection_remove(*self.app.tree.selection())
            panel.post_selected();panel.post_one();create.assert_not_called()
        panel.job=None
        self.assertEqual(panel.buttons['post'].cget('text'),'Καταχώριση έως 40')
        self.assertFalse(panel.buttons['accounts'].winfo_ismapped());self.assertFalse(panel.buttons['simulation'].winfo_ismapped())

    def test_posting_restores_paused_queue_and_shows_processed_progress(self):
        self.import_fixture('separate.xlsx');panel=self.app.rpa_panel
        ids=list(self.app._documents)
        panel.workspace.approve_many(self.app.company,[dict(document=d,group='6',account='64.03') for d in ids],confirmed=True)
        self.app.tree.selection_set([str(d) for d in ids]);panel.queue_selected();job=panel.job
        panel.rpa.pause(self.app.company,job);panel.job=None
        panel.restore_job();panel.refresh();self.root.update()
        self.assertEqual(panel.job,job);self.assertIn('0/2',panel.state.get())
        self.assertTrue(panel.buttons['resume'].winfo_ismapped());self.assertFalse(panel.buttons['pause'].winfo_ismapped())

    def test_search_clear_preserves_pending_group_and_cell_exclusions_through_refresh(self):
        from copy import deepcopy
        from tests.fixtures import reconcile_empty
        self.import_fixture('separate.xlsx');app=self.app
        ids=list(app._documents)
        app.rpa_panel.workspace.approve_many(app.company,[dict(document=d,group='6',account='64.03') for d in ids],confirmed=True,remember=True)
        app.state_filter.set('Μη καταχωρισμένα');app.group_filter.set('Ομάδα 6 · Έξοδα');app.refresh();self.root.update()
        excluded=app._documents[ids[0]]['name'];tree=app.tree
        x,y,w,h=tree.bbox(str(ids[0]),'name')
        with patch('tkinter.Menu.tk_popup'):
            tree.event_generate('<Button-3>',x=x+5,y=y+5);self.root.update()
            menu=app.column_filters.menu
            index=next(i for i in range(menu.index('end')+1) if menu.type(i)=='command' and menu.entrycget(i,'label')=='Εξαίρεση αυτής της τιμής')
            menu.invoke(index)
        app.column_filters.set('gross_minor','>=0,00')
        expected=set(app._documents);self.assertEqual(expected,{ids[1]})
        before_filters=deepcopy((app.column_filters.filters,app.column_filters.cell_filters))
        app.query.set('unmatched query');app.filter_documents();self.assertFalse(app._documents)
        before_db=list(app.erp.db.iterdump());before_evidence=deepcopy(app._evidence)
        self.button(app.documents_tab,'Καθαρισμός').invoke()
        self.assertEqual(app.query.get(),'');self.assertEqual(app.state_filter.get(),'Μη καταχωρισμένα')
        self.assertEqual(app.group_filter.get(),'Ομάδα 6 · Έξοδα')
        self.assertEqual((app.column_filters.filters,app.column_filters.cell_filters),before_filters)
        self.assertEqual(set(app._documents),expected);self.assertTrue(all(r['name']!=excluded for r in app._documents.values()))
        self.assertEqual(list(app.erp.db.iterdump()),before_db);self.assertEqual(app._evidence,before_evidence)
        app.notebook.select(app.reconciliation_tab);self.root.update();app.notebook.select(app.documents_tab);self.root.update()
        app.refresh();self.assertEqual(set(app._documents),expected)
        reconcile_empty(app.erp,app.company);app.refresh()
        self.assertEqual(set(app._documents),expected)
        self.assertEqual((app.column_filters.filters,app.column_filters.cell_filters),before_filters)
        app.column_filters.remove('name');self.assertEqual(set(app._documents),set(ids))
        app.column_filters.clear(notify=True);self.assertFalse(app.column_filters.cell_filters)
        self.assertEqual(app.state_filter.get(),'Μη καταχωρισμένα')

    def test_other_search_clear_handlers_preserve_kind_status_date_and_amount_exclusions(self):
        from copy import deepcopy
        self.import_fixture('separate.xlsx');app=self.app;app.refresh()
        for view in app.document_views.values():
            view.kind.set('Δελτία αποστολής' if view.view=='movement' else 'Τιμολόγια')
            view.column_filters.cell('issue_date','2026-10-21',True)
            if 'gross_minor' in view.tree['columns']:view.column_filters.cell('gross_minor',12,True)
            wanted=deepcopy((view.column_filters.filters,view.column_filters.cell_filters));kind=view.kind.get()
            view.query.set('unmatched query');view.refresh()
            self.button(view.parent,'Καθαρισμός').invoke()
            self.assertEqual(view.query.get(),'');self.assertEqual(view.kind.get(),kind)
            self.assertEqual((view.column_filters.filters,view.column_filters.cell_filters),wanted)
            self.assertTrue(all(r['issue_date']!='2026-10-21' for r in view.rows.values()))
            view.column_filters.clear(notify=True);self.assertFalse(view.column_filters.cell_filters)
        view=app.reconciliation;view.filter.set('Μη καταχωρισμένα')
        view.column_filters.cell('issue_date','2026-10-21',True);view.column_filters.cell('gross_minor',12,True)
        wanted=deepcopy((view.column_filters.filters,view.column_filters.cell_filters))
        view.query.set('unmatched query');view.refresh(view.rows)
        before=list(app.erp.db.iterdump())
        self.button(app.reconciliation_tab,'Καθαρισμός').invoke()
        self.assertEqual(view.query.get(),'');self.assertEqual(view.filter.get(),'Μη καταχωρισμένα')
        self.assertEqual((view.column_filters.filters,view.column_filters.cell_filters),wanted)
        self.assertEqual(list(app.erp.db.iterdump()),before)
        self.assertEqual(len(view.tree.get_children()),1)
        app.refresh();self.assertEqual((view.column_filters.filters,view.column_filters.cell_filters),wanted)
        view.column_filters.clear(notify=True);self.assertFalse(view.column_filters.cell_filters)

    def test_clear_search_cannot_reintroduce_delivery_note_into_posting_list(self):
        from app.application.mydata import MyData
        from app.infrastructure.aade.client import parsed_page
        from tests.test_workflow import response
        from tests.fixtures import reconcile_empty
        self.import_fixture('separate.xlsx');app=self.app
        xml=response(mark='88000001',number='DELIVERY').replace(b'<invoiceType>1.1</invoiceType>',b'<invoiceType>9.3</invoiceType>')
        api=MyData(app.erp);api.persist(app.company,'production','2026-10-01','2026-10-31',[(xml,parsed_page(xml))],'RequestDocs')
        api.import_documents(app.company,'production','2026-10-01','2026-10-31',confirmed=True)
        reconcile_empty(app.erp,app.company)
        app.state_filter.set('Μη καταχωρισμένα');app.refresh()
        self.assertTrue(any(r['mark']=='88000001' for r in app._month_rows))
        app.query.set('DELIVERY');app.filter_documents()
        self.button(app.documents_tab,'Καθαρισμός').invoke();app.refresh()
        self.assertTrue(app._documents)
        self.assertTrue(all(r['kind']=='invoice' and (not r['invoice_type'] or r['rpa_allowed']) for r in app._documents.values()))
        self.assertNotIn('88000001',{r['mark'] for r in app._documents.values()})
        self.assertEqual(self.count('rpa_jobs'),0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
