"""Background allocations cannot collect discarded GUI cycles."""
import gc
import threading
import unittest
import queue
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pathlib import Path
import tempfile
from app.ui import worker_collection


class WorkerCollectionTests(unittest.TestCase):
    def test_cycles_finalize_on_main_and_gc_state_is_restored(self):
        main=threading.get_ident();finalized=[];enabled=gc.isenabled()
        worker_collection.begin()
        try:
            class Cycle:
                def __del__(self):finalized.append(threading.get_ident())
            value=Cycle();value.self=value;del value
            def allocate():
                for _ in range(20000):item=[];item.append(item)
                self.assertFalse(gc.isenabled())
            worker=threading.Thread(target=allocate);worker.start();worker.join()
            self.assertEqual(finalized,[])
        finally:worker_collection.end()
        self.assertEqual(finalized,[main]);self.assertEqual(gc.isenabled(),enabled)

    def test_overlapping_workers_do_not_restore_collection_early(self):
        enabled=gc.isenabled();worker_collection.begin();worker_collection.begin()
        worker_collection.end();self.assertFalse(gc.isenabled())
        worker_collection.end();self.assertEqual(gc.isenabled(),enabled)

    def test_previously_disabled_collection_remains_disabled(self):
        enabled=gc.isenabled();gc.disable()
        try:
            worker_collection.begin();worker_collection.end()
            self.assertFalse(gc.isenabled())
        finally:
            if enabled:gc.enable()

    def test_thread_creation_failure_restores_collection(self):
        from app.ui.desktop import Desktop
        enabled=gc.isenabled()
        owner=SimpleNamespace(busy=False,_sync_import_button=Mock(),progress=Mock(),status=Mock())
        with patch('app.ui.desktop.threading.Thread',side_effect=RuntimeError('synthetic start failure')):
            with self.assertRaises(RuntimeError):Desktop.run_worker(owner,lambda:None,Mock())
        self.assertFalse(owner.busy);self.assertEqual(gc.isenabled(),enabled)

    def test_worker_system_exit_delivers_error_and_releases_collection(self):
        from app.ui.desktop import Desktop
        enabled=gc.isenabled()
        with tempfile.TemporaryDirectory() as folder:
            owner=SimpleNamespace(busy=False,_closing=False,_sync_import_button=Mock(),progress=Mock(),status=Mock(),work=queue.Queue(),directory=Path(folder),root=Mock())
            callback=Mock()
            owner.poll=Mock()
            def stopped():raise SystemExit()
            Desktop.run_worker(owner,stopped,callback);owner._worker_thread.join()
            with patch('app.ui.desktop.messagebox.showerror') as error:Desktop.poll(owner)
            error.assert_called_once();callback.assert_not_called()
            self.assertFalse(owner.busy);self.assertEqual(gc.isenabled(),enabled)
