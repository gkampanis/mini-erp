# Automatic Filter Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax.

**Goal:** First trial followed automatically by every eligible filtered record, without pilot activation or replay.
**Architecture:** Reuse the existing queue, item state and resume API. Remove pilot cap/activation, derive first_record_done from recorded execution, and let the UI continue successful checkpoint boundaries.
**Tech Stack:** Existing Python/Tkinter/SQLite/unittest; no new dependency.
**Spec:** docs/superpowers/specs/2026-10-25-automatic-filter-batch-design.md

## Global Constraints

Native adapter and _advance_saved stay unchanged. Only explicit start authorizes posting. Save is not proof of EBS persistence. Preserve tenant, group-2, duplicate and uncertainty protections. Preserve user Pause/Stop.

## Review Focus

- Unverified profile must execute all 13, without stamping pilot_at or storage verification.
- First Save/New failure must stop with no second record or replay.
- The filtered snapshot must exclude other suppliers and survive row removal after posting.
- Successful record 40 must advance to 41 through the existing resume API.
- User Pause/Stop must override automatic continuation.

### Task 1: Automatic batch semantics and delivery

Files: app/application/rpa.py (posting/create/progress), app/ui/rpa_panel.py (scope and scheduling), tests/test_posting_actions.py and tests/gui_regressions.py; version app/__init__.py.
Interface: retain posting/create/advance signatures. progress adds boolean first_record_done; native methods unchanged.

- [ ] Write and run failing backend/GUI tests for unverified 13-record auto batch, first failure, full filtered scope and 40→41.
- [ ] Remove pilot_at execution gate and single cap; derive first_record_done without claiming storage verification.
- [ ] Queue the full visible scope; automatically resume only the successful Save checkpoint, respecting explicit Pause/Stop.
- [ ] Run targeted tests, then the full delivery gate against source and extracted ZIP.
- [ ] Commit, obtain a fresh read-only review, resolve material findings with tests, verify and upload the final artifact.
