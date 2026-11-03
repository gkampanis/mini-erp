# Σύμβολον ERP Implementation Plan

> Use superpowers:executing-plans inline in the current chat, with a fresh final reviewer. Track every completed test cycle below.

**Goal:** Preserve exact AADE detail values, remember creditor VAT accounts, and post the corresponding rows in one TED.
**Architecture:** Add a focused detail extractor and application service over existing archived XML/record_json. Add company-scoped VAT rules and optional multirow payloads; preserve the original single-row path and Save/New sequencing.
**Tech Stack:** Existing Python/Tk/SQLite/Decimal; no new runtime library.
**Spec:** ../specs/2026-10-30-symbolon-lines-design.md (approved).

## Global Constraints
- Separate source extracted from verified P9.3.0; frozen P9.2.6 and existing installations untouched.
- No production writes or automated live EBS/AADE calls. User chooses all accounts.
- No tax-policy interpretation. Purchase group 2 remains outside RPA.
- Preserve source lines, amounts, categories and exemptions without guessed allocation or silent rounding.
- Full Windows source+ZIP gate and verified GitHub delivery required.

## Review Focus
- Missing lines must remain distinguishable from valid single-rate analysis.
- Archived page association must be invoice/company/environment scoped and hash checked.
- Account/rule/source edits must invalidate stale queued multirow snapshots.
- Second-row failure must never reach Save or overwrite the first row.
- UI changes must retain posting actions and original single-row behavior.

### Task 1: Exact detail ingestion
Files: app/infrastructure/aade/lines.py (new), aade/client.py, tests/test_mydata_lines.py (new).
Interface: extract_lines(invoice_element) -> dict with version/status/raw lines/normalized integer-cent lines/errors. Normalize all source details, retain XML strings for provenance, validate ordinary line net/VAT sums against summary; classify unsupported special data explicitly without tax-policy guesses.
- [x] RED: namespaced and escaped two-rate example yields 12638/3033 and 200600/0 with categories 1/7 and exemption27; summary213238/3033/216271.
- [x] RED: missing details, duplicate numbers, invalid decimals, >2 decimal places, unknown VAT category, category8 versus7, inconsistent totals, special source lines.
- [x] Implement extraction and attach as detail_analysis in parsed_page records, keeping current summary fields and raw archiving behavior.
- [x] GREEN: 38 tests via tests.test_mydata_lines, test_workflow, test_aade_import, test_unified_workspace. Read-only archive replay: verified4156, unsupported6, zero analysis errors.

### Task 2: Archived analysis and account rules
Files: app/application/vat_lines.py (new), migrations/017_counterparty_vat_rules.sql (new), tests/test_vat_lines.py (new).
Interface: VATLines(erp).analysis(company,document); .requirements(company,documents); .save_rules(company,counterparty,rules,confirmed); .posting_lines(company,document,primary_account).
- [x] RED: matched current record analysis or exact archived recovery; tenant/environment/MARK/hash boundaries and idempotence.
- [x] RED: first-use missing secondary, saved reuse, primary reference vs fixed secondary, changed rule/source snapshot, unchanged registered history.
- [x] Implement minimal scoped persistence and exact source-line account resolution; retain existing approvals.
- [x] GREEN: targeted service/migration/queue tests.

### Task 3: Multirow RPA and first-use UI
Files: rpa.py, ebs_adapter/adapter.py, ebs_workspace.py, ui/rpa_panel.py, ui/vat_accounts.py (new), suppliers.py/counterparties.py; tests/test_multiline_rpa.py and GUI tests.
- [x] RED: first-row sequence unchanged; header once, explicitly mapped following rows, account/net focus on each, exact source amounts, one Save/New.
- [x] RED: missing mapping detected before typing; row2 failure no Save; source/rule edit freshness; first-use prompt and saved reuse.
- [x] Implement optional detail_lines payload and additional mapped row positions. Keep old payload/adapter path for no multirow analysis.
- [x] Integrate first-use account prompt before queue planning, plus creditor rule editing; use existing continue/keep-pending behavior on issues.
- [x] GREEN: targeted engine/application/GUI tests plus original posting suites.

### Task 4: Branding, dominant list and delivery
Files: ui/branding.py, desktop.py, theme.py, docs/branding, app/__init__.py, README/docs, GUI regressions.
- [x] Change display name to Σύμβολον ERP; original modern mark, internal paths/startup unchanged.
- [x] Recover list height by compacting chrome and idle status, preserving all actions and readable arrows.
- [x] Review complete change fresh; resolve important findings with regression evidence.
- [ ] Full Windows delivery gate, source and extracted ZIP, zero required skips.
- [ ] Upload verified ZIP/hash/report/guide to new development branch and downloads; preserve stable branches; verify remote bytes.

