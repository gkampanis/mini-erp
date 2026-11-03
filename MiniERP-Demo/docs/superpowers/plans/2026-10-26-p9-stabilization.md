# Mini ERP P9 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans, with focused implementation and independent final review.

**Goal:** Deliver tested P9 with consistent pending scope/classification, one Excel column interaction, simple posting UI and safe429 handling.
**Architecture:** Reuse existing services, schema, protected rules and import backends. Restrict only the main view; preserve shared Workspace and RPA contracts.
**Tech Stack:** Python, Tk/ttk, SQLite, unittest, mocked AADE/FakeEBS.
**Spec:** ../specs/2026-10-26-p9-stabilization-design.md

## Global Constraints
- Native adapter, RPA engine, Save/New, account mapping algorithm, checkpoint/duplicate guards and schema unchanged.
- No real AADE/EBS calls; synthetic fixtures only.
- Prior source baseline292 backend +91 GUI PASS verified during P8 audit.
- Preserve existing .agents intent-to-add files.

## Review Focus
- Old approved6 documents when card explicitly changes2; preserve protected exceptions and undo after restart.
- Unknown AADE types remain reviewable, known nonfinancial8.6 never financial/RPA.
- Unreconciled visibility must never authorize posting.
- Ambiguous workbook purpose must never import EBS evidence as new documents.
- In-flight HTTP pagination/retry must observe another call’s429; wait cannot shorten.

### Task1 — Classification and supplier defaults
Files: domain/invoice_types.py, application/{supplier_purchases,supplier_accounts,counterparties,workspace}.py and dedicated tests.
- [x] Reproduce failures in tests before implementation.
- [x] Reuse precise financial predicate, account_group and existing purchase rules, transactions, undo.
- [x] Test months/companies/environments/future XLSX/ODS/AADE, old approvals/protected queues, persistence and rollback.

### Task2 — AADE cooldown
Files: infrastructure/aade/client.py, ui/aade_dialog.py and dedicated tests.
- [x] Write failing normalized-key/inflight/deadline/partial-display tests.
- [x] Minimal state lock + per-request check + max deadline; preserve correct Sync stop/PDF suppression.
- [x] Verify initial/page2/concurrent429, safe reruns and no credential leaks.

### Task3 — Stable pending view and posting UI
Files: ui/desktop.py, ui/rpa_panel.py, GUI tests.
- [x] Failing tests for immutable allowed rows across dropdown/search/reset/refresh, unresolved visibility and8.6.
- [x] Apply predicate before filters, remove registered scope switch, existing labels for unresolved; no RPA readiness relaxation.
- [x] Wire batch limit40 using existing engine API; preserve selected/one/FakeEBS sequences and pause/resume.
- [x] Remove redundant account approval popup; preserve explicit action and backend confirmations.

### Task4 — Excel interaction
Files: ui/excel_mapping.py, ui/{desktop,ebs_reconciliation}.py, tests.
- [x] Document current distinct stages/data/formats/call sites.
- [x] Shared column widget and single entry; recognize known format, saved mappings scoped by company/environment/stage; same-window raw recheck.
- [x] Preserve all raw fields and EBS date+five values, company/completeness guard; no second mapping during same import.
- [x] Verify XLSX/ODS, repeated imports/deduplication, unknown fields and no source mutation.

### Task5 — Review and delivery
- [x] Independent code/spec review and targeted fixes.
- [ ] Full backend/GUI source suites and extracted ZIP delivery gate with zero skips.
- [x] GUI screenshot inspection; compare protected baseline SHA256 and schema.
- [ ] P9 version/changelog/rollback, commit/tag, verified GitHub ZIP with SHA256/report.
- [ ] Explicit Windows/EBS live NOT_RUN.
