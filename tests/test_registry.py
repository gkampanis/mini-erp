"""Synthetic registry SOAP contracts; no live identities or credentials."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from app.application.service import ERP
from app.application.registry import Registry
from app.application.counterparties import Counterparties
from app.infrastructure.aade.registry import request_body,parse,lookup,SOAP,TYPES,SERVICE,WSSE
from app.infrastructure.aade.client import APIError
from app.infrastructure.importers.excel import preview
from tests.fixtures import demos
from tests.test_workspace import MemoryVault
from tests.test_workflow import Opener


def synthetic_response(vat='000000001',name='ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ'):
    return f'<s:Envelope xmlns:s="{SOAP}" xmlns:r="{TYPES}" xmlns:m="{SERVICE}"><s:Body><m:rgWsPublic2AfmMethodResponse><m:result><r:rg_ws_public2_result_rtType><r:error_rec/><r:basic_rec><r:afm>{vat}</r:afm><r:onomasia>{name}</r:onomasia><r:doy_descr>ΣΥΝΘΕΤΙΚΗ ΔΟΥ</r:doy_descr></r:basic_rec></r:rg_ws_public2_result_rtType></m:result></m:rgWsPublic2AfmMethodResponse></s:Body></s:Envelope>'.encode()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.vault=MemoryVault();self.erp=ERP(self.root/'data',self.vault)
        self.company=self.erp.company('000000008','ΣΥΝΘΕΤΙΚΗ');demos(self.root/'input');self.erp.commit_import(self.company,preview(self.root/'input/separate.xlsx'),confirmed=True)
        self.cp=Counterparties(self.erp).list(self.company,'000000001')[0]['id']
    def tearDown(self):self.erp.close();self.temp.cleanup()
    def test_soap_contract_escapes_credentials_and_calls_official_endpoint_only(self):
        root=ET.fromstring(request_body('synthetic<&','synthetic<&','000000008','000000001'))
        self.assertEqual(root.find('.//{'+WSSE+'}Username').text,'synthetic<&')
        self.assertEqual(root.find('.//{'+TYPES+'}afm_called_for').text,'000000001')
        opener=Opener([synthetic_response()]);values=lookup('synthetic','synthetic-key','000000008','000000001',opener=opener)
        self.assertEqual(values['onomasia'],'ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        self.assertEqual(opener.requests[0].full_url,'https://www1.gsis.gr/wsaade/RgWsPublic2/RgWsPublic2')
        self.assertEqual(opener.requests[0].get_method(),'POST')
    def test_mismatched_fault_and_entity_xml_are_rejected(self):
        for data in [synthetic_response('000000009'),b'<!DOCTYPE x><x/>',b'<html/>',f'<s:Envelope xmlns:s="{SOAP}"><s:Body><s:Fault/></s:Body></s:Envelope>'.encode()]:
            with self.assertRaises(APIError):parse(data,'000000001')
    def test_special_keys_are_separate_and_never_persisted_in_database(self):
        registry=Registry(self.erp);registry.save_credentials(self.company,'synthetic-reg-user','synthetic-reg-key',confirmed=True)
        self.erp.save_mydata_credentials(self.company,'production','synthetic-api-user','synthetic-api-key',confirmed=True)
        self.assertEqual(registry.read_credentials(self.company)['key'],'synthetic-reg-key')
        self.assertEqual(self.erp.mydata_credentials(self.company)['key'],'synthetic-api-key')
        dump='\n'.join(self.erp.db.iterdump())
        for value in ('synthetic-reg-user','synthetic-reg-key','synthetic-api-user','synthetic-api-key'):self.assertNotIn(value,dump)
        with patch.object(self.erp.repository,'audit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):registry.save_credentials(self.company,'replacement','replacement',confirmed=True)
        self.assertEqual(registry.read_credentials(self.company)['key'],'synthetic-reg-key')
    def test_lookup_preview_and_explicit_apply_preserve_card_code_accounts_and_raw(self):
        cards=Counterparties(self.erp);before,_=cards.detail(self.company,self.cp)
        cards.save(self.company,self.cp,before['name'],['supplier','creditor'],confirmed=True,accounts=dict(purchases_account='20.01',expenses_account='64.03',preferred_group='6'))
        raw=[tuple(x) for x in self.erp.db.execute('SELECT * FROM source_records')]
        registry=Registry(self.erp);registry.save_credentials(self.company,'synthetic','synthetic',confirmed=True)
        expected=parse(synthetic_response(),'000000001')
        previewed=registry.preview(self.company,self.cp,transport=lambda *args:expected)
        self.assertEqual(cards.detail(self.company,self.cp)[0]['name'],before['name'])
        with self.assertRaises(ValueError):registry.apply(self.company,self.cp,previewed)
        registry.apply(self.company,self.cp,previewed,confirmed=True)
        after,_=cards.detail(self.company,self.cp)
        self.assertEqual(after['code'],before['code']);self.assertEqual(after['accounts']['expenses_account'],'64.03')
        self.assertEqual(after['name'],'ΣΥΝΘΕΤΙΚΗ ΕΠΩΝΥΜΙΑ')
        self.assertEqual([tuple(x) for x in self.erp.db.execute('SELECT * FROM source_records')],raw)
