"""Presentation preferences and visible totals never modify accounting data."""
import json
from pathlib import Path
import tempfile
import unittest
from app.ui.preferences import UIPreferences, clean_layout, visible_totals, display_column


class UIPreferenceTests(unittest.TestCase):
    def test_round_trip_keeps_other_tables_and_theme(self):
        with tempfile.TemporaryDirectory() as folder:
            store=UIPreferences(folder);store.set_theme('dark')
            store.set_layout('documents',dict(widths={'vat':112},visible=['vat','name'],sort=['name',True]))
            store.set_layout('expenses',dict(widths={'name':250},visible=['name']))
            again=UIPreferences(folder)
            self.assertEqual(again.theme,'dark')
            self.assertEqual(again.layout('documents')['widths']['vat'],112)
            self.assertEqual(again.sort('documents',('vat',False)),('name',True))
            self.assertEqual(again.layout('expenses')['visible'],['name'])
            self.assertEqual(list(Path(folder).iterdir()),[Path(folder)/'ui-preferences.json'])
    def test_corrupt_or_unrelated_json_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ui-preferences.json'
            for data in ('{broken','[]','{"theme":"invalid","tables":[]}'):
                p.write_text(data)
                store=UIPreferences(folder)
                self.assertEqual(store.theme,'dark');self.assertEqual(store.layout('documents'),{})
    def test_layout_ignores_unknown_duplicates_invalid_width_and_sort(self):
        value=clean_layout(dict(visible=['unknown','name','name'],widths={'vat':-2,'name':999999,'unknown':120},sort=['unknown',False]),('vat','name'))
        self.assertEqual(value['visible'],['name']);self.assertEqual(value['widths'],{})
        self.assertNotIn('sort',value)
        self.assertEqual(clean_layout(dict(visible=[]),('vat','name'))['visible'],['vat','name'])
    def test_visible_minor_totals_are_exact_and_do_not_parse_display_strings(self):
        rows=[dict(net_minor=100001,tax_minor=24000,gross_minor=124001),dict(net_minor=-1,tax_minor=0,gross_minor=-1)]
        self.assertEqual(visible_totals(rows),(100000,24000,124000))
        self.assertEqual(visible_totals([]),(0,0,0))
    def test_hidden_columns_resolve_displayed_identity_not_underlying_index(self):
        class Tree:
            def __getitem__(self,key):return dict(columns=('name','vat','pdf_state'),displaycolumns=('pdf_state','name'))[key]
            def identify_column(self,x):return '#'+str(x)
        self.assertEqual(display_column(Tree(),1),'pdf_state')
        self.assertEqual(display_column(Tree(),2),'name')
        self.assertIsNone(display_column(Tree(),0))
        self.assertIsNone(display_column(Tree(),3))
    def test_unwritable_preferences_do_not_break_working_ui(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            store=UIPreferences(folder)
            with patch('app.ui.preferences.os.replace',side_effect=PermissionError('synthetic')):
                self.assertFalse(store.set_theme('light'))
            self.assertEqual(store.theme,'light')
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_widths_respect_identifiers_amounts_and_available_room(self):
        from app.ui.table_presentation import proposed_widths
        columns=['name','vat','net_minor']
        widths=proposed_widths(columns,{'name':'Επωνυμία','vat':'ΑΦΜ','net_minor':'Καθαρή €'},[{'name':'X'*200,'vat':'000000001','net_minor':'123.456.789,99'}],lambda text:len(text)*7,700)
        self.assertGreaterEqual(widths['vat'],9*7+24)
        self.assertGreaterEqual(widths['net_minor'],len('123.456.789,99')*7+24)
        self.assertLessEqual(sum(widths.values()),700)
        narrow=proposed_widths(columns,{},[],lambda text:len(text)*7,100)
        self.assertGreater(sum(narrow.values()),100)

    def test_malformed_saved_sort_is_ignored(self):
        for value in ([[],True],[{},False],[None,True]):
            self.assertNotIn('sort',clean_layout({'sort':value},('name','vat')))
