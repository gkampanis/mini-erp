"""Developer-only generated UI-state sequences; the desktop has no Hypothesis import."""
from copy import deepcopy
from datetime import date
from hypothesis import settings,strategies as st
from hypothesis.stateful import RuleBasedStateMachine,rule,invariant
from app.ui.column_filters import ColumnFilters
from app.ui.table_actions import sort_tree,posting_ids
from tests.test_column_filters import Headings
from tests.test_table_actions import Tree

IDS=(11,38,99,145)
COLS=('vat','issue_date','gross_minor')

class FilterStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.rows=[dict(id=key,name='SUP_'+str(i//2),vat=f'{4+i//2:09d}',issue_date=f'2026-09-0{i+1}',gross_minor=21+i*100,account_code='64.03') for i,key in enumerate(IDS)]
        self.original=deepcopy(self.rows);headings=Headings();headings.titles.update(vat='VAT')
        self.filters=ColumnFilters(headings,lambda:None)
        self.model={};self.query='';self.selected=set();self.order=('id',False)
    def cell(self,col,value,exclude):
        raw=date.fromisoformat(value) if col=='issue_date' else value
        self.filters.cell(col,raw,exclude)
        previous=self.model.get(col)
        values=set(previous[1]) if exclude and previous and previous[0]=='exclude' else set()
        values.add(value);self.model[col]=('exclude' if exclude else 'include',values)
    @rule(vat=st.sampled_from(('000000004','000000005')),exclude=st.booleans())
    def supplier(self,vat,exclude):self.cell('vat',vat,exclude)
    @rule(day=st.integers(1,4),exclude=st.booleans())
    def day(self,day,exclude):self.cell('issue_date',f'2026-09-0{day}',exclude)
    @rule(value=st.sampled_from((21,121,221,321)),exclude=st.booleans())
    def amount(self,value,exclude):self.cell('gross_minor',value,exclude)
    @rule(threshold=st.sampled_from((21,121,221,321)))
    def amount_range(self,threshold):
        self.filters.set('gross_minor',f'>={threshold//100},{threshold%100:02d}')
        self.model['gross_minor']=('ge',{threshold})
    @rule(column=st.sampled_from(COLS))
    def remove_one(self,column):
        condition=self.model.get(column)
        if not condition:return
        mode,values=condition
        if mode=='ge':self.filters.remove_rule(column,None);self.model.pop(column);return
        value=min(values)
        raw=date.fromisoformat(value) if column=='issue_date' else value
        self.filters.remove_rule(column,(mode=='exclude',self.filters.canonical(column,raw)))
        values.remove(value)
        if not values:self.model.pop(column)
    @rule(column=st.sampled_from(COLS))
    def remove_column(self,column):self.filters.remove(column);self.model.pop(column,None)
    @rule(query=st.sampled_from(('','SUP_0','SUP_1','000000004','NO_MATCH')))
    def search(self,query):self.query=query
    @rule()
    def clear_search(self):self.query=''
    @rule()
    def reset(self):self.filters.clear(notify=True);self.model.clear()
    @rule(key=st.sampled_from(('id','gross_minor','issue_date','name')),reverse=st.booleans())
    def sort(self,key,reverse):self.order=(key,reverse)
    @rule(selected=st.sets(st.sampled_from(IDS)))
    def select(self,selected):self.selected=selected
    @invariant()
    def view_and_selection_are_stable_ids_and_source_data_is_immutable(self):
        expected=[]
        for row in self.rows:
            if self.query.casefold() not in (row['name']+' '+row['vat']).casefold():continue
            accepted=True
            for col,(mode,values) in self.model.items():
                current=row[col]
                if mode=='ge':accepted &= current>=next(iter(values))
                elif mode=='include':accepted &= current in values
                else:accepted &= current not in values
            if accepted:expected.append(row)
        key,reverse=self.order
        expected.sort(key=lambda r:r[key] if key.endswith('_minor') else str(r[key]).casefold(),reverse=reverse)
        actual=[r for r in self.filters.apply(self.rows) if self.query.casefold() in (r['name']+' '+r['vat']).casefold()]
        tree=Tree(tuple(str(r['id']) for r in actual));tree.headings={c:c for c in ('id','vat','name','issue_date','gross_minor')}
        tree.selection=lambda:tuple(str(i) for i in self.selected if str(i) in tree.children)
        sort_tree(tree,{r['id']:r for r in self.rows},key,reverse)
        ids=[r['id'] for r in expected];assert posting_ids(tree,'batch')==ids
        selected=[i for i in ids if i in self.selected];assert posting_ids(tree,'selected')==selected
        if len(selected)==1:assert posting_ids(tree,'one')==selected
        else:
            try:posting_ids(tree,'one')
            except ValueError:pass
            else:raise AssertionError('Single action accepted zero or multiple records')
        assert self.rows==self.original

TestFilterStateMachine=FilterStateMachine.TestCase
TestFilterStateMachine.settings=settings(max_examples=35,stateful_step_count=35,deadline=None,derandomize=True)
