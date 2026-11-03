"""A test document cannot become live by omitting a source hint."""
import tempfile
import unittest
from pathlib import Path
from app.application.service import ERP
from app.application.mydata import MyData
from app.application.rpa import RPA
from app.infrastructure.importers.excel import preview
from app.infrastructure.aade.client import parsed_page
from tests.fixtures import workbook,HEADERS,ROW
from tests.test_workflow import response


class LiveEnvironmentTests(unittest.TestCase):
    def test_excel_in_test_workspace_never_enters_production(self):
        with tempfile.TemporaryDirectory() as directory:
            erp=ERP(Path(directory)/'data')
            try:
                company=erp.company('000000000','SYNTHETIC')
                with erp.db:erp.db.execute("INSERT INTO aade_settings(company_id,environment) VALUES (?,'test')",(company,))
                path=Path(directory)/'synthetic.xlsx';workbook(path,[HEADERS,ROW])
                self.assertEqual(erp.commit_import(company,preview(path),confirmed=True)['inserted'],1)
                self.assertEqual(erp.search(company),[])
                self.assertEqual(len(erp.search(company,environment='test')),1)
            finally:erp.close()

    def test_test_card_mapping_does_not_leak_to_live_display_or_registry_batch(self):
        from app.application.supplier_accounts import SupplierAccounts
        from app.application.registry import Registry
        from tests.test_workspace import MemoryVault
        from tests.test_supplier_purchases import synthetic_vat
        with tempfile.TemporaryDirectory() as directory:
            erp=ERP(Path(directory)/'data',MemoryVault())
            try:
                company=erp.company('000000008','SYNTHETIC');vat=synthetic_vat()
                with erp.db:
                    test=erp.db.execute("INSERT INTO counterparties(company_id,environment,vat,name) VALUES (?,'test',?,'')",(company,vat)).lastrowid
                    live=erp.db.execute("INSERT INTO counterparties(company_id,vat,name) VALUES (?,?,'')",(company,vat)).lastrowid
                accounts=SupplierAccounts(erp)
                from app.application.account_defaults import defaults_values
                with erp.db:accounts.write(company,test,defaults_values('','64.99','6'))
                self.assertEqual(accounts.display_accounts(company),{})
                registry=Registry(erp);registry.save_credentials(company,'synthetic','synthetic',confirmed=True)
                calls=[]
                def transport(*args):
                    calls.append(args[-1]);return dict(afm=vat,onomasia='LIVE NAME')
                result=registry.fill_missing(company,transport=transport)
                self.assertEqual(result['filled'],1);self.assertEqual(calls,[vat])
                self.assertEqual(erp.db.execute('SELECT name FROM counterparties WHERE id=?',(live,)).fetchone()[0],'LIVE NAME')
                self.assertEqual(erp.db.execute('SELECT name FROM counterparties WHERE id=?',(test,)).fetchone()[0],'')
                with erp.db:erp.db.execute("INSERT INTO aade_settings(company_id,environment) VALUES (?,'test')",(company,))
                self.assertEqual(registry.fill_missing(company,transport=transport)['filled'],1)
                self.assertEqual(erp.db.execute('SELECT name FROM counterparties WHERE id=?',(live,)).fetchone()[0],'LIVE NAME')
            finally:erp.close()

    def test_explicit_test_namespace_cannot_bypass_live_guard_without_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            erp=ERP(Path(directory)/'data')
            try:
                company=erp.company('000000000','SYNTHETIC')
                path=Path(directory)/'synthetic.xlsx';workbook(path,[HEADERS,ROW]);packet=preview(path)
                erp.repository.persist_import(company,packet,packet,environment='test')
                document=erp.search(company,environment='test')[0]['id']
                with self.assertRaisesRegex(ValueError,'δοκιμαστικ'):
                    RPA(erp).live_source(company,document)
            finally:erp.close()

    def test_mydata_test_first_then_live_keeps_distinct_cards_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            erp=ERP(Path(directory)/'data')
            try:
                company=erp.company('000000000','SYNTHETIC');service=MyData(erp)
                dates=('2026-10-01','2026-10-31');xml=response()
                for env in ('test','production'):
                    service.persist(company,env,*dates,[(xml,parsed_page(xml))])
                    result=service.import_documents(company,env,*dates,confirmed=True)
                    self.assertEqual(result['inserted'],1)
                test=erp.search(company,environment='test')[0];live=erp.search(company)[0]
                self.assertNotEqual(test['id'],live['id'])
                self.assertNotEqual(test['counterparty_id'],live['counterparty_id'])
                from app.application.supplier_accounts import SupplierAccounts
                report=SupplierAccounts(erp).save(company,[test['counterparty_id']],'6','64.99',confirmed=True)
                self.assertEqual(report['updated'],1)
                self.assertEqual(erp.preparation(company,test['id'])['account_code'],'64.99')
                self.assertIsNone(erp.preparation(company,live['id']))
                RPA(erp).live_source(company,live['id'])
                with self.assertRaises(ValueError):RPA(erp).live_source(company,test['id'])
            finally:erp.close()
