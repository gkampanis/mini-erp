# Έρευνα GitHub: παραστατικά, import και ασφαλής ροή προς EBS

Ημερομηνία έρευνας: 2026-10-21. Στόχος: επιλεγμένες ιδέες για το υπάρχον Mini ERP ως **χώρο προετοιμασίας και ελέγχου εισαγωγών στο EBS**, όχι αντικατάσταση του EBS ή αντιγραφή ενός ολόκληρου ERP.

Η έρευνα έγινε με read-only `git ls-remote` για branch SHAs και με λήψη συγκεκριμένων README, manifests και source files από `raw.githubusercontent.com`. Δεν εγκαταστάθηκαν ή εκτελέστηκαν τα τρίτα συστήματα, δεν έγινε clone/merge και δεν αντιγράφηκε κώδικάς τους στο app. Τα σημεία παρακάτω είναι παρατηρήσεις από τα συγκεκριμένα αρχεία, όχι πιστοποίηση της συμπεριφοράς ολόκληρων των συστημάτων. Το GitHub API ήταν μη προσβάσιμο μέσω του cloud proxy, αλλά οι επαληθευμένες raw πηγές και οι Git αναγνώσεις ήταν διαθέσιμες.

## Πηγές και άδειες

| Έργο | Branch / επαληθευμένο SHA | Σχετική άδεια |
|---|---|---|
| [Frappe ERPNext](https://github.com/frappe/erpnext) | `develop` / `b6336b8145e680a9807a1be8695aa792f9be722f` | GPL-3.0, από source header και [license.txt](https://github.com/frappe/erpnext/blob/b6336b8145e680a9807a1be8695aa792f9be722f/license.txt) |
| [OCA account-invoicing](https://github.com/OCA/account-invoicing) | `18.0` / `7c5bf446011ca58461abbe02cf5ba23cd9e9247b` | Τα δύο modules που εξετάστηκαν δηλώνουν AGPL-3 στα manifests, όχι ενιαία υπόθεση για όλο το repository |
| [OCA bank-statement-import](https://github.com/OCA/bank-statement-import) | `18.0` / `3bdccd4de5896181d59f0451633539112c265a80` | `account_statement_import_file`: LGPL-3, [manifest](https://github.com/OCA/bank-statement-import/blob/3bdccd4de5896181d59f0451633539112c265a80/account_statement_import_file/__manifest__.py), έκδοση `18.0.1.0.3` |
| [OCA queue](https://github.com/OCA/queue) | `18.0` / `4ccc50b153fdfd4ea48292978070043cda2e9aee` | `queue_job`: LGPL-3, [manifest](https://github.com/OCA/queue/blob/4ccc50b153fdfd4ea48292978070043cda2e9aee/queue_job/__manifest__.py) |
| [Dolibarr](https://github.com/Dolibarr/dolibarr) | `develop` / `59d018f5755e391a142e1554b47c0df259534116` | GPL-3.0 κείμενο [COPYING](https://github.com/Dolibarr/dolibarr/blob/59d018f5755e391a142e1554b47c0df259534116/COPYING) |

Οι άδειες ελέγχθηκαν πριν αποφασιστεί η χρήση μόνο λειτουργικών ιδεών. Καμία νέα εξάρτηση από ERPNext/Odoo/Dolibarr, κανένα source reuse ή μεταφορά των δικών τους accounting rules. Μελλοντική εισαγωγή δικού τους κώδικα θα απαιτούσε νέο έλεγχο συμβατότητας αδειών.

## Παρατηρήσεις που έχουν πρακτική αξία

### 1. ERPNext: supplier reference και καθαρά στάδια παραστατικού

Πηγή: [`purchase_invoice.py`](https://github.com/frappe/erpnext/blob/b6336b8145e680a9807a1be8695aa792f9be722f/erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py), μέθοδος `validate_supplier_invoice`, και [`purchase_invoice.json`](https://github.com/frappe/erpnext/blob/b6336b8145e680a9807a1be8695aa792f9be722f/erpnext/accounts/doctype/purchase_invoice/purchase_invoice.json).

Ο έλεγχος μοναδικότητας supplier invoice, όταν ενεργοποιείται, εξετάζει `bill_no`, supplier και fiscal year, εξαιρώντας cancelled documents. Το μοντέλο διαθέτει διακριτά business statuses όπως Draft· η ύπαρξη εισαγμένου record δεν σημαίνει ολοκληρωμένο posting.

**Στο Mini ERP:** διατηρούμε ξεχωριστή ταυτότητα του παραστατικού του προμηθευτή, raw πηγή και business review state. Η εισαγωγή Excel δεν πρέπει να δείχνει «καταχωρίστηκε στο EBS». Η προετοιμασία, η έγκριση και η αποστολή/επιβεβαίωση ERP είναι διαφορετικά στάδια. Δεν μεταφέρονται αυτόματα κανόνες fiscal year ή posting από ξένο ERP στην ελληνική εγκατάσταση.

### 2. OCA: προφανής προστασία από διπλό supplier invoice

Πηγές: [`account_invoice_supplier_ref_unique/README.rst`](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_supplier_ref_unique/README.rst), [`models/account_move.py`](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_supplier_ref_unique/models/account_move.py), [manifest](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_supplier_ref_unique/__manifest__.py), έκδοση `18.0.1.0.0`.

Ο supplier invoice number ελέγχεται χωρίς διάκριση κεφαλαίων/πεζών για τον ίδιο commercial partner. Η αιτία του ελέγχου είναι πρακτική: διπλό τιμολόγιο μπορεί να οδηγήσει σε διπλή πληρωμή.

**Στο Mini ERP:** πέρα από το υπάρχον exact business key και MARK, αξίζει συντηρητικός έλεγχος πιθανού διπλοτύπου σε ίδια εταιρεία/αντισυμβαλλόμενο/σειρά/αριθμό με casefold και trim. Η διαφορετική ημερομηνία δεν αρκεί για να θεωρηθεί νέο τιμολόγιο. Επειδή αριθμοί μπορεί να επαναλαμβάνονται ανά περίοδο, χρειάζεται ορατή εξαίρεση προς έλεγχο, όχι αυτόματο merge ή καθολική απαγόρευση. Δεν τροποποιείται η αρχική τιμή της πηγής.

### 3. OCA: επαληθευτικό σύνολο και εμφανής διαφορά

Πηγές: [`account_invoice_check_total/README.rst`](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_check_total/README.rst), [`models/account_move.py`](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_check_total/models/account_move.py), [manifest](https://github.com/OCA/account-invoicing/blob/7c5bf446011ca58461abbe02cf5ba23cd9e9247b/account_invoice_check_total/__manifest__.py), έκδοση `18.0.1.0.0`.

Το module προσθέτει Verification Total από το έντυπο του προμηθευτή, συγκρίνει με το υπολογισμένο total και εμφανίζει σαφή διαφορά πριν επιτρέψει posting όταν ο έλεγχος είναι ενεργός.

**Στο Mini ERP:** ο υπάρχων έλεγχος `gross = net + tax` παραμένει αυστηρός. Η προεπισκόπηση πρέπει να δείχνει καθαρή/ΦΠΑ/σύνολο μαζί, ο αριθμός εξαιρέσεων να φαίνεται πριν την εισαγωγή και να υπάρχει καθαρή αιτία ανά γραμμή. Αν το gross λείπει και προκύπτει αριθμητικά, αυτό δεν αποτελεί ανεξάρτητη επαλήθευση του PDF. Δεν μεταφέρεται η χρήση float του Odoo στο δικό μας domain: παραμένουν Decimal και cents.

### 4. OCA bank import: κοινό import pipeline και idempotent επανεισαγωγή

Πηγές: [`account_statement_import_base/README.rst`](https://github.com/OCA/bank-statement-import/blob/3bdccd4de5896181d59f0451633539112c265a80/account_statement_import_base/README.rst), [`account_statement_import_file/README.rst`](https://github.com/OCA/bank-statement-import/blob/3bdccd4de5896181d59f0451633539112c265a80/account_statement_import_file/README.rst).

Το base module διαχωρίζει το κοινό import από file και online adapters. Το file wizard περιγράφει επιλογή αρχείου και αποφυγή δεύτερης δημιουργίας ήδη εισαγμένων transactions.

**Στο Mini ERP:** κρατούμε ένα κοινό application import service και διαφορετικούς adapters όταν προστεθούν πηγές. Στην παρούσα έκδοση βελτιώνουμε μόνο την υπάρχουσα Excel διαδρομή: στάδια «Αρχείο → Αντιστοίχιση → Έλεγχος → Αποτέλεσμα», με ξεχωριστούς αριθμούς νέων/διπλοτύπων/εξαιρέσεων. Δεν προσθέτουμε banking module ή νέα API connectors.

### 5. OCA queue: identity key και έλεγχος πριν την εκτέλεση

Πηγή: [`queue_job/README.rst`](https://github.com/OCA/queue/blob/4ccc50b153fdfd4ea48292978070043cda2e9aee/queue_job/README.rst), ενότητες Job Properties, Retry Pattern και Tips and Tricks.

Τα jobs αποθηκεύονται στη βάση, εκτελούνται σε δική τους transaction, μπορούν να έχουν identity key και οι οδηγίες τονίζουν idempotency και relevance check στην αρχή της εκτέλεσης.

**Στο Mini ERP:** χρήσιμο πρότυπο για την αποθηκευμένη μελλοντική ουρά EBS, με `document_id`, μοναδική ταυτότητα attempt, ορατή κατάσταση και επανέλεγχο έγκρισης πριν γίνει write. Όμως τα γενικά retries δεν είναι ασφαλή για RPA: μετά από αβέβαιο Save δεν γνωρίζουμε αν έγινε εξωτερικό commit. Αυτή η κατάσταση πρέπει να μείνει `uncertain` και να ζητά έλεγχο, όχι να κάνει αυτόματο retry. Δεν χρειάζεται να εγκαταστήσουμε PostgreSQL/Odoo/queue_job για το single-user desktop.

### 6. Dolibarr: business card και συνημμένα σε διακριτή καρτέλα

Πηγές: [`fournisseur.facture.class.php`](https://github.com/Dolibarr/dolibarr/blob/59d018f5755e391a142e1554b47c0df259534116/htdocs/fourn/class/fournisseur.facture.class.php), [`fourn/facture/document.php`](https://github.com/Dolibarr/dolibarr/blob/59d018f5755e391a142e1554b47c0df259534116/htdocs/fourn/facture/document.php).

Το μοντέλο vendor invoice διακρίνει supplier reference και business status. Η document page συνδέεται με συγκεκριμένο supplier invoice και παρουσιάζει συνημμένα/metadata σε ξεχωριστό document context.

**Στο Mini ERP:** στο detail χωρίζονται ευανάγνωστα «Στοιχεία», «Προέλευση», «Ιστορικό», αντί ενός ενιαίου JSON/text dump. Όταν υλοποιηθεί το πραγματικό PDF/δελτίων archive, θα προστεθεί λειτουργική καρτέλα «Αρχεία» με document links. Δεν προτείνεται κενή ή παραπλανητική καρτέλα download πριν υπάρχει πραγματική πηγή και ασφαλής file service.

## Μικρές εφαρμογές που αξίζουν τώρα

1. **Αναγνώσιμη ροή import** με ξεχωριστά στάδια, summary έγκυρων/εξαιρέσεων και πλήρη row reasons, διατηρώντας χειροκίνητο mapping και ρητή επιβεβαίωση.
2. **Κανονικό ERP master/detail**: κύρια λίστα με καθαρή αναζήτηση και detail σε tabs στοιχείων, προέλευσης και ιστορικού. Επιστροφή σε ίδια αναζήτηση/επιλογή μετά import.
3. **Σαφή αποτελέσματα επανεισαγωγής**: νέες εγγραφές, διπλότυπα και συγκρούσεις δεν συγκεντρώνονται σε έναν ασαφή μετρητή «επιτυχίας».
4. **Συντηρητικό warning για near-duplicate** supplier reference όταν αλλάζουν ημερομηνία ή πεζά/κεφαλαία, με raw/source evidence, χωρίς αυτόματο overwrite. Αν προστεθεί τώρα, απαιτεί regression tests και tenant scope.
5. **Ορατά όρια EBS**: ό,τι έχει εισαχθεί τοπικά παρουσιάζεται ως τοπικό/προς έλεγχο. Οι μελλοντικές κλάσεις ομάδας 2/6, η έγκριση και το ERP confirmation είναι ξεχωριστές έννοιες. Δεν προστίθεται εικονικό «Send to EBS» που δεν κάνει πραγματική επιβεβαιωμένη λειτουργία.

## Τι δεν δικαιολογείται από την έρευνα

Δεν απαιτείται αλλαγή σε web framework, αντιγραφή ολόκληρου ERP UI, αποθήκη, CRM, νέοι λογιστικοί κανόνες, banking, αυτόματο posting ή νέα third-party runtime dependencies. Η έρευνα δεν επαληθεύει ελληνικές λογιστικές διατάξεις, myDATA APIs ή το πραγματικό EBS UI. Οι επιλεγμένες βελτιώσεις πρέπει να ελεγχθούν με τα υπάρχοντα synthetic fixtures και desktop smoke test ώστε η αλλαγή UI να μην υποβαθμίσει mapping, duplicate handling, atomic imports ή audit.
