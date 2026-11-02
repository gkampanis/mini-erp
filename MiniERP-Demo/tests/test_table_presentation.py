"""Empty and stale rows do not leave misleading table summaries."""
import unittest
from unittest.mock import Mock
from app.ui.table_presentation import TablePresentation


class SummaryTree:
    def __init__(self,children,columns):
        self.children=children;self.columns=columns
    def __getitem__(self,key):
        if key=='columns':return self.columns
        raise KeyError(key)
    def get_children(self):return self.children
    def selection(self):return ()


class TablePresentationSummaryTests(unittest.TestCase):
    def presentation(self,children,columns,models):
        result=TablePresentation.__new__(TablePresentation)
        result.tree=SummaryTree(children,columns)
        result.models=models
        result.totals=(0,0,0)
        result.preference_error=False
        result.summary=Mock()
        return result

    def test_empty_results_show_recovery_hint_and_clear_totals(self):
        presentation=self.presentation((),('net_minor','gross_minor'),{1:{'net_minor':100,'tax_minor':24,'gross_minor':124}})
        presentation.totals=(100,24,124)
        presentation.update_summary()
        self.assertIn('Κανένα αποτέλεσμα',presentation.summary.set.call_args.args[0])
        self.assertIn('καθάρισε την αναζήτηση',presentation.summary.set.call_args.args[0])
        self.assertEqual(presentation.totals,(0,0,0))

    def test_invalid_or_stale_row_ids_do_not_break_visible_totals(self):
        presentation=self.presentation(('not-an-id','2','3'),('net_minor','gross_minor'),{
            2:{'net_minor':100,'tax_minor':24,'gross_minor':124},
            3:None,
        })
        presentation.update_summary()
        self.assertEqual(presentation.totals,(100,24,124))
        self.assertIn('Ορατά: 3',presentation.summary.set.call_args.args[0])
        self.assertIn('Σύνολο 1,24 €',presentation.summary.set.call_args.args[0])


if __name__=='__main__':
    unittest.main()
