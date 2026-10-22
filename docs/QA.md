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

## Delivery gate εμπνευσμένο από ECC — 22/10/2026

Η συσκευασία περνά πλέον από το [Delivery Check](ECC_DELIVERY.md). Προστέθηκαν 6 έλεγχοι του ίδιου του gate: πραγματικό exit/timeout, μηδενικά ή skipped tests, απουσία φρέσκων αποτελεσμάτων, syntax/επικίνδυνα patterns, package manifest/allowlist και μη αντικατάσταση artifact μετά αποτυχία. Το backend suite περιέχει πλέον 26 tests, ενώ οι GUI regressions παραμένουν 9. Τα suites εκτελούνται ξανά και από το αποσυμπιεσμένο υποψήφιο ZIP.

Η cloud εκτέλεση έλεγξε και το demo/readback από το πακέτο. Αίτημα `--require-windows` στο Linux επέστρεψε αποτυχία χωρίς Windows ZIP, όπως απαιτείται. Οι Windows CMD launcher αλλαγές παραμένουν μη δοκιμασμένες σε πραγματικά Windows μέχρι να εκτελεστεί εκεί το gate. Δεν γίνεται ισχυρισμός coverage percentage ή πλήρους security audit από στοχευμένο static check.


## Startup diagnostics — 22/10/2026

Μετά αναφορά χρήστη ότι η εκκίνηση δεν εμφανίζει τίποτα, ο CMD launcher απλοποιήθηκε και ο έλεγχος Python μεταφέρθηκε σε bootstrap Python. Προστέθηκε `ANOIGMA_MINI_ERP.bat` με διατήρηση κονσόλας μέσω cmd /k, αναλυτικό per-run startup log, preflight έκδοσης/ελλιπούς αποσυμπίεσης/Tk/SQLite και διατήρηση πραγματικού child exit code. Δεν τεκμηριώνεται ακόμη η συγκεκριμένη αιτία στο PC του χρήστη· το νέο bootstrap εξασφαλίζει δυνατότητα διάγνωσης χωρίς νέα εγκατάσταση Python ή αλλαγή EBS.

Προστέθηκαν 4 tests εκκίνησης, άρα 30 backend/tool tests και 9 GUI regressions. Το gate εκτελεί επιπλέον πραγματικό `START_DEMO.py --check` στον source και στο αποσυμπιεσμένο ZIP. Οι BAT/CMD δεν έχουν εκτελεστεί σε Windows σε αυτή την cloud μηχανή.


## PDF / RPA / στρογγυλοποίηση / UI — 22/10/2026

Το υποχρεωτικό suite επεκτάθηκε σε 41 backend/tool tests και 12 GUI regressions.
Τα νέα synthetic tests ελέγχουν ROUND_HALF_UP και raw/audit, πραγματική migration
002→003/004 με προϋπάρχουσες εγκρίσεις, επωνυμία/ΑΦΜ, απομόνωση εταιρειών,
vault με injected memory adapter χωρίς μυστικά στο SQLite, PDF checksum και
πραγματικό raster rendering, HTTPS validation και mock λήψη, αποθήκευση ουράς,
παύση 40, αλλαγή approval, αβέβαιη προσπάθεια και απαγόρευση replay.
Στο GUI ελέγχονται επιπλέον ασφαλής φόρμα κωδικών, inline PDF και ουρά simulation.

Οι Windows Credential Manager/SendInput και πραγματικό EBS δεν εκτελέστηκαν.
Η HTTPS λήψη ελέγχεται με συνθετική απόκριση, όχι με πραγματικό τιμολόγιο.
Η μελέτη επίσημων τρεχουσών AADE προδιαγραφών παραμένει περιορισμένη από proxy
403· δεν δηλώνεται ελεγμένη ζωντανή σύνδεση. Τα πεδία κωδικών δεν είναι connector.
Για πλήρη tests χρειάζονται οι pinned PDF εξαρτήσεις του requirements-pdf.txt.
