"""Heading sorts move current IDs, without refreshing or formatting money as text."""
from copy import deepcopy
import unittest
from unittest.mock import Mock,MagicMock
from types import SimpleNamespace
from app.ui.table_actions import sort_tree
from app.ui.document_views import DocumentView
from app.ui.ebs_reconciliation import ReconciliationTab


class Tree:
    def __init__(self,children=('1','2','3')):
        self.children=list(children);self.headings=dict(name='Επωνυμία',net_minor='Καθαρή €',status='Κατάσταση')
        self.items={key:dict(tags=('protected',) if key=='2' else ()) for key in children}
        self.selected=('2',);self.focused='2';self.x=(.25,.7);self.y=(.1,.3)
    def __getitem__(self,key):return tuple(self.headings) if key=='columns' else None
    def get_children(self):return tuple(self.children)
    def move(self,item,parent,index):self.children.remove(item);self.children.insert(index,item)
    def item(self,item,option=None,**kwargs):
        if kwargs:self.items[item].update(kwargs)
        return self.items[item].get(option) if option else self.items[item]
    def heading(self,key,option=None,**kwargs):
        if 'text' in kwargs:self.headings[key]=kwargs['text']
        return self.headings[key]
    def xview(self):return self.x
    def yview(self):return self.y
    def xview_moveto(self,fraction):self.x=(fraction,self.x[1])
    def yview_moveto(self,fraction):self.y=(fraction,self.y[1])
    def delete(self,*args):raise AssertionError('A heading must never delete rows')


class TableActionsTests(unittest.TestCase):
    def models(self):
        return {1:dict(name='β',net_minor=10000,status='review'),2:dict(name='Α',net_minor=200,status='registered',match_kind='exact'),3:dict(name='α',net_minor=-100,status='not_registered')}
    def test_money_sort_preserves_raw_values_ids_selection_focus_and_scroll(self):
        tree=Tree();rows=self.models();before=deepcopy(rows)
        self.assertEqual(sort_tree(tree,rows,'net_minor'),['3','2','1'])
        self.assertEqual(tree.selected,('2',));self.assertEqual(tree.focused,'2')
        self.assertEqual(tree.x,(.25,.7));self.assertEqual(tree.y,(.1,.3));self.assertEqual(rows,before)
        self.assertIn('protected',tree.items['2']['tags']);self.assertTrue(tree.headings['net_minor'].endswith(' ↑'))
        self.assertEqual(sort_tree(tree,rows,'net_minor',True),['1','2','3'])
        self.assertEqual(tree.headings['net_minor'].count('↓'),1);self.assertNotIn('↑',tree.headings['net_minor'])
    def test_unicode_sort_is_case_insensitive_and_equal_values_are_stable(self):
        tree=Tree();rows=self.models()
        self.assertEqual(sort_tree(tree,rows,'name'),['2','3','1'])
        self.assertEqual(sort_tree(tree,rows,'name'),['2','3','1'])
    def test_document_heading_never_calls_full_refresh(self):
        view=DocumentView.__new__(DocumentView);view.tree=Tree();view.rows=self.models();view.sort=('name',False)
        view.column_filters=Mock();view.refresh=Mock(side_effect=AssertionError('Unexpected refresh'))
        view.sort_by('net_minor')
        self.assertEqual(view.tree.children,['3','2','1']);view.refresh.assert_not_called()
        view.column_filters.sync_headings.assert_called_once()
    def test_reconciliation_heading_never_requeries_evidence_and_uses_displayed_status(self):
        view=ReconciliationTab.__new__(ReconciliationTab);view.tree=Tree();view.rows=self.models();view.sort=('name',False)
        view.column_filters=Mock();view.refresh=Mock(side_effect=AssertionError('Unexpected refresh'));view.service=Mock()
        view.sort_by('status');view.refresh.assert_not_called();view.service.results.assert_not_called()
        from app.ui.ebs_reconciliation import result_title
        self.assertEqual(view.tree.children,sorted(['1','2','3'],key=lambda item:result_title(view.rows[int(item)]).casefold()))
    def test_double_click_heading_or_empty_space_never_opens_previous_document(self):
        for cls,callback in [(DocumentView,'detail'),(ReconciliationTab,'open')]:
            view=cls.__new__(cls);view.tree=MagicMock();view.tree.__getitem__.return_value=('name','pdf_state')
            action=Mock();setattr(view,callback,action);event=SimpleNamespace(x=10,y=20)
            view.tree.identify_region.return_value='heading';view.double_click(event);action.assert_not_called()
            view.tree.identify_region.return_value='cell';view.tree.identify_row.return_value=''
            view.tree.identify_column.return_value='#1';view.double_click(event);action.assert_not_called()
            view.tree.identify_row.return_value='2';view.double_click(event);action.assert_called_once()
            view.tree.selection_set.assert_called_once_with('2')
