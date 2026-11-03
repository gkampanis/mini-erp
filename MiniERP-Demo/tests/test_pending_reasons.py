import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.ui.desktop import Desktop


class UndoPurchaseTests(unittest.TestCase):
    def test_unsuccessful_undo_preserves_token_and_button(self):
        owner=SimpleNamespace(company=1,_purchase_undo=(1,'SYNTHETIC',False,4),set_purchase=Mock(return_value=False),purchase_undo_button=Mock())
        Desktop.undo_purchase(owner)
        self.assertEqual(owner._purchase_undo,(1,'SYNTHETIC',False,4))
        owner.purchase_undo_button.pack_forget.assert_not_called()
    def test_successful_undo_clears_token(self):
        owner=SimpleNamespace(company=1,_purchase_undo=(1,'SYNTHETIC',False,4),set_purchase=Mock(return_value=True),purchase_undo_button=Mock())
        Desktop.undo_purchase(owner)
        self.assertIsNone(owner._purchase_undo)
    def test_busy_purchase_returns_false(self):
        self.assertIs(Desktop.set_purchase(SimpleNamespace(busy=True),'SYNTHETIC',False),False)
    def test_cancelled_undo_preserves_token(self):
        owner=SimpleNamespace(company=1,busy=False,rpa_panel=SimpleNamespace(running=False),erp=SimpleNamespace(db=Mock()),root=Mock(),
                              _purchase_undo=(1,'SYNTHETIC',True,4),purchase_undo_button=Mock())
        owner.erp.db.execute.return_value.fetchone.return_value={'name':'SYNTHETIC'}
        owner.set_purchase=lambda *args:Desktop.set_purchase(owner,*args)
        with patch('app.ui.desktop.messagebox.askyesno',return_value=False):Desktop.undo_purchase(owner)
        self.assertIsNotNone(owner._purchase_undo);owner.purchase_undo_button.pack_forget.assert_not_called()
    def test_stale_rule_undo_preserves_token(self):
        owner=SimpleNamespace(company=1,busy=False,rpa_panel=SimpleNamespace(running=False),erp=Mock(),status=Mock(),
                              _purchase_undo=(1,'SYNTHETIC',False,4),purchase_undo_button=Mock())
        owner.set_purchase=lambda *args:Desktop.set_purchase(owner,*args)
        with patch('app.application.supplier_purchases.SupplierPurchases.set',side_effect=ValueError('stale version')):Desktop.undo_purchase(owner)
        self.assertIsNotNone(owner._purchase_undo);owner.purchase_undo_button.pack_forget.assert_not_called()
    def test_reason_context_action_copies_full_text(self):
        owner=SimpleNamespace(_documents={1:dict(pending_reason='Full reason with details')},root=Mock())
        tree=Mock();tree.identify_row.return_value='1';menu=Mock()
        Desktop.pending_reason_menu(owner,SimpleNamespace(y=1),tree,menu)
        menu.add_command.call_args.kwargs['command']()
        owner.root.clipboard_append.assert_called_once_with('Full reason with details')


class PendingReasonTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE audit_events(id INTEGER PRIMARY KEY,company_id INTEGER,action TEXT,entity_id INTEGER,payload TEXT)')
        self.db.execute('CREATE TABLE rpa_jobs(id INTEGER PRIMARY KEY,company_id INTEGER,status TEXT,mode TEXT)')
        self.db.execute('CREATE TABLE rpa_items(id INTEGER PRIMARY KEY,job_id INTEGER,document_id INTEGER,status TEXT,reason TEXT,payload TEXT)')
    def event(self,action,payload,entity=None):
        self.db.execute('INSERT INTO audit_events(company_id,action,entity_id,payload) VALUES (1,?,?,?)',(action,entity,json.dumps(payload)))
    def test_existing_layout_shows_new_column_once_and_respects_later_hiding(self):
        from app.ui.pending_reasons import expose_pending_column
        preferences=Mock();preferences.layout.return_value={'visible':['name','preparation_state','pdf_state']}
        expose_pending_column(preferences)
        layout=preferences.set_layout.call_args.args[1]
        self.assertEqual(layout['visible'],['name','preparation_state','pending_reason','pdf_state'])
        layout['visible'].remove('pending_reason');preferences.layout.return_value=layout;preferences.set_layout.reset_mock()
        expose_pending_column(preferences);preferences.set_layout.assert_not_called()
    def reasons(self,rows,evidence):
        from app.ui.pending_reasons import pending_reasons
        return pending_reasons(SimpleNamespace(db=self.db),1,rows,evidence)
    def attempt(self,status='uncertain',job_status='paused',reason='Actual field error'):
        row=dict(id=1,counterparty_id=2,prepared_at='now',vat='000000001',name='SYNTHETIC',series='TEST',number='1',issue_date='2026-09-30',net_minor=10000,account_code='64.03.00.0024',nature_group='6')
        payload=dict(vat=row['vat'],name=row['name'],invoice='TEST/1',date='30/09/2026',net='100,00',account=row['account_code'],group='6')
        self.db.execute('INSERT INTO rpa_jobs VALUES (1,1,?,?)',(job_status,'fill_only'))
        self.db.execute('INSERT INTO rpa_items VALUES (1,1,1,?,?,?)',(status,reason,json.dumps(payload)))
        self.event('rpa_started',dict(job=1,item=1),1)
        return row
    def test_current_attempt_displays_actual_failure_instead_of_generic_evidence(self):
        row=self.attempt()
        self.assertEqual(self.reasons([row],{1:dict(status='review',match_kind='attempt',reason='Generic attempt')})[1],'Actual field error')
    def test_queued_creditor_pause_displays_reason_without_attempt_evidence(self):
        row=self.attempt('queued',reason='Select creditor in EBS')
        self.assertEqual(self.reasons([row],{1:dict(status='not_registered')})[1],'Select creditor in EBS')
    def test_resolved_attempt_or_changed_snapshot_does_not_show_old_error(self):
        row=self.attempt('not_saved_confirmed');evidence={1:dict(status='not_registered')}
        self.assertNotEqual(self.reasons([row],evidence)[1],'Actual field error')
        self.db.execute("UPDATE rpa_items SET status='uncertain'");row['net_minor']=10100
        self.assertNotEqual(self.reasons([row],evidence)[1],'Actual field error')
    def test_newer_related_edit_invalidates_attempt_diagnostic(self):
        row=self.attempt();self.event('account_rule_approved',dict(counterparty_id=2))
        self.assertNotEqual(self.reasons([row],{1:dict(status='review',match_kind='attempt',reason='Generic attempt')})[1],'Actual field error')
    def test_secondary_vat_account_keeps_reason_for_same_approval(self):
        row=self.attempt();payload=json.loads(self.db.execute('SELECT payload FROM rpa_items').fetchone()[0])
        payload.update(account='64.03.00.0013',approval_at=row['prepared_at'])
        self.db.execute('UPDATE rpa_items SET payload=?',(json.dumps(payload),))
        self.assertEqual(self.reasons([row],{1:dict(status='review',match_kind='attempt',reason='Generic')})[1],'Actual field error')
    def test_current_evidence_and_missing_account_take_priority(self):
        rows=[dict(id=1,prepared_at=None,suggested_account='',counterparty_id=2)]
        self.assertEqual(self.reasons(rows,{1:dict(status='review',reason='Current reconciliation')})[1],'Current reconciliation')
        self.assertIn('λογαριασμό',self.reasons(rows,{1:dict(status='not_registered')})[1])
    def test_new_eligible_plan_clears_previous_skipped_reason(self):
        rows=[dict(id=1,prepared_at='now',counterparty_id=2)]
        self.event('rpa_selection_planned',dict(documents=[],skipped=[dict(document=1,reason='Mapping missing')]))
        self.event('rpa_selection_planned',dict(documents=[1],skipped=[]))
        self.assertEqual(self.reasons(rows,{1:dict(status='not_registered')})[1],'Έτοιμο για καταχώριση')
    def test_related_account_edit_invalidates_stored_reason(self):
        rows=[dict(id=1,prepared_at='now',counterparty_id=2)]
        self.event('rpa_selection_planned',dict(documents=[],skipped=[dict(document=1,reason='Old account')]))
        self.event('account_rule_approved',dict(counterparty_id=2))
        self.assertNotEqual(self.reasons(rows,{1:dict(status='not_registered')})[1],'Old account')
    def test_unrelated_supplier_edit_does_not_erase_current_diagnostic(self):
        rows=[dict(id=1,prepared_at='now',counterparty_id=2)]
        self.event('rpa_selection_planned',dict(documents=[],skipped=[dict(document=1,reason='Mapping missing')]))
        self.event('account_rule_approved',dict(counterparty_id=99))
        self.assertEqual(self.reasons(rows,{1:dict(status='not_registered')})[1],'Mapping missing')
