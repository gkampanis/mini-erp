# QA / migrations / rollback

```sh
cd /workspace/mini-erp
python -m unittest discover -s tests -v
python -m app --check --data-dir .local/check
python -m app.demo --prepare-only
python -m app.demo --prepare-only
```

Τα tests παράγουν πραγματικά συνθετικά OOXML workbooks σε προσωρινούς φακέλους. Ελέγχουν δύο layouts, χωριστή/ενιαία σειρά, leading zeros, mixed suppliers, cents, nonfinite ποσά, formulas, XML limits, manual mapping, duplicate/conflict, audit immutability, tenant isolation, reopen, migrations και backup integrity. Το crash test τερματίζει subprocess με os._exit εντός transaction και επαληθεύει rollback/retry από νέα σύνδεση. Δεν υποκαθιστά power-loss hardware testing.

## Migrations

`app/infrastructure/database.py` εφαρμόζει τα ordered SQL αρχεία του `migrations/` μέσα σε transaction και καταγράφει το version. `001_initial.sql`: πραγματικοί πίνακες/FKs/indices/triggers. Δεν επιτρέπεται αλλαγή εφαρμοσμένης migration· προσθέστε νέα version και δοκιμές upgrade σε αντίγραφο. Κρατήστε backup πριν αναβάθμιση.

## Backup / restore

Η `backup(connection, path)` χρησιμοποιεί SQLite backup API και PRAGMA integrity_check. Backup της SQLite **και** ολόκληρου του `sources/` στον ίδιο χρόνο με σταματημένη την εισαγωγή. Το WAL δεν αντιγράφεται χειροκίνητα από ενεργή βάση. Για συνεπές πλήρες backup κλείστε το desktop και αντιγράψτε όλο τον data directory σε νέα θέση/NAS, διατηρώντας το ενεργό data directory τοπικό.

Restore: κλείστε desktop, κρατήστε το τρέχον data directory με άλλο όνομα, επαναφέρετε το backup σε νέο τοπικό directory, εκτελέστε `python -m app --check --data-dir <restored>` και ελέγξτε τα SHA256 του sources έναντι import_jobs. Ανοίξτε την εφαρμογή στον restored φάκελο και ελέγξτε αναζήτηση/detail. Αυτόματη down migration δεν υποστηρίζεται· rollback εφαρμογής με συμβατή backup βάση, ποτέ drop tables με δεδομένα.

## Χειροκίνητο acceptance

Windows: εγκατάσταση Python/Tk, demo, αλλαγή mapping και επανέλεγχος, επιβεβαίωση εισαγωγής, έλεγχος πλήρους αναφοράς εξαιρέσεων, search, detail, κλείσιμο και επανεκκίνηση. Μετά νέα εισαγωγή ίδιου αρχείου πρέπει να εμφανίζονται duplicates, χωρίς νέα documents. Ακύρωση preview δεν γράφει δεδομένα. Windows desktop και EBS acceptance δεν θεωρούνται ελεγμένα από Linux tests.

## Αποτελέσματα παρούσας εκτέλεσης

- 12/12 automated tests πέρασαν με Python 3.12.14 και system Python 3.13.5 (τελική desktop επικύρωση με το δεύτερο).
- GUI smoke με Xvfb και system Tk 8.6: δύο previews/επιβεβαιώσεις, τρία documents, duplicate retry, search και detail. Τα dialogs επιλογής αρχείου/έγκρισης αυτοματοποιήθηκαν μόνο στη δοκιμή.
- Πραγματικά screenshots: [λίστα](screenshots/documents.png), [preview](screenshots/import-preview.png), [detail](screenshots/document-detail.png).
- Δύο εκτελέσεις demo: 3 documents και στη δεύτερη εκτέλεση 3 duplicates / 0 νέα documents.
- Legacy: 6 pass, 1 skipped importer fixture. 13 baseline files συγκρίθηκαν byte-for-byte με το original ZIP, του οποίου SHA256 ταυτίζεται με το manifest.
- Windows desktop, live EBS, AADE, PDF archive, πλήρες backup αρχείων και πραγματικό NAS restore δεν δοκιμάστηκαν.

