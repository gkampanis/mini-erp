# Schema: υλοποίηση και roadmap

Οι `migrations/001_initial.sql` και `002_preparation.sql` είναι η εκτελέσιμη πηγή αλήθειας. Η δεύτερη προσθέτει document_preparations(document_id,company_id,nature_group,account_code,note,approved_by,approved_at) με tenant-integrity triggers και ξεχωριστό audit από τα imported δεδομένα. Οι μελλοντικοί πίνακες παρακάτω είναι σχεδιασμός και δεν δημιουργούνται ακόμη.

```mermaid
erDiagram
 companies ||--o{ counterparties : owns
 companies ||--o{ import_jobs : imports
 import_jobs ||--o{ source_records : preserves
 source_records ||--o| documents : originates
 counterparties ||--o{ documents : issues
 companies ||--o{ audit_events : records
 counterparties ||--o| account_mappings : approved
 documents ||--o{ document_lines : future
 documents ||--o{ attachments : future
 companies ||--o{ accounting_periods : future
 companies ||--o{ sync_cursors : future
 companies ||--o{ rpa_jobs : future
 rpa_jobs ||--o{ rpa_job_items : future
```

| Ενότητα | Προτεινόμενα πεδία / constraints μετά την πρώτη τομή |
|---|---|
| accounting_periods | id, company_id, start_date, end_date, state(open/closed), closed_by, closed_at. Απαγόρευση overlapping periods και αλλαγών σε κλειδωμένη περίοδο μόνο μετά χωριστό domain review. |
| counterparties | aliases, role(supplier/customer/both), active, updated_at. company+vat unique, αλλαγές επωνυμίας με audit diff. |
| document_lines | id, document_id, line_no, description, net_minor, tax_minor, gross_minor, account_code nullable, classification_status. unique(document_id,line_no), totals συμφωνούν με header. Χωρίς tax-category autoassignment. |
| attachments | id, company_id, document_id, kind, sha256, storage_path, original_filename, mime_type, byte_size, created_by, created_at. unique(company_id,document_id,sha256), content-addressed paths κάτω από archive root. |
| account_mapping_history | id, company_id, counterparty_id, document_id nullable, old_code, new_code, decision, approved_by, approved_at, reason. Append-only· μόνο explicit approval δημιουργεί recommendation evidence. |
| rpa_jobs | id, company_id, connector_version, mode, status, approved_by, approved_at, created_at. Default connector disabled, queue preview απαραίτητο. |
| rpa_job_items | id, job_id, document_id, status, attempt_id, save_invoked_at, erp_reference, confirmation_evidence, updated_at. unique(job_id,document_id). Crash στην αβέβαιη φάση → uncertain, όχι replay. |
| sync_cursors | id, company_id, connector, cursor, last_success_at, source_version, unique(company_id,connector). Ενημέρωση cursor μόνο μετά atomic persist της σελίδας. |
| payments/settlements | Ξεχωριστό milestone: payment events, currency, counterparties, allocation σε invoices, reconciliation και audit. Όχι εγγραφές γενικού καθολικού. |

Ποσά integer minor units για EUR στο MVP. Μελλοντικά multicurrency χρειάζεται explicit currency scale και migration· δεν θεωρούμε κάθε νόμισμα δύο δεκαδικά. ΑΦΜ/MARK/σειρές/αριθμοί TEXT, dates ISO. Source bytes και raw rows ποτέ overwrite. Για updates σε έγγραφα απαιτούνται versioning, review και before/after audit. Ο λογαριασμός και η φορολογική κατηγοριοποίηση είναι διαφορετικές έννοιες.


## Αναβάθμιση 003 / 004

Η 003 ανακατασκευάζει ατομικά το documents, διατηρώντας IDs, προετοιμασίες,
πηγές και audit. Προστίθεται `rounding_minor` (ακέραιος, -1 έως 1):
`gross_minor = net_minor + tax_minor + rounding_minor`. Η στήλη αφορά μόνο
διαφορά τεκμηριωμένης στρογγυλοποίησης αρχικών δεκαδικών, όχι αυθαίρετο κλείσιμο
ασυμφωνιών ή αυτόματη εγγραφή λογιστικού λογαριασμού στρογγυλοποίησης.

Η 004 προσθέτει:

- `attachments`: company/document, είδος invoice/delivery_note/other, SHA-256,
  σχετική διαδρομή immutable blob, αρχικό όνομα, προέλευση, timestamp.
- `aade_settings`: μόνο εταιρεία, περιβάλλον και timestamp. **Κανένα μυστικό**.
- `rpa_jobs`: εταιρεία, simulation/fill_only, κατάσταση, timestamp.
- `rpa_items`: job/document, snapshot εγκεκριμένων πεδίων, κατάσταση,
  αιτία και timestamp. Η κατάσταση started αποθηκεύεται πριν το input και
  διακοπή μετατρέπεται σε uncertain για χειροκίνητο έλεγχο.

Οι εφαρμογικές υπηρεσίες ελέγχουν εταιρεία πριν επιστρέψουν PDF ή ουρά.
Η SQLite δεν αποτελεί σύστημα εξουσιοδότησης πολλαπλών χρηστών ή κρυπτογράφηση.
