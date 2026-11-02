"""Isolated optional process; reuses the ERP's PDF validation and database adapter."""
import hashlib
import json
from pathlib import Path
import sys
from app.application.service import ERP
from app.application.provider_pdf import ProviderDatabase
from app.infrastructure.providers.browser_downloads import BrowserPDFDownloader
from app.infrastructure.providers.models import Client

class Cancel:
    def __init__(self,path):self.path=Path(path)
    def is_set(self):return self.path.exists()

class CamoufoxPDFDownloader(BrowserPDFDownloader):
    def __init__(self,db,binary,profile):
        super().__init__(db,headless=False,allow_print=False,timeout=120)
        self.binary=binary;self.profile=profile
    def _candidates(self,client_id,dates=None):return self.db.failed_download_candidates(client_id,dates)
    async def _start(self):
        from playwright.async_api import async_playwright
        from camoufox.async_api import AsyncNewBrowser
        from camoufox.addons import DefaultAddons
        self.playwright=await async_playwright().start()
        self.context=await AsyncNewBrowser(self.playwright,persistent_context=True,user_data_dir=str(self.profile),executable_path=self.binary,headless=False,geoip=False,exclude_addons=list(DefaultAddons),accept_downloads=True)
        self.browser=self.context.browser

def execute(data):
    erp=ERP(data['directory'])
    try:
        owner=erp.db.execute('SELECT vat,name FROM companies WHERE id=?',(data['company'],)).fetchone()
        if owner is None:raise ValueError('Δεν βρέθηκε εταιρεία')
        adapter=ProviderDatabase(erp,data['company'],data['environment'],data['marks'])
        profile=erp.directory/'provider-browser'/'camoufox'/hashlib.sha256(f"{data['company']}|{data['environment']}".encode()).hexdigest()
        profile.mkdir(parents=True,exist_ok=True,mode=0o700)
        backend=CamoufoxPDFDownloader(adapter,data['binary'],profile)
        client=Client(str(data['company']),owner['name'],owner['vat'],'production' if data['environment']=='production' else 'development')
        cancel=Cancel(data['cancel'])
        for row in adapter.download_candidates(str(data['company'])):adapter.link_cached(row['mark'])
        if not backend._candidates(client.id) or cancel.is_set():
            from app.infrastructure.providers.pdf_downloads import PDFDownloader
            return PDFDownloader.run(backend,client,Path(data['destination']),cancel)
        return backend.run(client,Path(data['destination']),cancel)
    finally:erp.close()

def main():
    request=Path(sys.argv[1]);data=json.loads(request.read_text())
    try:result=dict(result=execute(data))
    except Exception as error:
        from app.infrastructure.crashlog import record
        record(data['directory'],error,'camoufox');result=dict(error=True)
    Path(data['response']).write_text(json.dumps(result))
if __name__=='__main__':main()