Cloud runtime: το προεπιλεγμένο Python/Tk 9 δεν απέδωσε σωστά ελληνικά στο Xvfb. Για GUI χρησιμοποιήθηκε `/usr/bin/python3` (3.13.5, Tk 8.6), με σωστή απόδοση επιβεβαιωμένη στα screenshots. Δεν απαιτήθηκε αλλαγή της εφαρμογής για αυτό. Το Xvfb κατεβάστηκε με υπογεγραμμένο Debian APT metadata και αποσυμπιέστηκε στο `/workspace/cloud-tools/x11`, χωρίς εγκατάσταση στο σύστημα. Για screenshots μόνο, χρησιμοποιήθηκε το ήδη διαθέσιμο Pillow από το default Python.

## Έρευνα και UI / προετοιμασία EBS — 21/10/2026

Τελική επαλήθευση: **20/20 domain/database/import/preparation tests**, **9/9 πρόσθετα GUI regression tests** και επιτυχές end-to-end GUI smoke. Οι αρχικοί 12 έλεγχοι διατηρήθηκαν· προσαρμόστηκε μόνο η αναμενόμενη λίστα migrations ώστε να περιλαμβάνει την 002.

```sh
/usr/bin/python3 -m unittest discover -s tests -v
DISPLAY=:99 XDG_CACHE_HOME=/workspace/cloud-tools/cache /usr/bin/python3 -m tests.gui_regressions
DISPLAY=:99 XDG_CACHE_HOME=/workspace/cloud-tools/cache /usr/bin/python3 -m tests.gui_smoke
```

Οι 9 δοκιμές UI καλύπτουν ακύρωση χωρίς εγγραφές, μοναδικό preview, mapping recheck, busy προστασία, σφάλματα worker, πλήρεις εξαιρέσεις, σωστό document ID μετά ταξινόμηση/φίλτρο, ρητή έγκριση ομάδας 2/6 με επαναφόρτωση και audit, κλείσιμο με preview, μικρό παράθυρο και σφάλμα SQLite κατά την έγκριση. Οι συνδυασμένες περιπτώσεις ελέγχονται σε 9 tests, όχι ως ξεχωριστές μετρήσεις επιτυχίας. Διορθώθηκε πραγματικό callback error κατά το κλείσιμο preview. Το GUI test harness καθαρίζει Tk objects στο κύριο thread ανά περίπτωση, ώστε το GC επόμενου worker να μην οριστικοποιεί Tcl variables προηγούμενου test.

Η migration 002 εφαρμόστηκε σε synthetic υπάρχουσα βάση 001 και επαληθεύτηκε ότι τα αρχικά documents/source παραμένουν ίδια. Η έγκριση προετοιμασίας και το audit κάνουν rollback μαζί σε αποτυχία. Τα near-duplicate warnings ελέγχθηκαν στο ίδιο έτος και με ασφαλή διαχωρισμό επόμενου έτους. Δεν είναι λογιστική επιβεβαίωση EBS.

Νέα πραγματικά screenshots από συνθετικά δεδομένα: [νέα λίστα](screenshots/documents.png), [προετοιμασία](screenshots/preparation.png), [έλεγχοι εισαγωγής](screenshots/import-reviews.png). Οι δύο εμφανιζόμενοι λογαριασμοί στα screenshots είναι συνθετικά παραδείγματα, όχι επικυρωμένο σχέδιο EBS.

Μετά τις αλλαγές επαληθεύτηκαν ξανά byte-for-byte και τα 13 αρχεία του αρχικού EBS archive. Δεν έγινε live EBS/Windows acceptance, πραγματική καταχώριση, λήψη PDF ή myDATA σύνδεση. Η τοπική προετοιμασία δεν αλλάζει αυτή τη διάκριση.
