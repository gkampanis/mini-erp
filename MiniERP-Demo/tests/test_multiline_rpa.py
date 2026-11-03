from copy import deepcopy
import unittest
from app.infrastructure.ebs_adapter.adapter import FIELDS,SimulationAdapter
from app.application.workspace import validate_profile
from app.application.rpa import RPA
from tests import test_vat_lines as fixtures


class Driver:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    def validate_target(self,field,point):self.calls.append(('validate',field,tuple(point)));return point
    def ensure_account_focus(self,point,net,previous):
        self.calls.append(('account_focus',tuple(point)))
        if self.fail=='second_account':raise RuntimeError('synthetic account focus')
    def __getattr__(self,name):return lambda *args,**kwargs:self.calls.append((name,*args))


class MultilineAdapterTests(unittest.TestCase):
    def mapping(self):return {**{field:(10+i*30,100) for i,(field,_) in enumerate(FIELDS)},'EXPENSE_ACCOUNT_GRID_CELL_2':(100,130),'NET_AMOUNT_GRID_CELL_2':(130,130)}
    def payload(self):return dict(vat='000000001',invoice='TEST/1',date='30/09/2026',account='64.03.0024',net='2132,38',detail_lines=[dict(account='64.03.0024',net='126,38',net_minor=12638,tax_minor=3033),dict(account='64.03.0000',net='2006,00',net_minor=200600,tax_minor=0)])
    def fill(self,driver,payload,mapping):
        from app.infrastructure.ebs_adapter.adapter import fill_multiline_sequence
        return fill_multiline_sequence(driver,payload,mapping)
    def test_header_once_and_each_exact_row_uses_its_own_focus_and_position(self):
        driver=Driver();self.fill(driver,self.payload(),self.mapping())
        writes=[c[1] for c in driver.calls if c[0]=='write']
        self.assertEqual(writes,['000000001','TEST/1','30092026','64.03.0024','126,38','64.03.0000','2006,00'])
        self.assertIn(('account_focus',(100,130)),driver.calls)
        self.assertIn(('require_net_focus',(130,130),(130,100)),driver.calls)
    def test_missing_or_overlapping_second_row_mapping_fails_before_any_input(self):
        for mapping in ({f:(10+i*30,100) for i,(f,_) in enumerate(FIELDS)},{**self.mapping(),'EXPENSE_ACCOUNT_GRID_CELL_2':(100,100)}):
            driver=Driver()
            with self.assertRaises(ValueError):self.fill(driver,self.payload(),mapping)
            self.assertFalse(any(c[0] in ('write','click','hotkey','press') for c in driver.calls))
    def test_second_account_focus_failure_does_not_type_second_account_or_amount(self):
        driver=Driver('second_account')
        with self.assertRaises(RuntimeError):self.fill(driver,self.payload(),self.mapping())
        self.assertNotIn(('write','64.03.0000'),driver.calls);self.assertFalse(any(c[0]=='write' and c[1]=='2006,00' for c in driver.calls))
    def test_simulation_checks_exact_line_sum_and_control_characters(self):
        SimulationAdapter().fill(self.payload(),self.mapping())
        for change in ('sum','unsafe','minor'):
            value=self.payload()
            if change=='sum':value['detail_lines'][1]['net']='2005,00'
            elif change=='unsafe':value['detail_lines'][1]['account']='64\t03'
            else:value['detail_lines'][1]['net_minor']=200599
            with self.assertRaises(ValueError):SimulationAdapter().fill(value,self.mapping())
    def test_old_profile_and_explicit_additional_row_are_supported_without_row_guessing(self):
        mapping=self.mapping();old={k:v for k,v in mapping.items() if k in {f for f,_ in FIELDS}}
        for m in (old,mapping):self.assertEqual(validate_profile(dict(mapping=m,save=(1,2),new=(3,4)))['mapping'],{k:list(v) for k,v in m.items()})
        mapping.pop('NET_AMOUNT_GRID_CELL_2')
        with self.assertRaises(ValueError):validate_profile(dict(mapping=mapping,save=(1,2),new=(3,4)))


