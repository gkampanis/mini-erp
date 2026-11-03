# Έρευνα → συγκεκριμένες αλλαγές στο Mini ERP

Ημερομηνία: 21/10/2026. Προϊόν: χώρος προετοιμασίας, ελέγχου και τεκμηρίωσης εισαγωγών στο EBS, όχι αντικατάστασή του. Εφαρμόστηκαν ιδέες με νέα δική μας υλοποίηση. Δεν αντιγράφηκε κώδικας, assets ή λογιστικοί κανόνες τρίτων και δεν προστέθηκε runtime dependency.

| Επαληθευμένη πηγή | Ιδέα | Τι ενσωματώθηκε |
|---|---|---|
| ERPNext / OCA import modules | Διακριτά στάδια και αποτελέσματα εισαγωγής | Preview σε tabs Εγγραφές / Αντιστοίχιση / Εξαιρέσεις, ξεχωριστοί μετρητές νέων/duplicates/rejections/warnings, ρητή επιβεβαίωση. |
| OCA supplier reference checks | Πιθανό διπλότυπο παρά την αλλαγή ημερομηνίας | Nonblocking warning για ίδιο ΑΦΜ/σειρά/αριθμό στην ίδια εταιρεία και ημερολογιακό έτος με διαφορετική ημερομηνία. Casefold χωρίς αλλαγή πηγής. Δεν υποκαθιστά μελλοντικές εταιρικές accounting periods και δεν κάνει merge. |
| Paperless-ngx / Dolibarr | Master/detail και σταθερό review workspace | Καθαρή λίστα, αναζήτηση/reset/count, tabs Στοιχεία / Προετοιμασία EBS / Προέλευση / Ιστορικό, αποθηκευμένες αναφορές στο Έλεγχοι εισαγωγής. |
| CustomTkinter example | Συνεπής οπτική ιεραρχία και προσαρμογή χώρου | Δικό μας ttk theme, χρώματα, αποστάσεις, πίνακες με εναλλασσόμενες γραμμές, δεξιά στοίχιση ποσών, localized ημερομηνίες/ποσά, προσαρμογή στο διαθέσιμο display. Δεν εγκαταστάθηκε CustomTkinter. |
| ERPNext / Paperless review concepts | Imported ≠ approved ≠ posted | Η τοπική έγκριση ομάδας/λογαριασμού είναι ανεξάρτητη από το immutable παραστατικό και δεν χαρακτηρίζεται ως επιβεβαιωμένη EBS καταχώριση. |

## Ομάδα 2 / ομάδα 6

Στο detail ο χειριστής επιλέγει φύση συναλλαγής (αγορά ομάδας 2 ή έξοδο ομάδας 6), δίνει λογαριασμό από το δικό του σχέδιο, σημείωση και ρητή επιβεβαίωση ελέγχου. Η εφαρμογή επαληθεύει συντακτικά τον κωδικό και ότι συμφωνεί με την επιλεγμένη ομάδα. **Δεν επαληθεύει ότι ο λογαριασμός είναι υπαρκτός/ενεργός/κατάλληλος στο πραγματικό EBS.** Αυτό χρειάζεται εταιρικό chart και connector acceptance πριν οποιαδήποτε πραγματική καταχώριση.

Η migration `002_preparation.sql` προσθέτει `document_preparations` με company/document scope. Κάθε έγκριση/διόρθωση έχει before/after audit στην ίδια συναλλαγή. Ο ίδιος αντισυμβαλλόμενος μπορεί να έχει και τις δύο ομάδες· δεν δημιουργείται καθολικός supplier κανόνας από μια μεμονωμένη έγκριση. Το `documents.status`, τα αρχικά ποσά και το raw source δεν αλλάζουν. Φίλτρα «Χωρίς προετοιμασία / Με τοπική έγκριση» διαβάζουν την ανεξάρτητη απόφαση, όχι πλασματική EBS κατάσταση.

## Τι διατηρήθηκε και τι διορθώθηκε

Διατηρήθηκαν importer/domain validation, explicit confirmation, manual mapping και mandatory recheck, per-worker SQLite connection, transactions/crash rollback, exact dedupe/conflict rules, source SHA/raw και audit. Διορθώθηκε επιπλέον η δυνατότητα δεύτερου preview να χαθεί αν ξεκινούσε άλλη εργασία: υπάρχει ένα modal preview και οι busy ενέργειες απορρίπτονται πριν κλείσει το παράθυρο. Η ένδειξη επεξεργασίας παραμένει εμφανής κατά την αναζήτηση.

## Εκτός αυτής της αλλαγής

Δεν προστέθηκαν CRM, αποθήκη, banking, OCR, cloud sync ή νέο framework. Δεν ενεργοποιήθηκαν EBS writes/myDATA/λογιστικές εγγραφές. Το PDF/δελτίων archive παραμένει επόμενο σχετικό milestone: δεν προστέθηκε κενό κουμπί λήψης χωρίς πραγματική ασφαλή πηγή. Η έρευνα OCA queue παραμένει σχεδιασμός για μελλοντική ουρά· uncertain Save δεν θα επαναλαμβάνεται αυτόματα.

Αναλυτικά pinned links, source observations και άδειες: [workflow research](RESEARCH_WORKFLOW.md), [UI research](RESEARCH_UI.md).

## Επαλήθευση

20 automated backend tests, 9 GUI regression tests και επιτυχές end-to-end desktop smoke με δύο layouts και duplicate retry. Οι αρχικές λειτουργίες παραμένουν ελεγμένες. [Αναλυτικά QA](QA.md). [Νέα οθόνη](screenshots/documents.png), [φόρμα προετοιμασίας](screenshots/preparation.png), [μόνιμες αναφορές εισαγωγής](screenshots/import-reviews.png).
