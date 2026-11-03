"""Real Greek posting reasons must expose their corrective controls."""
import unittest
from app.ui.posting_issues import issue_actions


class IssueActionTests(unittest.TestCase):
    def test_mapping_reasons_open_settings(self):
        for reason in ('Όρισε πρώτα τις θέσεις στις Ρυθμίσεις EBS.',
                       'Απαιτούνται πρόσθετες γραμμές EBS',
                       'Απαιτείται πλήρης CSV mapper'):
            with self.subTest(reason=reason):self.assertTrue(issue_actions(reason)['settings'])

    def test_ambiguous_matching_opens_comparison(self):
        for reason in ('Χρειάζεται έλεγχος: πολλαπλές ισχυρές αντιστοιχίσεις',
                       'Χρειάζεται έλεγχος — διαφορετικά/ελλιπή: σειρά/αριθμός',
                       'Μερική συμφωνία — Πιθανώς καταχωρισμένο'):
            with self.subTest(reason=reason):
                actions=issue_actions(reason,True)
                self.assertTrue(actions['compare']);self.assertTrue(actions['review'])

    def test_missing_account_and_preparation_offer_card(self):
        for reason in ('Λείπει εγκεκριμένη προετοιμασία','Δεν υπάρχει λογαριασμός εξόδων ομάδας 6','Όρισε λογαριασμό για ΦΠΑ 13%'):
            with self.subTest(reason=reason):self.assertTrue(issue_actions(reason)['account'])

    def test_excluded_groups_cannot_offer_account_or_settings(self):
        actions=issue_actions('Αγορές ομάδας 2 · εκτός RPA · λογαριασμός και θέσεις EBS')
        self.assertFalse(actions['account']);self.assertFalse(actions['settings']);self.assertFalse(actions['review'])
