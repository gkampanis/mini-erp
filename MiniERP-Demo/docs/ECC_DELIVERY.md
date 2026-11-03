# Mini ERP Delivery Check — έλεγχος πριν από κάθε ZIP

Εργαλείο του συγκεκριμένου project, εμπνευσμένο από το [ECC verification-loop](https://github.com/affaan-m/ECC/blob/90606c8315ee09cafc303515c5f33024db6b9882/skills/verification-loop/SKILL.md). Εξετάστηκε η [MIT άδεια](https://github.com/affaan-m/ECC/blob/90606c8315ee09cafc303515c5f33024db6b9882/LICENSE). Η υλοποίηση είναι δική μας Python και προσαρμόζεται στο πραγματικό Mini ERP, χωρίς εγκατάσταση hooks, agents, εξωτερικού λογισμικού ECC ή νέων εφαρμογών. Δεν χρησιμοποιεί AI για να αποφαίνεται αν πέρασαν τα tests: διαβάζει πραγματικά exit codes και τα αποτελέσματα των runners.

## Εκτέλεση

Windows με Python 3.12 και Tcl/Tk:

```powershell
py -3.12 scripts\verify_delivery.py --require-windows
```

Cloud Linux με το ήδη εγκατεστημένο Xvfb:

```sh
DISPLAY=:99 XDG_CACHE_HOME=/workspace/cloud-tools/cache /usr/bin/python3 scripts/verify_delivery.py
```

Και η παλαιότερη εντολή `python scripts/package_demo.py` περνά πλέον από τον ίδιο έλεγχο. Το low-level `build()` χρησιμοποιείται εσωτερικά για υποψήφια πακέτα· ένα ZIP χωρίς verification report δεν θεωρείται ελεγμένη παράδοση.

## Τι ελέγχει

1. Δημιουργεί προσωρινό αντίγραφο μόνο των επιτρεπόμενων αρχείων κώδικα/τεκμηρίωσης. Δεν εκτελεί δοκιμές στην κανονική βάση ή στον EBS Agent.
2. Ελέγχει Python syntax και συγκεκριμένα επικίνδυνα patterns: eval/exec, pickle deserialization, shell=True και hardcoded credential-like assignments στην εφαρμογή. Αυτός ο στοχευμένος έλεγχος δεν ισοδυναμεί με πλήρες security audit ή code review.
3. Απαιτεί λειτουργικό Tk/display. Οι απαραίτητες GUI δοκιμές δεν παραλείπονται σιωπηλά όταν λείπει display.
4. Εκτελεί πραγματικές backend tests, GUI regression tests και end-to-end εισαγωγή μέσω της οθόνης. Μηδενικά tests, failures, errors, skipped, expected failures και unexpected successes μπλοκάρουν την παράδοση.
5. Δημιουργεί υποψήφιο ZIP και ελέγχει CRC, paths, απαιτούμενα αρχεία, ακριβές allowlist περιεχομένων και αποκλεισμό τοπικών βάσεων, credential files, PDF/πραγματικών Excel και legacy αρχείων. Μόνο δύο παραγόμενα συνθετικά Excel επιτρέπονται.
6. Αποσυμπιέζει το ZIP σε νέο προσωρινό φάκελο και επαναλαμβάνει tests/GUI πάνω **στα συσκευασμένα αρχεία**, ώστε να εντοπίζει αρχεία ή migrations που λείπουν.
7. Ανοίγει το demo, ελέγχει ότι αποθηκεύτηκαν τρία παραστατικά, ελέγχει SQLite integrity/foreign keys και επανεισάγει τα Excel του ίδιου του ZIP ώστε να αποδεικνύει ότι δεν δημιουργούνται διπλότυπα.
8. Συγκρίνει hashes των συσκευασμένων αρχείων κώδικα με το ελεγμένο source και επιβεβαιώνει ότι ο source δεν άλλαξε κατά τη διάρκεια του ελέγχου. Μόνο τα CMD line endings κανονικοποιούνται για μεταφορά LF/CRLF.
9. Μόνο μετά την επιτυχία δημοσιεύει το νέο ZIP τοπικά, με `VERIFICATION_REPORT.json` μέσα, SHA-256 και εξωτερική αναφορά JSON. Καμία αυτόματη δημοσίευση GitHub ή αποστολή δεδομένων.

## Αποτελέσματα και όρια

Παραγόμενα αρχεία:

- `.local/releases/MiniERP-Checked-Demo.zip`
- `.local/releases/MiniERP-Checked-Demo.zip.sha256`
- `.local/releases/MiniERP-Checked-Demo.verification.json`
- `.local/verification/<run-id>/report.json` και logs κάθε εντολής.

Σε αποτυχία η εντολή επιστρέφει μη μηδενικό exit code και γράφει FAILED report. Δεν αντικαθιστά το προηγούμενο ZIP. Ένα προηγούμενο επιτυχές ZIP δεν πρέπει να παρουσιάζεται ως αποτέλεσμα μιας νεότερης αποτυχημένης εκτέλεσης: ελέγχεται το run-id και το hash της αναφοράς.

Το Linux report αναφέρει ρητά `windows_desktop: NOT_RUN`, `windows_launcher: NOT_RUN`, `ebs_live: NOT_RUN`. Το `--require-windows` αποτυγχάνει σε μηχάνημα Linux. Σε πραγματικά Windows εκτελεί επιπλέον το `START_DEMO.cmd --check`, το οποίο ελέγχει τον launcher σε δικό του προσωρινό συνθετικό data directory. Έτσι δεν βαφτίζουμε μια δοκιμή cloud «ελεγμένο Windows executable». Ο launcher check προετοιμάζει το demo χωρίς να ανοίγει ατέρμονα παράθυρο· οι πραγματικές desktop αλληλεπιδράσεις καλύπτονται από τις χωριστές GUI tests.

Η πραγματική καταχώριση EBS, οι εταιρικοί λογιστικοί κανόνες, η λήψη PDF και η πιστοποίηση παραγωγικής λειτουργίας παραμένουν έξω από αυτό το gate. Το εργαλείο μειώνει σφάλματα παράδοσης και regressions· δεν εγγυάται λογιστική ορθότητα ή απουσία κάθε bug.

## Έλεγχοι του ίδιου του εργαλείου

`tests/test_delivery.py`: απόρριψη άδειας/παραλειπόμενης σουίτας, διατήρηση πραγματικού exit code, timeout, φρέσκα αποτελέσματα runner, syntax/dangerous pattern blocking, διατήρηση απορρήτων στα μηνύματα, package/source manifest και προστασία από δεδομένα εκτός allowlist. Ελέγχεται ότι μια υποχρεωτική αποτυχία δεν αντικαθιστά υπάρχον artifact.
