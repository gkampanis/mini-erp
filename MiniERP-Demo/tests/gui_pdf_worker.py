"""Actual Tk/worker regression for archived-PDF rendering; synthetic files only."""
import hashlib
from pathlib import Path
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.ui.pdf_pane import open_saved_pdf


class SavedPDFWorkerGUI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.file=Path(self.temp.name)/'synthetic.pdf';self.file.write_bytes(b'%PDF-1.4 synthetic render fixture')
        self.digest=hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.root=tk.Tk();self.addCleanup(self.root.destroy)
        self.main_thread=threading.get_ident();self.render_calls=[];self.measurements=[]
        self.workers=[]
        self.owner=SimpleNamespace(root=self.root,busy=False,run_worker=self.run_worker)
        for method in ('winfo_width','winfo_height'):
            original=getattr(tk.Canvas,method)
            def measure(canvas,original=original,method=method):
                self.assertEqual(threading.get_ident(),self.main_thread,'Tk geometry queried from PDF worker')
                value=original(canvas);self.measurements.append((method,value));return value
            guard=patch.object(tk.Canvas,method,measure);guard.start();self.addCleanup(guard.stop)
        renderer=patch('app.ui.pdf_pane.render',side_effect=self.render);renderer.start();self.addCleanup(renderer.stop)

    def run_worker(self,execute,done):
        from app.ui import worker_collection
        worker_collection.begin()
        results=[];failures=[]
        def work():
            try:results.append(execute())
            except BaseException as error:failures.append(error)
        worker=threading.Thread(target=work,name='synthetic-pdf-worker');self.workers.append(worker)
        try:worker.start();worker.join(timeout=3)
        finally:worker_collection.end()
        self.assertFalse(worker.is_alive(),'PDF worker attempted a blocking Tk operation')
        if failures:raise failures[0]
        self.assertEqual(threading.get_ident(),self.main_thread)
        done(results[0]);return True

    def render(self,path,page,width,height):
        self.assertNotEqual(threading.get_ident(),self.main_thread)
        self.render_calls.append((Path(path),page,width,height))
        return dict(ppm=b'P6\n1 1\n255\n\xff\x00\x00',pages=3)

    def test_saved_pdf_measures_canvas_on_main_thread_before_background_render(self):
        win=open_saved_pdf(self.owner,self.file,self.digest);self.root.update()
        self.assertEqual(len(self.render_calls),1)
        path,page,width,height=self.render_calls[0]
        self.assertEqual((path,page),(self.file,0))
        self.assertEqual([name for name,_ in self.measurements],['winfo_width','winfo_height'])
        self.assertEqual((width,height),tuple(max(200,value-20) for _,value in self.measurements))
        canvas=next(child for child in win.winfo_children()[0].winfo_children() if isinstance(child,tk.Canvas))
        self.assertEqual(len(canvas.find_all()),1)
        self.assertTrue(all(not worker.is_alive() for worker in self.workers))

    def test_next_page_captures_new_canvas_size_before_render_worker(self):
        win=open_saved_pdf(self.owner,self.file,self.digest);self.root.update()
        win.geometry('940x900');win.update_idletasks();self.measurements.clear()
        frame=win.winfo_children()[0]
        controls=next(child for child in frame.winfo_children() if isinstance(child,ttk.Frame))
        controls.winfo_children()[1].invoke();self.root.update()
        self.assertEqual([call[1] for call in self.render_calls],[0,1])
        self.assertEqual(self.render_calls[-1][2:],tuple(max(200,value-20) for _,value in self.measurements))
        self.assertTrue(all(not worker.is_alive() for worker in self.workers))


if __name__=='__main__':unittest.main()