class MultilinePayloadTests(unittest.TestCase):
    setUp=fixtures.VATLineTests.setUp
    tearDown=fixtures.VATLineTests.tearDown
    service=fixtures.VATLineTests.service
    rules=fixtures.VATLineTests.rules
    add_single_vat_document=fixtures.VATLineTests.add_single_vat_document
    def test_payload_contains_explicit_source_rows_and_rule_edit_updates_fresh_payload(self):
        service=self.service();service.save_rules(self.company,self.cp,self.rules(),confirmed=True)
        payload=RPA(self.erp).payload(self.company,self.document)
        self.assertEqual([r['net'] for r in payload['detail_lines']],['126,38','2006,00'])
        self.assertEqual(payload['net'],'2132,38')
        rules=self.rules();rules[1]['account']='64.09.0000';service.save_rules(self.company,self.cp,rules,confirmed=True)
        self.assertNotEqual(RPA(self.erp).payload(self.company,self.document),payload)

    def native_job(self,two=False):
        from app.application.workspace import Workspace
        from tests.fixtures import reconcile_empty
        from app.application.mydata import MyData
        from app.infrastructure.aade.client import parsed_page
        from tests.test_mydata_lines import invoice
        import xml.etree.ElementTree as ET
        ids=[self.document]
        if two:
            node=invoice();node.find('{*}mark').text='100002';node.find('{*}invoiceHeader/{*}aa').text='2'
            root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);data=ET.tostring(root)
            api=MyData(self.erp);api.persist(self.company,'production','2026-09-30','2026-09-30',[(data,parsed_page(data))]);api.import_incoming(self.company,'production','2026-09-30','2026-09-30',confirmed=True)
            second=next(r['id'] for r in self.erp.search(self.company) if r['id']!=self.document)
            self.erp.prepare_document(self.company,second,'6','64.03.00.0024',confirmed=True);ids.append(second)
        reconcile_empty(self.erp,self.company)
        mapping=MultilineAdapterTests().mapping();profile=dict(mapping=mapping,save=[5,10],new=[15,20])
        Workspace(self.erp).save_profile(self.company,profile)
        self.service().save_rules(self.company,self.cp,self.rules(),confirmed=True)
        return RPA(self.erp).create(self.company,ids,mode='fill_only',execution='save_new',pilot=True,confirmed=True)

    def backend(self,fail=None):
        class Backend(Driver):
            def __init__(self):super().__init__(fail);self.handle=100
            def prepare(self,profile,expected):self.calls.append(('prepare',expected));return self.handle
            def fill(self,payload,mapping):
                from app.infrastructure.ebs_adapter.adapter import fill_multiline_sequence,fill_sequence
                (fill_multiline_sequence if payload.get('detail_lines') else fill_sequence)(self,payload,mapping)
            def save(self,point):self.calls.append(('save',tuple(point)))
            def open_new(self,point):self.calls.append(('new',tuple(point)));self.handle+=1;return self.handle
        return Backend()

    def test_two_multiline_invoices_save_once_each_and_open_new_only_between_invoices(self):
        job=self.native_job(two=True);backend=self.backend();rpa=RPA(self.erp)
        first=rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(first['status'],'running');self.assertEqual(sum(c[0]=='save' for c in backend.calls),1);self.assertEqual(sum(c[0]=='new' for c in backend.calls),1)
        last=rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(last['status'],'completed');self.assertEqual(sum(c[0]=='save' for c in backend.calls),2);self.assertEqual(sum(c[0]=='new' for c in backend.calls),1)

    def test_row_two_focus_failure_keeps_invoice_pending_and_never_sends_save(self):
        job=self.native_job();backend=self.backend('second_account')
        result=RPA(self.erp).advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(result['item_status'],'uncertain');self.assertEqual(result['issue_phase'],'fill')
        self.assertFalse(any(c[0]=='save' for c in backend.calls));self.assertFalse(result['save_may_have_been_sent'])

    def test_source_corruption_after_queue_stops_before_backend_input(self):
        job=self.native_job();backend=self.backend()
        page=self.erp.db.execute('SELECT storage_path FROM mydata_pages').fetchone()[0];(self.erp.directory/page).write_bytes(b'<RequestedDoc/>')
        with self.assertRaises(ValueError):RPA(self.erp).advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(backend.calls,[])

    def test_refreshed_pdf_url_does_not_block_unchanged_queued_finances(self):
        import xml.etree.ElementTree as ET
        from tests.test_mydata_lines import invoice
        from app.infrastructure.aade.client import parsed_page
        job=self.native_job();backend=self.backend()
        node=invoice();ET.SubElement(node,'downloadingInvoiceUrl').text='https://example.com/refreshed-synthetic.pdf'
        root=ET.Element('RequestedDoc');ET.SubElement(root,'invoicesDoc').append(node);xml=ET.tostring(root)
        self.api.persist(self.company,'production','2026-09-30','2026-09-30',[(xml,parsed_page(xml))])
        self.assertEqual(RPA(self.erp).advance(self.company,job,live_confirmed=True,adapter=backend)['status'],'completed')
        self.assertEqual(sum(c[0]=='save' for c in backend.calls),1)

    def test_later_secondary_only_invoice_uses_original_mapping_and_one_save(self):
        from app.application.workspace import Workspace
        from tests.fixtures import reconcile_empty
        self.service().save_rules(self.company,self.cp,self.rules(),confirmed=True)
        doc=self.add_single_vat_document();reconcile_empty(self.erp,self.company)
        old={f:[10+30*i,100] for i,(f,_) in enumerate(FIELDS)}
        Workspace(self.erp).save_profile(self.company,dict(mapping=old,save=[5,10],new=[15,20]))
        rpa=RPA(self.erp);job=rpa.create(self.company,[doc],mode='fill_only',execution='save_new',pilot=True,confirmed=True)
        backend=self.backend();result=rpa.advance(self.company,job,live_confirmed=True,adapter=backend)
        self.assertEqual(result['status'],'completed')
        self.assertIn(('write','64.03.00.0000'),backend.calls)
        self.assertNotIn(('write','64.03.00.0024'),backend.calls)
        self.assertEqual(sum(c[0]=='save' for c in backend.calls),1);self.assertFalse(any(c[0]=='new' for c in backend.calls))


if __name__=='__main__':unittest.main(verbosity=2)
