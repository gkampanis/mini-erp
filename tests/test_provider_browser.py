"""Actual Chromium with synthetic routed providers only; never a live invoice."""
import asyncio
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.infrastructure.providers.models import Client
from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader
from app.infrastructure.providers.pdf_downloads import Pending
from app.infrastructure.providers.print_fallback import print_invoice_page
from tests.test_workspace import synthetic_pdf


class ProviderBrowserTests(unittest.TestCase):
    def test_dynamic_embedded_pdf_is_archived_byte_for_byte(self):
        class Browser(BrowserPDFDownloader):
            async def _new_context(self):
                context=await super()._new_context()
                async def handler(route):
                    if route.request.url.endswith('/original.pdf'):await route.fulfill(body=synthetic_pdf(),content_type='application/pdf')
                    else:await route.fulfill(body='<html><body><iframe src="/original.pdf"></iframe></body></html>',content_type='text/html')
                await context.route('**/*',handler);return context
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        with tempfile.TemporaryDirectory() as temp,patch('app.infrastructure.providers.pdf_downloads.socket.getaddrinfo',return_value=public),patch('app.infrastructure.providers.browser_downloads.browser_launch_options',return_value=dict(headless=True)):
            backend=Browser(None,headless=True,timeout=5)
            row=dict(mark=10000001,issue_date='2026-10-21',download_url='https://example.com/invoice')
            with backend.session():artifact=backend._download(Client('synthetic','ΣΥΝΘΕΤΙΚΗ','000000000','production'),row,Path(temp),threading.Event())
            self.assertEqual(artifact[0].read_bytes(),synthetic_pdf())
            self.assertEqual(artifact[0].relative_to(temp).as_posix(),'000000000/2026-10/10000001.pdf')

    def test_real_print_pipeline_distinguishes_html_copy_and_rejects_challenge(self):
        async def check(folder):
            from playwright.async_api import async_playwright
            from app.infrastructure.providers.browser_downloads import browser_launch_choices
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True,**browser_launch_choices()[0]);page=await browser.new_page()
                client=Client('synthetic','ΣΥΝΘΕΤΙΚΗ','000000000','production')
                row=dict(mark=10000001,issue_date='2026-10-21',issuer_vat='000000001',recipient_vat='000000000',series='TEST',number='100',download_url='https://example.com/invoice')
                await page.set_content('<html><title>Synthetic Invoice</title><body><h1>Invoice TEST 100</h1><p>Issuer 000000001 Recipient 000000000</p><p>2026-10-21 Total 0.12</p><p>Synthetic goods and services supplied for offline browser verification only.</p></body></html>')
                artifact=await print_invoice_page(page,client,row,folder,threading.Event())
                self.assertEqual(artifact.state,'printed_unverified');self.assertTrue(artifact.path.is_file())
                await page.set_content('<html><title>Just a moment</title><body>Verify you are human</body></html>')
                with self.assertRaises(Pending):await print_invoice_page(page,client,row,folder,threading.Event())
                await browser.close()
        with tempfile.TemporaryDirectory() as temp:asyncio.run(check(Path(temp)))
