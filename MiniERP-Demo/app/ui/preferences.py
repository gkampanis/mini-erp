"""UI-only preferences. No accounting connection, migrations or native input."""
import copy
import json
import os
from pathlib import Path
import tempfile


def clean_layout(value,columns):
    if not isinstance(value,dict):return {}
    allowed=set(columns);result={};visible=value.get('visible')
    if isinstance(visible,list):
        result['visible']=list(dict.fromkeys(c for c in visible if isinstance(c,str) and c in allowed)) or list(columns)
    widths=value.get('widths',{})
    result['widths']={k:v for k,v in widths.items() if k in allowed and type(v) is int and 45<=v<=1600} if isinstance(widths,dict) else {}
    sort=value.get('sort')
    if isinstance(sort,(list,tuple)) and len(sort)==2 and isinstance(sort[0],str) and sort[0] in allowed and type(sort[1]) is bool:result['sort']=list(sort)
    return result


def visible_totals(rows):
    rows=list(rows);totals=[]
    for key in ('net_minor','tax_minor','gross_minor'):
        values=[r.get(key) or 0 for r in rows]
        if any(type(v) is not int for v in values):raise ValueError('Τα σύνολα προβολής απαιτούν ακέραια λεπτά')
        totals.append(sum(values))
    return tuple(totals)


def display_column(tree,x):
    try:
        displayed=list(tree['displaycolumns']);columns=list(tree['columns'])
        if displayed==['#all']:displayed=columns
        index=int(tree.identify_column(x)[1:])-1
        return displayed[index] if 0<=index<len(displayed) else None
    except (ValueError,IndexError,TypeError):return None


class UIPreferences:
    def __init__(self,directory):
        self.path=Path(directory)/'ui-preferences.json';self.data={}
        try:
            if self.path.stat().st_size<=262144:
                value=json.loads(self.path.read_text(encoding='utf8'))
                if isinstance(value,dict):self.data=value
        except (OSError,ValueError,UnicodeError,RecursionError):pass
        if not isinstance(self.data.get('tables'),dict):self.data['tables']={}
    @property
    def theme(self):return self.data.get('theme') if self.data.get('theme') in ('light','dark') else 'dark'
    def layout(self,key):
        value=self.data['tables'].get(key,{})
        return copy.deepcopy(value) if isinstance(value,dict) else {}
    def sort(self,key,default,columns=None):
        value=self.layout(key).get('sort')
        if isinstance(value,(list,tuple)) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is bool and (columns is None or value[0] in columns):return tuple(value)
        return default
    def set_layout(self,key,value):
        self.data['tables'][key]=copy.deepcopy(value)
        return self.save()
    def set_theme(self,value):
        if value not in ('light','dark'):raise ValueError('Άγνωστη εμφάνιση')
        self.data['theme']=value;return self.save()
    def save(self):
        staged=None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            fd,staged=tempfile.mkstemp(prefix='.ui-pref-',suffix='.json',dir=self.path.parent)
            with os.fdopen(fd,'w',encoding='utf8') as stream:json.dump(self.data,stream,ensure_ascii=False,indent=2)
            os.replace(staged,self.path);return True
        except (OSError,TypeError,ValueError,UnicodeError):return False
        finally:
            if staged:
                try:os.unlink(staged)
                except OSError:pass
