"""Synthetic P9 financial scope and supplier-group consistency regressions."""
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from app.application.counterparties import Counterparties
from app.application.ebs_reconciliation import EBSReconciliation
from app.application.mydata import MyData
from app.application.rpa import RPA
from app.application.service import ERP
from app.application.supplier_accounts import SupplierAccounts
from app.application.workspace import Workspace
from app.domain.invoice_types import classify
from app.infrastructure.aade.client import parsed_page
from app.infrastructure.importers.excel import preview
from tests import test_supplier_purchases as fixtures
from tests.fixtures import HEADERS,ROW,workbook,reconcile_empty
from tests.test_ods import ods
from tests.test_workflow import response


class P9ClassificationTests(unittest.TestCase):
    setUp=fixtures.PurchaseTests.setUp
    tearDown=fixtures.PurchaseTests.tearDown
    add=fixtures.PurchaseTests.add

    def save_card(self,group,*,expense='64.03',purchase='20.01',apply_pending=True):
        service=Counterparties(self.erp);cp=self.erp.search(self.company)[0]['counterparty_id']
        card,_=service.detail(self.company,cp)
        return service.save(self.company,cp,card['name'],['supplier'],confirmed=True,
                            accounts=dict(purchases_account=purchase,expenses_account=expense,preferred_group=group),
                            apply_pending=apply_pending)

    def receive(self,code,mark,*,zero=False,credit=False,delivery=False):
        raw=response(mark=mark,number=mark,issuer=self.supplier)
        raw=raw.replace(b'<invoiceType>1.1</invoiceType>',f'<invoiceType>{code}</invoiceType><isDeliveryNote>{str(delivery).lower()}</isDeliveryNote>'.encode())
        if zero:raw=raw.replace(b'0.10',b'0.00').replace(b'0.02',b'0.00').replace(b'0.12',b'0.00')
        elif credit:raw=raw.replace(b'0.10',b'-0.10').replace(b'0.02',b'-0.02').replace(b'0.12',b'-0.12')
        api=MyData(self.erp)
        api.persist(self.company,'production','2026-10-01','2026-10-31',[(raw,parsed_page(raw))])
        api.import_incoming(self.company,'production','2026-10-01','2026-10-31',confirmed=True)
        return next(r for r in Workspace(self.erp).rows(self.company) if r['mark']==mark)

    def test_known_nonfinancial_type_is_distinct_from_unknown_and_other_value_types(self):
        for code,expected in [('8.6',False),('9.3',False),('10.1',False),('16.1',True),('5.1',True),('1.1',True),('99.99',None)]:
            with self.subTest(code=code):self.assertIs(classify(code,True).get('financial'),expected)

    def test_purchase_rule_excludes_known_orders_without_a_positive_amount_heuristic(self):
        before=self.receive('8.6','89000001',zero=True)
        self.service.set(self.company,self.supplier,True)
        self.assertFalse(next(r for r in Workspace(self.erp).rows(self.company) if r['id']==before['id'])['purchase_classified'])
        self.assertFalse(self.receive('8.6','89000002')['purchase_classified'])
        rent=self.receive('16.1','89000003',zero=True)
        credit=self.receive('5.1','89000004',credit=True)
        delivery=self.receive('1.1','89000005',delivery=True)
        self.assertTrue(rent['purchase_classified']);self.assertTrue(credit['purchase_classified'])
        self.assertEqual(credit['gross_minor'],-12)
        self.assertTrue(delivery['purchase_classified']);self.assertTrue(delivery['is_delivery_note'])
        self.assertEqual(delivery['family'],'invoice')
        self.assertFalse(self.receive('99.99','89000006')['purchase_classified'])

    def test_workspace_uses_inferred_expense_group_on_future_import_without_approval(self):
        self.save_card(None,purchase='')
        document=self.add('3','2026-11-21')
        row=next(r for r in Workspace(self.erp).rows(self.company) if r['id']==document)
        self.assertEqual((row['suggested_group'],row['suggested_account']),('6','64.03'))
        self.assertIsNone(self.erp.preparation(self.company,document))
        self.assertEqual(SupplierAccounts(self.erp).rows(self.company)[0]['group'],'6')

    def test_group2_defaults_do_not_classify_nonfinancial_or_unknown_documents_as_purchases(self):
        self.save_card('6')
        self.receive('8.6','89000021',zero=True);self.receive('99.99','89000022')
        self.save_card('2')
        rows={r['mark']:r for r in Workspace(self.erp).rows(self.company)}
        self.assertFalse(rows['89000021']['is_purchase'])
        self.assertFalse(rows['89000022']['is_purchase'])
        self.assertTrue(rows['70000001']['is_purchase'])

    def test_explicit_card_purchase_change_overrides_pending_approvals_across_months_and_imports(self):
        self.save_card('6')
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')]
        card=self.save_card('2')
        self.assertTrue(self.service.inspect(self.company,self.supplier)['enabled'])
        self.assertEqual(card['purchase_update']['changed'],2)
        self.assertTrue(all(r['purchase_classified'] for r in Workspace(self.erp).rows(self.company)))
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.other)))
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')],before)
        self.add('3','2026-11-21')
        values=list(ROW);values[0]=self.supplier;values[3]='4';values[4]='2026-12-21';values[8]='70000004'
        content=''.join('<table:table-row>'+''.join('<table:table-cell office:value-type="string"><text:p>'+escape(str(v))+'</text:p></table:table-cell>' for v in cells)+'</table:table-row>' for cells in (HEADERS,values))
        path=self.root/'future.ods';ods(path,content)
        self.erp.commit_import(self.company,preview(path),confirmed=True)
        self.assertTrue(self.receive('1.1','89000010')['purchase_classified'])
        again=ERP(self.erp.directory)
        try:self.assertTrue(all(r['purchase_classified'] for r in Workspace(again).rows(self.company)))
        finally:again.close()

    def test_card_account_edit_keeps_purchase_rule_and_explicit_group6_change_removes_it(self):
        self.save_card('6');self.save_card('2')
        self.assertTrue(self.service.inspect(self.company,self.supplier)['enabled'])
        version=self.service.inspect(self.company,self.supplier)['version']
        self.save_card('2',purchase='20.09')
        self.assertEqual(self.service.inspect(self.company,self.supplier)['version'],version)
        self.save_card('6',expense='64.09')
        self.assertFalse(self.service.inspect(self.company,self.supplier)['enabled'])
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))
        self.assertTrue(all(r['account_code']=='64.09' for r in self.erp.search(self.company)))

    def test_saving_explicit_group2_repairs_legacy_default_without_rewriting_approvals(self):
        self.save_card('6');cp=self.erp.search(self.company)[0]['counterparty_id']
        with self.erp.db:
            SupplierAccounts(self.erp).write(self.company,cp,dict(purchases_account='20.01',expenses_account='64.03',preferred_group='2'))
        self.assertFalse(self.service.inspect(self.company,self.supplier)['enabled'])
        before=[tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')]
        for disabled_rule in (False,True):
            with self.subTest(disabled_rule=disabled_rule):
                if disabled_rule:self.service.set(self.company,self.supplier,False)
                self.save_card('2')
                self.assertTrue(self.service.inspect(self.company,self.supplier)['enabled'])
                self.assertTrue(all(r['purchase_classified'] for r in Workspace(self.erp).rows(self.company)))
                self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')],before)

    def test_same_group2_enabled_rule_does_not_reclassify_a_previously_protected_queue(self):
        self.save_card('6');document=self.erp.search(self.company)[0]['id'];rpa=RPA(self.erp)
        job=rpa.create(self.company,[document],confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(job,))
        self.save_card('2')
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='paused' WHERE id=?",(job,))
        version=self.service.inspect(self.company,self.supplier)['version']
        attempts=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        self.save_card('2',purchase='20.09')
        self.assertEqual(self.service.inspect(self.company,self.supplier)['version'],version)
        self.assertFalse(next(r for r in Workspace(self.erp).rows(self.company) if r['id']==document)['purchase_classified'])
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],attempts)

    def test_ordinary_expense_account_edit_does_not_undo_independent_purchase_rule(self):
        self.save_card('6');self.service.set(self.company,self.supplier,True)
        self.save_card('6',expense='64.09')
        self.assertTrue(all(r['purchase_classified'] for r in Workspace(self.erp).rows(self.company)))
        self.assertTrue(self.service.inspect(self.company,self.supplier)['enabled'])

    def test_supplier_mapping_group_change_uses_existing_purchase_rule_and_can_reverse_it(self):
        cp=self.erp.search(self.company)[0]['counterparty_id'];accounts=SupplierAccounts(self.erp)
        accounts.save(self.company,[cp],'6','64.03',confirmed=True)
        accounts.save(self.company,[cp],'2','20.01',confirmed=True)
        self.assertTrue(all(r['purchase_classified'] for r in Workspace(self.erp).rows(self.company)))
        accounts.save(self.company,[cp],'6','64.09',confirmed=True)
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))

    def test_card_group_change_reports_protected_records_and_preserves_preparations_and_attempts(self):
        self.save_card('6');ids=[r['id'] for r in self.erp.search(self.company)]
        ids.extend(self.add(str(i),'2026-11-21') for i in (3,4,5))
        for document in ids:self.erp.prepare_document(self.company,document,'6','64.03',confirmed=True)
        reconcile_empty(self.erp,self.company)
        EBSReconciliation(self.erp).confirm_manual(self.company,ids[0],'Synthetic registered',confirmed=True)
        rpa=RPA(self.erp);active=rpa.create(self.company,[ids[1]],confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_jobs SET status='running' WHERE id=?",(active,))
        complete=rpa.create(self.company,[ids[2]],confirmed=True);rpa.advance(self.company,complete)
        real=rpa.create(self.company,[ids[3]],mode='fill_only',confirmed=True)
        with self.erp.db:self.erp.db.execute("UPDATE rpa_items SET status='save_pending' WHERE job_id=?",(real,))
        preparations=[tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')]
        attempts=[tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')]
        try:card=self.save_card('2',expense='64.09')
        except ValueError as exc:self.fail('Explicit purchase classification must preserve active attempts: '+str(exc))
        self.assertEqual(card['purchase_update']['changed'],1)
        self.assertEqual({r['document'] for r in card['purchase_update']['exceptions']},set(ids[:4]))
        self.assertEqual(set(card['pending_update']['protected']),set(ids[:4]))
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM document_preparations')],preparations)
        self.assertEqual([tuple(r) for r in self.erp.db.execute('SELECT * FROM rpa_items')],attempts)

    def test_unprepared_registered_exception_is_not_moved_by_purchase_account_defaults(self):
        self.save_card('6',apply_pending=False);document=self.erp.search(self.company)[0]['id']
        EBSReconciliation(self.erp).confirm_manual(self.company,document,'Synthetic registered',confirmed=True)
        self.save_card('2')
        row=next(r for r in Workspace(self.erp).rows(self.company) if r['id']==document)
        self.assertFalse(row['purchase_classified']);self.assertFalse(row['is_purchase'])
        self.assertIsNone(self.erp.preparation(self.company,document))

    def test_card_and_purchase_rule_rollback_together_after_late_audit_failure(self):
        self.save_card('6');before=list(self.erp.db.iterdump());audit=self.erp.repository.audit;enabled=[]
        def fail_card(*args,**kwargs):
            if args[1]=='counterparty_card_updated':
                enabled.append(self.service.inspect(self.company,self.supplier)['enabled'])
                raise RuntimeError('Synthetic card audit failure')
            return audit(*args,**kwargs)
        with patch.object(self.erp.repository,'audit',side_effect=fail_card):
            with self.assertRaises(RuntimeError):self.save_card('2')
        self.assertEqual(enabled,[True])
        self.assertEqual(list(self.erp.db.iterdump()),before)

    def test_restore_after_explicit_card_purchase_change_reuses_previous_group_and_accounts(self):
        self.save_card('6');self.save_card('2')
        self.assertEqual(self.service.inspect(self.company,self.supplier)['previous_group'],'6')
        self.service.restore(self.company,self.supplier)
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))
        cp=self.erp.search(self.company)[0]['counterparty_id']
        values=Counterparties(self.erp).detail(self.company,cp)[0]['accounts']
        self.assertEqual((values['preferred_group'],values['purchases_account'],values['expenses_account']),('6','20.01','64.03'))

    def test_test_card_group_change_does_not_classify_same_vat_production_documents(self):
        path=self.root/'test.xlsx';values=list(ROW);values[0]=self.supplier;values[8]='80000001'
        workbook(path,[HEADERS,values]);item=preview(path)
        self.erp.repository.persist_import(self.company,item,item,environment='test')
        service=Counterparties(self.erp);card=service.list(self.company,environment='test')[0]
        service.save(self.company,card['id'],card['name'],['supplier'],confirmed=True,
                     accounts=dict(purchases_account='20.01',expenses_account='',preferred_group='2'))
        self.assertFalse(self.service.inspect(self.company,self.supplier)['enabled'])
        self.assertFalse(any(r['is_purchase'] for r in Workspace(self.erp).rows(self.company)))
