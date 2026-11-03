"""Synthetic AADE dialog checks; run with DISPLAY=:99 python -m tests.gui_aade_rate_limit."""
import gc
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.application.mydata import MyData
from app.application.service import ERP
from app.infrastructure.aade.client import Client
from app.ui.aade_dialog import open_settings
from tests.gui_smoke import widgets
from tests.test_workflow import Opener, response
from tests.test_workspace import MemoryVault


class AADERateLimitDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.display_root=tk.Tk();cls.display_root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.display_root.destroy();cls.display_root=None;gc.collect()

    def setUp(self):
        Client._cooldowns.clear()
        self.network=patch.object(socket,'create_connection',side_effect=AssertionError('Live network forbidden'))
        self.network.start();self.addCleanup(self.network.stop)
        self.temp=tempfile.TemporaryDirectory();self.erp=ERP(Path(self.temp.name)/'data',MemoryVault())
        self.company=self.erp.company('000000008','SYNTHETIC')
        self.erp.save_mydata_credentials(self.company,'production','synthetic','SYNTHETIC_KEY',confirmed=True)
        self.root=tk.Toplevel(self.display_root);self.root.withdraw()
        owner=SimpleNamespace(root=self.root,erp=self.erp,company=self.company,directory=self.erp.directory,
                              busy=False,rpa_panel=SimpleNamespace(running=False),_closing=False,
                              refresh=lambda:None,open_settings=lambda _:None)
        owner.run_worker=lambda execute,done:done(execute())
        self.owner=owner
        self.win=open_settings(owner,period='2026-10')
        labels=[w for w in widgets(self.win) if isinstance(w,ttk.Label) and w.cget('textvariable')]
        self.status=next(w for w in labels if 'Credential Manager' in self.label(w))
        self.output=next(w for w in labels if self.label(w).startswith('Άντληση εξόδων μήνα'))

    def tearDown(self):
        for timer in self.root.tk.call('after','info'):self.root.after_cancel(timer)
        self.win.destroy();self.root.destroy();self.erp.close();self.temp.cleanup()
        # Release dialog closures/StringVars while their Tcl owner thread is active.
        self.win=None;self.status=None;self.output=None;self.root=None
        Client._cooldowns.clear();gc.collect()

    def label(self,widget):return str(widget.getvar(widget.cget('textvariable')))

    def fetch(self,bodies,test):
        opener=Opener(bodies)
        # Delegate to the real service; observe whether the dialog starts another method.
        original=MyData.fetch
        with patch('urllib.request.build_opener',return_value=opener),patch.object(MyData,'fetch',autospec=True,side_effect=original) as calls:
            self.win.fetch_aade(test)
        return opener,calls.call_count

    def test_first_429_stops_find_and_connection_test_before_next_method(self):
        for test in (False,True):
            with self.subTest(test=test):
                Client._cooldowns.clear()
                opener,calls=self.fetch([HTTPError('https://example.invalid',429,'synthetic',{'Retry-After':'120'},None)],test)
                self.assertEqual(calls,1)
                self.assertEqual(len(opener.requests),1)
                self.assertIn('Δεν ολοκληρώθηκε',self.label(self.status))
                self.assertIn('0/2',self.label(self.status))
                self.assertIn('HTTP 429',self.label(self.output));self.assertIn('120',self.label(self.output))
                self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_syncs').fetchone()[0],0)

    def test_second_429_reports_partial_communication_and_keeps_completed_snapshot(self):
        opener,calls=self.fetch([response(receiver='000000008'),HTTPError('https://example.invalid',429,'synthetic',{'Retry-After':'120'},None)],False)
        self.assertEqual(calls,2);self.assertEqual(len(opener.requests),2)
        self.assertIn('Μερική επικοινωνία',self.label(self.status));self.assertIn('1/2',self.label(self.status))
        self.assertIn('RequestDocs',self.label(self.status))
        self.assertIn('HTTP 429',self.label(self.status));self.assertIn('120',self.label(self.status))
        self.assertIn('1/2',self.label(self.output))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_syncs').fetchone()[0],1)
        self.assertEqual(self.erp.db.execute('SELECT mark FROM mydata_records').fetchone()[0],'10000001')

    def test_partial_connection_test_does_not_persist_records(self):
        self.fetch([response(receiver='000000008'),HTTPError('https://example.invalid',429,'synthetic',{'Retry-After':'120'},None)],True)
        self.assertIn('Μερική επικοινωνία',self.label(self.status));self.assertIn('1/2',self.label(self.status))
        self.assertIn('HTTP 429',self.label(self.output))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_syncs').fetchone()[0],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_records').fetchone()[0],0)

    def test_complete_connection_test_keeps_success_message_and_no_snapshots(self):
        opener,calls=self.fetch([response(receiver='000000008'),response(mark='10000002',issuer='000000008',receiver='000000001',number='2')],True)
        self.assertEqual(calls,2);self.assertEqual(len(opener.requests),2)
        self.assertTrue(self.label(self.status).startswith('Επιτυχής επικοινωνία:'))
        self.assertIn('RequestDocs',self.label(self.status));self.assertIn('RequestTransmittedDocs',self.label(self.status))
        self.assertIn('Δεν αποθηκεύτηκαν παραστατικά',self.label(self.output))
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM mydata_syncs').fetchone()[0],0)

    def test_main_acquisition_never_downloads_pdf_even_with_old_saved_preference(self):
        from app.application.sync import Sync
        Sync(self.erp).save_preferences(self.company,'production',auto_pdf=True)
        with patch.object(Sync,'run',return_value={'import':dict(inserted=1,duplicates=2,rejected=[])} ) as run:
            self.win.sync_expenses()
        self.assertFalse(run.call_args.kwargs['download'])
        self.assertIn('σύνδεσμο',self.label(self.output))
        self.assertFalse(any(isinstance(w,ttk.Checkbutton) and 'μαζική άντληση' in str(w.cget('text')) for w in widgets(self.win)))

    def test_received_pdf_link_is_retained_and_opens_only_on_explicit_browser_action(self):
        self.win.kind_var.set('Ληφθέντα')
        self.fetch([response(receiver='000000008')],False)
        tree=self.win.records_tree
        self.assertEqual(len(tree.get_children()),1)
        tree.selection_set(tree.get_children()[0])
        button=next(w for w in widgets(self.win) if isinstance(w,ttk.Button) and w.cget('text')=='Άνοιγμα Παραστατικού')
        with patch('app.ui.aade_dialog.webbrowser.open') as browser:
            button.invoke()
        browser.assert_called_once_with('https://example.com/synthetic.pdf')
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM provider_attempts').fetchone()[0],0)
        self.assertEqual(self.erp.db.execute('SELECT count(*) FROM attachments').fetchone()[0],0)

    def test_stop_is_prominent_and_cannot_be_overwritten_by_queued_progress(self):
        pending=[]
        def worker(execute,done):
            self.owner.busy=True;pending.append(done);return True
        self.owner.run_worker=worker
        self.win.sync_expenses()
        self.assertFalse(self.win.stop_button.instate(['disabled']))
        self.win.stop_button.invoke()
        self.assertTrue(self.win.cancel_event.is_set())
        self.assertIn('Διακοπή ζητήθηκε',self.label(self.output))
        self.win.sync_expenses()
        self.assertEqual(len(pending),1)
        self.owner.busy=False
        pending[0]({'cancelled':True,'import':dict(inserted=1,duplicates=0,rejected=[])})
        self.assertIn('διακόπηκε',self.label(self.output))
        self.assertTrue(self.win.stop_button.instate(['disabled']))

    def test_closing_active_dialog_requests_stop_and_keeps_it_open_until_completion(self):
        pending=[]
        def worker(execute,done):
            self.owner.busy=True;pending.append(done);return True
        self.owner.run_worker=worker
        self.win.sync_expenses()
        self.win.tk.call(self.win.protocol('WM_DELETE_WINDOW'))
        self.assertTrue(self.win.winfo_exists())
        self.assertTrue(self.win.cancel_event.is_set())

    def test_stop_and_primary_actions_fit_minimum_dialog_in_both_themes(self):
        from app.ui.theme import apply
        for theme in ('light','dark'):
            apply(self.win,theme)
            self.win.geometry('900x630');self.win.update()
            notebook=next(w for w in widgets(self.win) if isinstance(w,ttk.Notebook))
            notebook.select(1);self.win.update()
            stop=self.win.stop_button
            self.assertTrue(stop.winfo_viewable())
            self.assertGreaterEqual(stop.winfo_width(),stop.winfo_reqwidth())
            self.assertLessEqual(stop.winfo_x()+stop.winfo_width(),stop.master.winfo_width())
            labels=[w.cget('text') for w in widgets(self.win) if isinstance(w,ttk.Button)]
            self.assertIn('Άντληση μήνα — στοιχεία και σύνδεσμοι μόνο',labels)
            self.assertIn('Λήψη PDF (χωριστή εργασία)',labels)


if __name__=='__main__':unittest.main()
