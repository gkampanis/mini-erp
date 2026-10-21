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