## Ledger
- Approved design and permission to proceed are explicit. Continue inline without repeat approval.
- Read-only actual XML evidence and aggregate audit remain in work/, not in package fixtures. Test amounts may reproduce the supplied example with synthetic identities only.
- Each completion entry records the command/result; no completion claim before current verification.

- Task1 RED→GREEN: 10 tests initially failed (missing extractor/API analysis), then passed. Added a precision regression with >28 significant digits; reproduced silent Decimal-context rounding, then fixed by integer coefficient/exponent conversion. 38 targeted integration tests passed.
- Task2 initial RED→GREEN: 7 new service tests passed, including old archive recovery without writes, corrupt hash, tenant scope, approval requirement, rule reuse/primary-reference update, unchanged document/approval. Further queue/source cases remain.
- Task3 initial RED→GREEN: 6 new adapter/payload tests failed before implementation, now 32 tests including original workspace/workflow pass. Native multirow uses explicit row mapping, original fill_sequence for first row, separate verified editors for following rows. Save/New code unchanged. UI mapping capture, first-use dialog and final full regression remain.
- Ruling: old archived detail recovery stays read-only and hash checked; no financial backfill writes needed. New RequestDocs ingestion persists detail_analysis naturally in record_json.
- Ruling: follow operator keep-it-simple scope; no voucher tax-policy interpretation. Explicitly unsupported source types remain distinguishable, with no inferred data.

- Additional verification: 13 service/grouping tests passed after regression RED→GREEN for missing archive preventing mixed-VAT downgrade. A second regression RED→GREEN verifies purchase/registered exclusions before the first-use VAT dialog; combined service/multirow suite 23 passed.
- GUI targeted tests: 3 first-use/mapping tests passed; 5 layout/branding/contrast tests passed after dominant-list regression RED→GREEN (old list 26% of 900px; new at least57%). Final full gate remains required.
- Fresh read-only review found two issues above; both addressed. No live EBS or production writes performed.

- Fresh follow-up reviewer ran 33 extraction/service/multirow tests: all passed, no remaining P1/P2. First full gate ran424 backend tests and stopped on7 filter fixture errors (new footer collaborator absent in __new__ fixture); corrected fixture,7 targeted filter tests passed. Full gate rerun required.

- Second gate:424 backend passed;133 GUI ran with132 passed and1 stale isolated routing test failed because synthetic IDs bypassed the new VAT preflight. Updated routing fixture to stub/verify that preflight while retaining real VAT preflight coverage in DesktopRegressions and service tests. Targeted routing test passed. No application code changed after first gate except previously reviewed fixes. Full fresh gate required.

- User requested deeper structural review of all affected boundaries and no needless runtime controls. Fresh data/RPA/XML reviews found and fixed: canonical MARK metadata loss and cross-page duplicate conflict; later missing-detail refresh downgrade; prompts on unapproved/rounding records; PDF-URL-only refresh falsely invalidating queues. Every behavioral fix had a reproduced regression; latest69 targeted tests passed, then50 including real queue orchestration with fake backend passed.
- Added repeatable seeded1000-scenario/3000-corrupt-mutation test, independent Decimal oracle. External lxml official XSD check: all15611 financial detailrows valid, full envelope4of6 conform with4peripheral deviations on2pages; six envelopes parsed, one outside scope. Aggregate evidence only.
- User confirmed no success indicator or extra success confirmations desired; preserve successful20261025/P9.2.6 native Save/New flow. Save AST verified against original ZIP gitblob2f145453244037adaa08ccf9e8c26c750ea64342; current session byte-identical P9.3.0. Timing limitations documented, actualEBS NOT_RUN.

- Expanded backend probe ran442 tests:440passed and2synthetic summary-only fixture errors. Corrected shared synthetic AADE response to include its actual one-rate invoiceDetails rather than weaken missing-source protection. Latest81 targeted type/monthly/workflow/XML/VAT tests passed. Full source+package gate now rerun.

- Follow-up structural rounding observation found238single-signature source invoices where aggregate rounding differs from exact source-line sum. No such difference among26existing expense-account candidates. Reproduced service early-return loss RED, fixed by primary-account row compaction and baseline one-row fallback only when exact VAT conserved; no new VAT-rule prompts or typing.35reviewer/77targeted tests passed. Previous full gate was deliberately halted before delivery for this follow-up; fresh complete gate required.

- Final transition regression: saved secondary VAT account also applies to later single-category invoices, using original five-point mapping and one Save. Configured unknown category asks once; untouched single-category creditors retain legacy behavior. Queued payloads rebind on explicit rule edits; attempted history remains unchanged. Fresh reviewer ran69 tests plus a secondary-only queued edit probe without P1/P2 findings. Full fresh gate required after this fix.
