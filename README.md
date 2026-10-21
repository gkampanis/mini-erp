# Mini ERP — πρώτη λειτουργική τομή

Ανεξάρτητο ελληνικό desktop για **Excel → SQLite → Παραστατικά → Αναζήτηση / Detail**. Δεν απαιτεί Entersoft. Η εφαρμογή δεν παράγει λογιστικές εγγραφές και δεν επικοινωνεί με myDATA/EBS.

## Εκκίνηση

Python 3.12+ με Tkinter και SQLite. Δεν απαιτούνται τρίτα Python packages. Στα Windows εγκαταστήστε Python από python.org με Tcl/Tk. Σε Linux χρειάζεται διαθέσιμο display και Tkinter του Python runtime.

```powershell
cd mini-erp
py -3.12 -m unittest discover -s tests -v
py -3.12 -m app.demo
```

Το demo δημιουργεί αποκλειστικά συνθετικά δεδομένα στο `.local/demo`: δύο διαφορετικά Excel layouts, τρία τιμολόγια, τρεις προμηθευτές και μία απορριπτέα γραμμή. Αρνείται υπάρχοντα φάκελο βάσης χωρίς demo marker. Επαναληπτική εκτέλεση δεν διπλασιάζει παραστατικά.

Για κανονική κενή βάση:

```powershell
py -3.12 -m app --data-dir C:\MiniERP-data
```

Στην πρώτη εκκίνηση δηλώνετε εταιρεία (ΑΦΜ ως κείμενο και επωνυμία). Στο Linux οι αντίστοιχες εντολές χρησιμοποιούν `python`. Προτιμήστε τοπικό δίσκο για βάση και sources, όχι ενεργή SQLite σε SMB/NAS.

## Χρήση

1. «Εισαγωγή Excel»: αναγνωρίζει XLSX/XLSM, ανεξάρτητα από σειρά στηλών.
2. Ελέγξτε mapping και preview. Άγνωστες/διφορούμενες στήλες διορθώνονται από τα πεδία αντιστοίχισης και επανελέγχονται πριν επιβεβαίωση.
3. Υποχρεωτικά ΑΦΜ, ημερομηνία, καθαρή, ΦΠΑ και αριθμός ή ενιαίος αριθμός. MARK προαιρετικό. Σειρά/αριθμός διατηρούνται ξεχωριστά. Το gross μπορεί να προκύψει από net + tax χωρίς υπολογισμό φορολογικού συντελεστή.
4. Επιβεβαιώστε την εισαγωγή. Οι εξαιρέσεις εμφανίζονται στην πλήρη αναφορά και αποθηκεύονται στο job. Διπλότυπα παραλείπονται, conflicts κρατούνται για έλεγχο χωρίς overwrite.
5. Αναζητήστε με ΑΦΜ, επωνυμία, ημερομηνία, σειρά, αριθμό ή MARK. Διπλό κλικ για detail, raw προέλευση, SHA-256 και audit timeline.

Πρώτη τομή: εισερχόμενα τιμολόγια EUR, όλα «Προς έλεγχο». Αρχεία .xls χρειάζονται εξωτερική μετατροπή. Formula rows απορρίπτονται, macros δεν εκτελούνται, ΑΦΜ δεν συμπληρώνονται αυτόματα. Ο έλεγχος ΑΦΜ είναι μορφολογικός, όχι επαλήθευση στο φορολογικό μητρώο. Περιορισμοί: 20 MB compressed, 64 MB expanded XML, 20.000 γραμμές/φύλλο, 200 cells/γραμμή.

## Τεκμηρίωση και επόμενα

- [Αναλυτικό audit, αρχιτεκτονική, schema, ADRs, backlog](docs/AUDIT.md)
- [Συμβόλαια και ασφάλεια integrations](docs/CONTRACTS.md)
- [QA, migrations και backup/restore](docs/QA.md)

Η πρώτη τομή δεν είναι ολόκληρο το Phase 1. PDF archive, editing μητρώου, approved account-mapping UI, manual classification, advanced filters, exports και dashboard είναι επόμενα milestones. myDATA, EBS, journal και έκδοση παραστατικών δεν έχουν υλοποιηθεί. Δεν γίνεται ισχυρισμός φορολογικής συμμόρφωσης. Το αρχικό EBS source διατηρείται ανέπαφο εκτός repository στο `/workspace/reference-handoff` του παρόντος cloud workspace.

## Git / κυκλοφορίες

Το νέο repository είναι ανεξάρτητο από τον EBS Agent. `main` για baseline και `feature/*` για λειτουργίες. Τοπικά tags μόνο για ελεγμένα releases. Κανένα push ή δημόσια διάθεση χωρίς έγκριση και έλεγχο άδειας/δεδομένων.

Στο παρόν cloud χρησιμοποιήστε `/usr/bin/python3 -m app.demo` με διαθέσιμο `DISPLAY` για σωστή απόδοση ελληνικών. Δείτε επίσης το [schema roadmap](docs/SCHEMA.md) και τα [screenshots της εκτελεσμένης εφαρμογής](docs/screenshots/documents.png).
