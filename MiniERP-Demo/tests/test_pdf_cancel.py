import asyncio
import threading
import unittest
from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader


class BrowserCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_interrupts_waiting_navigation_and_finishes_cleanup(self):
        closed=[]
        class Hanging(BrowserPDFDownloader):
            async def _capture(self,*args):
                try:await asyncio.Event().wait()
                finally:closed.append(True)
        backend=Hanging(None);cancel=threading.Event()
        asyncio.get_running_loop().call_later(.03,cancel.set)
        result=await asyncio.wait_for(backend._capture_until_cancelled(None,None,None,cancel),timeout=1)
        self.assertIsNone(result);self.assertEqual(closed,[True])

    async def test_already_cancelled_does_not_open_another_document(self):
        class Never(BrowserPDFDownloader):
            async def _capture(self,*args):raise AssertionError('Must not open another document')
        cancel=threading.Event();cancel.set()
        self.assertIsNone(await Never(None)._capture_until_cancelled(None,None,None,cancel))
