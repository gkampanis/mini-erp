# Συμβόλαια πρώτης τομής

`preview(path, manual_mapping=None) -> Preview`: immutable original bytes και SHA256, επιλεγμένο sheet, headers, mapping (field → zero-based column), valid records, rejected rows με αριθμό και αιτία. Το object είναι μεταβλητό για UI, αλλά η υπηρεσία ξαναδιαβάζει τα bytes με το επιβεβαιωμένο mapping και ελέγχει hash πριν commit. Δεν εμπιστεύεται normalized values από UI. Το preview δεν γράφει στη βάση.

`ERP.commit_import(company, preview, confirmed=True) -> report`: explicit approval, archive πρώτα, μετά μία atomic SQL transaction για job, source rows, counterparties, documents, audit. Rollback μπορεί να αφήσει αχρησιμοποίητο hash-addressed source blob, όχι μερικό παραστατικό. Idempotency στο business key και στο MARK ανά εταιρεία. Ίδια identity με διαφορετικά ποσά/metadata → conflict, όχι update. Πολλαπλά import attempts διατηρούνται ως ξεχωριστά jobs.

`ERP.search(company, query)` και `ERP.detail(company, id)`: scoped στην εταιρεία, επιστρέφουν ποσά σε integer cents. Ελληνικό casefold search στην application layer· για μεγαλύτερα datasets χρειάζονται pagination και FTS. Καμία υπόσχεση multiuser από SQLite desktop.

## Επεκτάσεις (σχεδιασμός, όχι υλοποιημένες APIs)

- Mapping service: μόνο `user_approved` αποφάσεις με actor/timestamp/history. Conflicts και άγνωστα ΑΦΜ → Needs Review. UI progress του legacy δεν γίνεται λογιστική έγκριση.
- PDF archive: ελεγχόμενο μέγεθος/τύπος, SHA256 bytes, ασφαλές content-addressed path, link σε εταιρεία/παραστατικό, duplicate handling και backup manifest. Όχι arbitrary filename paths.
- myDATA: αρχικά read-only, με τρέχουσα επίσημη AADE REST/XSD προδιαγραφή κατά την υλοποίηση. Pagination, cursors, retry/backoff, raw XML retention, credentials σε OS keyring. Κανένα endpoint/credential δεν επινοείται εδώ.
- EBS: Windows-only isolated adapter, disabled by default, χωρίς direct DB writes. States queued → started → save_invoked → confirmed_in_erp ή uncertain/failed/skipped. Confirmation απαιτεί authoritative readback ή ρητό ελεγμένο operator evidence, όχι νέο TED. Μετά crash πριν επιβεβαίωση → uncertain, ποτέ blind replay. Ξεχωριστές acceptance tests και έγκριση πριν activation.
- Diagnostics: καταγραφή exception type/context και προαιρετικά process metrics χωρίς invoice payloads/secrets σε γενικά logs. Audit δεδομένων μόνο εντός προστατευμένης τοπικής βάσης.


## Τοπική προετοιμασία (υλοποιημένη)

`ERP.prepare_document(company,id,group,account_code,note='',actor='local_operator',confirmed=False)` απαιτεί `confirmed is True`, ομάδα `'2'/'6'`, συμβατό συντακτικά account prefix και actor. Επιστρέφει την εγκεκριμένη απόφαση με UTC timestamp. Η `ERP.preparation(company,id)` επιστρέφει dict ή None. Ο λογαριασμός δεν επικυρώνεται στο πραγματικό EBS και καμία λειτουργία δεν κάνει posting. Η απόφαση και το before/after audit είναι atomic, tenant scoped και ξεχωριστά από imported fields.

`ERP.import_reviews(company)` επιστρέφει newest-first jobs με parsed reports και counts. Το search διατηρεί τα αρχικά πεδία και προσθέτει `nature_group`, `account_code`, `prepared_at`. Οι μη δεσμευτικές duplicate warnings αποθηκεύονται σε report/audit και δεν αλλάζουν exact duplicate/conflict handling. Το `document_preparations` δεν είναι supplier mapping ή journal.
