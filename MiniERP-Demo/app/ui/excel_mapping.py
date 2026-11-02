"""One column interaction, retaining the two existing workbook business stages."""
import json
import tkinter as tk
from tkinter import ttk

from app.infrastructure.importers.excel import NAMES,REQUIRED,header_mapping,preview
from app.infrastructure.importers.legacy_primitives import norm


EBS_COLUMNS={'date':'Ημ/νία','invoice':'Εναλ. παρ/κό','vat':'Α.Φ.Μ.','net':'Αξία','tax':'ΦΠΑ','gross':'Σύνολο'}
EBS_IGNORED=('Παρ/κό','Κατ.','Συναλλασσόμενος','Τίτλος')


def auto_mapping(headers,role='documents'):
    mapping=header_mapping(headers)
    if role=='ebs':
        mapping={k:v for k,v in mapping.items() if k in EBS_COLUMNS}
        for key,label in EBS_COLUMNS.items():
            matches=[column for column,title in headers.items() if norm(title)==norm(label)]
            if len(matches)==1:mapping[key]=matches[0]
        ignored={column for column,title in headers.items() if norm(title) in {norm(s) for s in EBS_IGNORED}}
        mapping={key:column for key,column in mapping.items() if column not in ignored}
    return mapping


def best_layout(book,role='documents',*,saved_mapping=None):
    candidates=[]
    for sheet in book['sheets']:
        for row,headers in sheet['rows'][:12]:
            saved=saved_mapping(headers) if saved_mapping else {}
            mapping=saved or auto_mapping(headers,role)
            required=EBS_COLUMNS if role=='ebs' else REQUIRED
            score=sum(key in mapping for key in required)*5+(100 if saved else 0)
            if role!='ebs':score+=sum(key in mapping for key in ('invoice','number','series'))
            candidates.append((score,dict(sheet=sheet['name'],header_row=row,headers=headers,mapping=mapping)))
    if not candidates:raise ValueError('Δεν υπάρχουν αναγνώσιμα φύλλα')
    return max(candidates,key=lambda candidate:candidate[0])[1]


def classify_workbook(book,erp=None,company=None):
    """Only identify established layouts; common financial headers need a role."""
    if erp is not None and company is not None:
        from app.application.ebs_reconciliation import EBSReconciliation
        service=EBSReconciliation(erp)
        active=erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(company,)).fetchone()
        environment=active[0] if active else 'production';roles={'ebs'} if saved_ebs_layout(erp,company,book) else set()
        for sheet in book['sheets']:
            for _,headers in sheet['rows'][:12]:
                if service.saved_mapping(company,headers):roles.add('ebs')
                if saved_document_mapping(erp,company,headers,environment):roles.add('documents')
        if len(roles)==1:return roles.pop()
        if roles:return None
    for sheet in book['sheets']:
        for _,headers in sheet['rows'][:12]:
            if any(norm(label)==norm(EBS_COLUMNS['invoice']) for label in headers.values()):return 'ebs'
    layout=best_layout(book,'documents');mapping=layout['mapping']
    complete=all(key in mapping for key in REQUIRED) and any(key in mapping for key in ('number','invoice'))
    if complete and ('mark' in mapping or ('series' in mapping and 'number' in mapping)):
        return 'documents'
    return None


def saved_ebs_layout(erp,company,book):
    """Honor stored sheet/header metadata, including headers below the scan window."""
    from app.application.ebs_reconciliation import EBSReconciliation
    for profile in erp.db.execute('SELECT * FROM ebs_column_mappings WHERE company_id=?',(company,)):
        sheet=next((s for s in book['sheets'] if s['name']==profile['sheet']),None)
        if sheet is None:continue
        headers=next((raw for row,raw in sheet['rows'] if row==profile['header_row']),None)
        if headers is not None and EBSReconciliation.layout_hash(headers)==profile['layout_hash']:
            return dict(sheet=sheet['name'],header_row=profile['header_row'],headers=headers,mapping=json.loads(profile['mapping_json']))
    return None


def saved_document_mapping(erp,company,headers,environment='production'):
    """Reuse successful document-import audit, without an EBS-profile/schema change."""
    expected={str(column):label for column,label in headers.items()}
    rows=erp.db.execute("SELECT a.payload FROM audit_events a JOIN import_jobs j ON j.id=json_extract(a.payload,'$.job') AND j.company_id=a.company_id WHERE a.company_id=? AND a.action='import_completed' AND j.environment=? ORDER BY a.id DESC",(company,environment))
    for row in rows:
        packet=json.loads(row['payload'])
        if packet.get('source_kind','excel')!='excel' or packet.get('headers')!=expected:continue
        mapping=packet.get('mapping',{})
        if not isinstance(mapping,dict) or any(key not in NAMES or type(column) is not int or column not in headers for key,column in mapping.items()):continue
        if all(key in mapping for key in REQUIRED) and any(key in mapping for key in ('number','invoice')):return mapping
    return {}


def raw_preview(erp,company,path,book):
    active=erp.db.execute('SELECT environment FROM aade_settings WHERE company_id=?',(company,)).fetchone()
    environment=active[0] if active else 'production'
    layout=best_layout(book,'documents',saved_mapping=lambda headers:saved_document_mapping(erp,company,headers,environment))
    return preview(path,layout['mapping'],book=book,sheet=layout['sheet'],header_row=layout['header_row'])


class ColumnMapping(ttk.Frame):
    def destroy(self):
        super().destroy()
        # Tcl variables belong to the UI thread, including their final release.
        self.variables.clear()
        self.boxes.clear()

    def __init__(self,parent,fields,*,unique=False):
        super().__init__(parent)
        self.unique=unique;self.lookup={};self.variables={};self.boxes={}
        for column in range(2):self.columnconfigure(column*2+1,weight=1)
        for index,(key,label) in enumerate(fields.items()):
            row,column=index//2,(index%2)*2
            ttk.Label(self,text=label,wraplength=160).grid(row=row,column=column,sticky='w',pady=7,padx=8)
            variable=tk.StringVar(self,value='—');self.variables[key]=variable
            box=ttk.Combobox(self,textvariable=variable,state='readonly',width=24)
            box.grid(row=row,column=column+1,sticky='ew',padx=8);self.boxes[key]=box

    def set_headers(self,headers,mapping,*,excluded_labels=()):
        excluded={norm(label) for label in excluded_labels}
        self.lookup={f'{column+1}: {label}':column for column,label in sorted(headers.items()) if norm(label) not in excluded}
        for key,box in self.boxes.items():
            box.configure(values=('—',*self.lookup))
            self.variables[key].set(next((label for label,column in self.lookup.items() if column==mapping.get(key)),'—'))

    def mapping(self):
        mapping={key:self.lookup[var.get()] for key,var in self.variables.items() if var.get() in self.lookup}
        if self.unique and len(set(mapping.values()))!=len(mapping):
            raise ValueError('Η ίδια στήλη χρησιμοποιείται δύο φορές. Διόρθωσε την αντιστοίχιση.')
        return mapping

    def missing(self,required,alternative=()):
        mapping=self.mapping();missing=[key for key in required if key not in mapping]
        if alternative and not any(key in mapping for key in alternative):missing.append('/'.join(alternative))
        return missing
