"""Column predicates preserve financial cents and combine without SQL."""
import unittest
from unittest.mock import Mock
from app.ui.column_filters import ColumnFilters


class Headings:
    def __init__(self):self.titles=dict(name='Επωνυμία ↑',gross_minor='Σύνολο €',issue_date='Ημερομηνία')
    def bind(self,*args,**kwargs):pass
    def __getitem__(self,key):return tuple(self.titles)
    def heading(self,column,option=None,**kwargs):
        if kwargs:self.titles[column]=kwargs['text']
        return self.titles[column]


class ColumnFilterTests(unittest.TestCase):
    def setUp(self):
        self.tree=Headings();self.changed=Mock();self.filters=ColumnFilters(self.tree,self.changed)
        self.rows=[dict(id=1,name='ΔΟΚΙΜΗ Α',gross_minor=12,issue_date='2026-10-21'),dict(id=2,name='Δοκιμή Β',gross_minor=12400,issue_date='2026-09-20')]
    def test_combined_amount_and_text_filters_use_exact_cents(self):
        self.filters.set('name','δοκιμή');self.filters.set('gross_minor','>=0,13')
        self.assertEqual([r['id'] for r in self.filters.apply(self.rows)],[2])
        self.filters.set('gross_minor','<=0,12');self.assertEqual(self.filters.apply(self.rows),[self.rows[0]])
        self.assertEqual(self.rows[0]['gross_minor'],12)
    def test_date_search_and_exact_text_keep_original_records(self):
        self.filters.set('issue_date','21/10');self.assertEqual(self.filters.apply(self.rows),[self.rows[0]])
        self.filters.clear();self.filters.set('name','=Δοκιμή Β');self.assertEqual(self.filters.apply(self.rows),[self.rows[1]])
    def test_filter_marker_and_sort_arrow_survive_clear(self):
        self.filters.set('name','A');self.assertEqual(self.tree.titles['name'],'● Επωνυμία ↑')
        self.filters.sync_headings();self.assertEqual(self.tree.titles['name'],'● Επωνυμία ↑')
        self.filters.clear();self.assertEqual(self.tree.titles['name'],'Επωνυμία ↑')
    def test_invalid_amount_cannot_replace_a_valid_filter(self):
        self.filters.set('gross_minor','>100')
        with self.assertRaises((ValueError,ArithmeticError)):self.filters.set('gross_minor','>nonsense')
        self.assertEqual(self.filters.filters['gross_minor'],'>100')
