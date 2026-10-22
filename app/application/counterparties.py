"""Stable company+VAT cards; roles never infer an invoice accounting account."""
class Counterparties:
    def __init__(self,erp):self.erp=erp;self.db=erp.db

    def list(self,company,query=''):
        rows=self.db.execute('SELECT c.*,count(d.id) AS document_count FROM counterparties c LEFT JOIN documents d ON d.counterparty_id=c.id AND d.company_id=c.company_id WHERE c.company_id=? GROUP BY c.id ORDER BY c.name,c.vat',(company,)).fetchall()
        result=[]
        for row in rows:
            card=dict(row);card['roles']=[r[0] for r in self.db.execute('SELECT role FROM counterparty_roles WHERE counterparty_id=? ORDER BY role',(row['id'],))]
            groups={r[0] for r in self.db.execute('SELECT DISTINCT p.nature_group FROM document_preparations p JOIN documents d ON d.id=p.document_id AND d.company_id=p.company_id WHERE p.company_id=? AND d.counterparty_id=?',(company,card['id']))}
            default=self.db.execute('SELECT preferred_group FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,card['id'])).fetchone()
            if default and default[0]:groups.add(default[0])
            card['transaction_scope']='Αγορές (2) · εκτός EBS' if groups=={'2'} else 'Έξοδα (6) → EBS' if groups=={'6'} else 'Αγορές και έξοδα (2/6)' if groups=={'2','6'} else 'Χρειάζεται διαχωρισμό'
            if not query or any(query.casefold() in str(card[k]).casefold() for k in ('code','vat','name')):result.append(card)
        return result

    def detail(self,company,counterparty):
        row=self.db.execute('SELECT * FROM counterparties WHERE id=? AND company_id=?',(counterparty,company)).fetchone()
        if row is None:raise ValueError('Δεν βρέθηκε καρτέλα σε αυτή την εταιρεία')
        card=dict(row);card['roles']=[r[0] for r in self.db.execute('SELECT role FROM counterparty_roles WHERE counterparty_id=? ORDER BY role',(counterparty,))]
        account_row=self.db.execute('SELECT * FROM counterparty_accounts WHERE company_id=? AND counterparty_id=?',(company,counterparty)).fetchone()
        card['accounts']=dict(account_row) if account_row else dict(purchases_account='',expenses_account='',preferred_group=None)
        documents=[r for r in self.erp.search(company) if r['counterparty_id']==counterparty]
        return card,documents

    def save(self,company,counterparty,name,roles,confirmed=False,accounts=None):
        if confirmed is not True:raise ValueError('Απαιτείται επιβεβαίωση καρτέλας')
        if not isinstance(name,str) or not name.strip() or len(name.strip())>256:raise ValueError('Χρειάζεται επωνυμία έως 256 χαρακτήρες')
        roles=set(roles)
        if not roles or not roles<={'supplier','creditor','customer'}:raise ValueError('Επίλεξε τουλάχιστον έναν έγκυρο ρόλο')
        from app.application.account_defaults import defaults_values
        values=None if accounts is None else defaults_values(accounts.get('purchases_account',''),accounts.get('expenses_account',''),accounts.get('preferred_group'))
        before,_=self.detail(company,counterparty)
        with self.db:
            self.db.execute('UPDATE counterparties SET name=? WHERE company_id=? AND id=?',(name.strip(),company,counterparty))
            self.db.execute('DELETE FROM counterparty_roles WHERE counterparty_id=?',(counterparty,))
            self.db.executemany('INSERT INTO counterparty_roles(counterparty_id,role) VALUES (?,?)',[(counterparty,r) for r in sorted(roles)])
            if values is not None:
                self.db.execute("INSERT INTO counterparty_accounts(counterparty_id,company_id,purchases_account,expenses_account,preferred_group,approved_by) VALUES (?,?,?,?,?,'local_operator') ON CONFLICT(counterparty_id) DO UPDATE SET purchases_account=excluded.purchases_account,expenses_account=excluded.expenses_account,preferred_group=excluded.preferred_group,approved_by=excluded.approved_by,approved_at=CURRENT_TIMESTAMP,version=counterparty_accounts.version+1",(counterparty,company,values['purchases_account'],values['expenses_account'],values['preferred_group']))
            self.erp.repository.audit(company,'counterparty_card_updated',None,dict(counterparty_id=counterparty,before=before,after=self.detail(company,counterparty)[0]))
        return self.detail(company,counterparty)[0]
