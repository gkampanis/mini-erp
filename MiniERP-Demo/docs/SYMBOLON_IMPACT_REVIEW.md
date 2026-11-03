# P9.4.0 structural impact review

Approved scope: exact AADE invoice lines, accounting/VAT accounts, explicitly mapped extra rows in one TED, dominant list and Σύμβολον ERP branding. No tax-policy/voucher interpretation or new ERP modules.

## Boundary coverage

| Boundary | Evidence and invariant |
| --- | --- |
| Official XML → parser | Namespaces/escaped wrappers, canonical numeric MARK, duplicate/cross-page financial conflicts, cancellation normalization; originals retained. test_mydata_lines, test_workflow, test_cancellation_retention. |
| Parser → snapshots/documents | Conflicts rejected before archive/DB writes; company/recipient/environment scoped identity. Exact-cent summaries, original details, immutable archives. test_vat_lines, test_aade_import, existing association suites. |
| Refresh/old records | Linked, hash-checked archive recovery without financial backfill; missing/corrupt archives and later missing details cannot silently downgrade to total-net posting. Excel without associated AADE record retains prior behavior. |
| Creditor → document/queue | Primary account reference follows approved document/card behavior; secondary rule is explicit and company/environment/creditor/VAT scoped. Queued snapshots rebind; attempted and registered history remains unchanged. |
| Preflight eligibility | Purchases/group2, outgoing, excluded types, registered, unapproved without eligible supplier default and rounding-review documents do not require irrelevant VAT choices. |
| Queue freshness | Financial source fingerprint excludes PDF URLs/names/raw serialization. Real amounts/category/exemption/account changes remain relevant. Archived raw bytes are still independently hash checked. |
| RPA first/additional rows | Original first-row fill_sequence unchanged; all explicit row positions validated before input. Following account/net editors must be on the intended mapped row. Failure before Save retains existing continue/skip flow. |
| Save/New/continuation | One header/Save per invoice; New between documents; no automatic failed-invoice replay. Original session.py remains byte-identical to P9.3.0/P9.2.6. No new success confirmation. |
| EBS reconciliation | Mixed-VAT invoice matches a single exported invoice-total row. Split exported accounting rows without authoritative grouping remain review, never false absence or guessed registration. Existing conservative matching unchanged. |
| UI | Dense layout, list uses at least57% normal-window height; narrow-window actions accessible; themed arrows/buttons and column filters retained. Existing row IDs and posting selections preserved. |
| Upgrade | Isolated source; migration017 adds only scoped VAT rules. Same data directory and launcher. Old stable Git branch and production install untouched. |

## Independent checks

Official XSD v2.0.2 ZIP source: https://www.aade.gr/sites/default/files/2026-09/v2.0.2XSDs_0.zip
SHA256 feaf90afc57150c841ad7ef73edbe181b3eac22dfb189b3cb5d54d6fdb85154e.
All15611 original detail rows passed the independent lxml schema check. Four of six full invoice envelopes conform; two contain four peripheral element-content deviations (classifications, packing declarations, cancellation extension). All six are accepted by the existing parser; no source XML rewritten or discarded to force schema conformance. One additional archive is outside invoice-envelope scope. No identities/values exported in the aggregate report.

Read-only monetary replay:4162 unique invoices,4156 verified ordinary sums,6 explicitly unsupported special recType cases, zero analysis errors. No live AADE request.

Seeded property/mutation coverage is included in tests/test_vat_line_properties.py:1000 valid mixed-category scenarios, independent Decimal HALF_UP oracle, exact per-account/category/exemption cent conservation and complete source-line coverage;3000 corrupt variants rejected. No new runtime dependency.

Fresh independent reviews covered source association, data impact, RPA/focus/continuation and runtime prompts. Confirmed issues were reproduced before changes and regression tested: archive loss downgrade, missing-detail refresh downgrade, canonical MARK metadata loss, duplicate-MARK wrong analysis, unrelated PDF refresh blocking and prompts for excluded/unready records.

## Timing research and practical boundary

Verified the user's working20261025 ZIP against Git blob2f145453244037adaa08ccf9e8c26c750ea64342. Its save() AST matches the current native implementation: Save click,1.3s wait, health check. New form uses12s observation with0.6s stable active form. The stable P9.2.6 activation retry remains intact. No arbitrary timing change or new success popup was introduced.

A synthetic delayed-save model exposes an existing limitation: if EBS ignores New while asynchronous Save is still busy, the one New click can be lost. Window readiness or longer sleep cannot establish committed database persistence. Actual EBS timing/input was NOT_RUN; retain reconciliation evidence or existing operator confirmation semantics. Microsoft describes framework-dependent idle timing: https://learn.microsoft.com/en-us/dotnet/api/system.windows.automation.windowpattern.waitforinputidle

The full current-source and extracted-ZIP Windows delivery gate remains the publication requirement. Its companion verification JSON is authoritative for final counts/status; targeted review results alone are not delivery approval.

Read-only existing EBS export audit:148data rows,140normalized rows,8with identity issues (6missing reference,3missing/invalid VAT,1overlap). Valid rows have no repeated supplier/reference/date groups. These missing identities are not filled by guessing from AADE, and are not evidence about future multirow exports. Existing scoped review behavior is retained.

Rounding follow-up: across all read-only source invoices,238ordinary single-signature invoices have exact individual standard HALF_UP VAT but a different aggregate rounded VAT. A later focused check of26existing incoming expense-account candidates found no such deviation. These populations are distinct and do not prove actual EBS behavior. Single-signature posting now preserves original same-primary-account rows when compaction changes VAT, with no new rule prompt; exact aggregation retains the baseline one-row path. 35independent reviewer tests and77targeted tests passed. Source VAT differs from standard HALF_UP in640other invoices/659lines; these are diagnostic observations, not declared source errors or new runtime blocks. EBS VAT remains automatically calculated; no VAT-field typing added. Official EBS document-type settings can influence total-versus-line rounding: https://wiki.entersoft.eu/wiki/EBS-DocumentType_EL.

- Final transition regression: saved secondary VAT account also applies to later single-category invoices, using original five-point mapping and one Save. Configured unknown category asks once; untouched single-category creditors retain legacy behavior. Queued payloads rebind on explicit rule edits; attempted history remains unchanged. Fresh reviewer ran69 tests plus a secondary-only queued edit probe without P1/P2 findings. Full fresh gate required after this fix.
