# Parastio UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox tracking.

**Goal:** Deliver the approved uniform Parastio appearance over the stable P9.2.6 workflow.
**Architecture:** Add isolated UI preferences and table presentation helpers; integrate through the existing table factory and current UI callbacks. Preserve business services/native engine byte-for-byte.
**Tech Stack:** Python 3.12+, Tkinter/ttk, local JSON preferences, packaged PNG, existing verification tooling.
**Spec:** docs/superpowers/specs/2026-10-30-parastio-ui-design.md

## Global Constraints
- Stable reference: stable-2026.10.30-P9.2.6; new source work/parastio/MiniERP-Demo.
- No application/domain/infrastructure/migration edits or production DB/EBS actions.
- Existing MiniERP data location and startup compatibility remain.
- All totals derive from integer minor units of visible model rows.
- Full Windows gate before delivery; announce interactive tests.

## Review Focus
- Hidden/reordered PDF or name columns must resolve displayed column IDs correctly.
- Existing filter context menus and header double-click behavior must remain correct.
- Repeated refresh/resize must not reset saved widths or write financial data.
- Corrupt/read-only preferences and disappearing windows must not crash UI.
- Dark/light themes must preserve readable numeric, selected, disabled and warning states.

### Task 1 — UI preference model and table primitives
Files: app/ui/preferences.py, app/ui/table_presentation.py, tests/test_ui_preferences.py.
- [x] RED: preference round-trip/corruption/invalid layout; display-column resolution; exact visible totals; persisted sort/default validation.
- [x] Implement atomic UI-only persistence and pure width/layout/summary helpers.
- [x] GREEN: backend targeted tests.

### Task 2 — Table behavior and integration
Files: app/ui/table_presentation.py, desktop.py, document_views.py, suppliers.py, counterparties.py, column_filters.py, table_actions.py, ebs_reconciliation.py; tests/gui_regressions.py.
- [x] RED: saved width survives refresh/reopen; optional PDF column does not misroute; selected ID and active filters survive; totals reflect visible rows.
- [x] Implement Auto width / Columns toolbar, safe persistence, sorting, tooltip, summary and displayed-column hit testing.
- [x] GREEN: new GUI checks and existing filter/PDF/header checks.

### Task 3 — Uniform theme, branding, reconciliation presentation
Files: app/ui/theme.py, branding.py, settings.py, desktop.py, docs/branding/parastio-mark.png, app/__init__.py; tests/gui_regressions.py.
- [x] RED: theme persists/reloads; both requested buttons absent; normalized comparison still actionable.
- [x] Implement two coordinated palettes, compact controls, Parastio icon/header, secondary history menu and contextual comparison confirmation.
- [x] GREEN: complete GUI suite including legacy widget selectors.

### Task 4 — Review and delivery
- [x] Fresh-context review vs verified P9.2.6 ZIP; resolve important findings.
- [ ] Assert all business/native/migration bytes unchanged, then full Windows delivery gate on source and extracted ZIP.
- [ ] Publish ZIP/hash/report/guide to new UI branch and downloads without moving stable branch; remote byte/hash verification.
- [ ] Notify test windows closed; report exact checks and EBS NOT_RUN.

## Execution ledger
- User approved the mockup/scope before this plan and selected Parastio. No repeated approval needed for agreed reversible UI implementation.
- No code repository exists inside the packaged source; review uses the original ZIP. GitHub development/delivery branches provide versioned deliverables, leaving the frozen stable branch intact.

- Preflight: 391 backend (2 outdated presentation test doubles corrected); 126 GUI (one old settings-tab expectation updated for Appearance). Targeted rerun: 13 pure tests and 3 GUI passed. New dark/light control-state contrast tests reproduced 55 failing state cases, then both tests passed after explicit ttk color maps. Full frozen-snapshot gate remains required below.
- Reviewer finding resolved: counterparty row replacements now update count/widths and raw-cent totals. Contextual confirmation retains the existing busy/RPA guard.
- User requested stronger dark button visibility during implementation: explicit readable arrows/checkboxes and brighter button surfaces/borders included.
