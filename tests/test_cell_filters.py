"""Raw typed equality/exclusion with AND, independent of displayed formatting."""
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import Mock
from app.ui.column_filters import ColumnFilters

class CellFiltersTests(unittest.TestCase):
    def setUp(self):
        self.filters=ColumnFilters.__new__(ColumnFilters)
        self.filters.value=None;self.filters.filters={};self.filters.cell_filters={}
        self.filters.on_change=Mock();self.filters.sync_headings=Mock();self.filters.summary=Mock();self.filters.tree=Mock();self.filters.tree.heading.return_value="Column"
        self.rows=[dict(id=1,vat='012345678',name='ONE',net_minor=100,issue_date='2026-10-01'),dict(id=2,vat='012345678',name='ONE',net_minor=200,issue_date='2026-10-02'),dict(id=3,vat='12345678',name='TWO',net_minor=100,issue_date='2026-10-01')]
    def ids(self):return [r['id'] for r in self.filters.apply(self.rows)]
    def test_vat_zeros_amounts_dates_and_and_combination_preserve_models(self):
        before=deepcopy(self.rows)
        self.filters.cell('vat','012345678');self.assertEqual(self.ids(),[1,2])
        self.filters.cell('net_minor',100);self.assertEqual(self.ids(),[1])
        self.filters.cell('issue_date',date(2026,10,1));self.assertEqual(self.ids(),[1])
        self.filters.cell('issue_date',date(2026,10,2));self.assertEqual(self.ids(),[])
        self.filters.remove('issue_date');self.assertEqual(self.ids(),[1])
        self.assertEqual(self.rows,before)
    def test_exclusion_and_clear_restore_all_rows_with_existing_range(self):
        self.filters.cell('name','ONE',True);self.assertEqual(self.ids(),[3])
        self.filters.clear();self.assertEqual(self.ids(),[1,2,3])
        self.filters.set('net_minor','>=1,50');self.assertEqual(self.ids(),[2])
        self.filters.cell('vat','012345678');self.assertEqual(self.ids(),[2])
        self.filters.clear(notify=True);self.assertEqual(self.ids(),[1,2,3])
    def test_empty_heading_value_removes_both_text_and_cell_rules_for_that_column(self):
        self.filters.cell('name','ONE');self.filters.set('name','ONE')
        self.filters.cell('vat','012345678')
        self.assertEqual(self.ids(),[1,2])
        self.filters.set('name','')
        self.assertNotIn('name',self.filters.filters);self.assertNotIn('name',self.filters.cell_filters)
        self.assertIn('vat',self.filters.cell_filters)
        self.assertEqual(self.ids(),[1,2])
    def test_include_then_exclude_switches_column_mode_without_contradictory_rules(self):
        self.filters.cell('name','ONE');self.assertEqual(self.ids(),[1,2])
        self.filters.cell('name','ONE',True);self.assertEqual(self.ids(),[3])
        self.filters.cell('name','TWO');self.assertEqual(self.ids(),[3])
        self.filters.cell('name','ONE');self.assertEqual(self.ids(),[1,2])
        self.filters.cell('net_minor',100);self.assertEqual(self.ids(),[1])
        self.filters.remove('name');self.assertEqual(self.ids(),[1,3])
    def test_exclusions_accumulate_and_other_column_rules_remain_independent(self):
        self.filters.cell('net_minor',100)
        self.filters.cell('name','ONE',True);self.assertEqual(self.ids(),[3])
        self.filters.cell('name','TWO',True);self.assertEqual(self.ids(),[])
        self.filters.remove('name');self.assertEqual(self.ids(),[1,3])

    def test_heading_and_cell_operations_replace_only_the_same_column_mode(self):
        self.filters.set('name','=ONE');self.assertEqual(self.ids(),[1,2])
        self.filters.cell('name','ONE',True);self.assertEqual(self.ids(),[3])
        self.filters.cell('net_minor',100)
        self.filters.set('name','=ONE');self.assertEqual(self.ids(),[1])
        self.assertNotIn('name',self.filters.cell_filters)
        self.assertIn('net_minor',self.filters.cell_filters)
    def test_remove_one_supplier_exclusion_keeps_the_other_exclusion_and_date(self):
        self.filters.cell('name','ONE',True);self.filters.cell('name','TWO',True)
        self.filters.cell('issue_date',date(2026,10,1))
        self.assertEqual(self.ids(),[])
        self.filters.remove_rule('name',(True,'ONE'))
        self.assertEqual(self.ids(),[1])
        self.assertEqual(self.filters.cell_filters['name'],[(True,'TWO')])
        self.assertIn('issue_date',self.filters.cell_filters)
