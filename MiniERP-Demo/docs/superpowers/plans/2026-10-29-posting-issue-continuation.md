# Posting Issue Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove history-based posting locks and ask the operator whether to continue after a runtime issue.
**Architecture:** Keep native fill/Save/New; separate reconciliation evidence from attempt display; return structured issue context to Tk and use an explicit continuation scheduling action.
**Tech Stack:** Python, Tk, SQLite, existing Windows RPA adapter.
**Spec:** ../specs/2026-10-29-posting-issue-continuation-design.md

## Global Constraints
- Group 6 only; preserve tenant scope, real EBS evidence, immutable attempt history and mapping/net-focus checks.
- No production database writes or EBS actions while developing/testing.
- Failed documents remain pending; a possibly sent Save is disclosed, never treated as verified storage.
- ZIP delivery only after complete Windows source/package gate and remote hash verification.

## Review Focus
- A previous failed Save must not block a later explicit selection.
- Yes continues later documents exactly once; No sends no more commands.
- A failed New after a sent Save stays pending and discloses Save uncertainty.
- A preflight failure must not loop on the same queued item when Yes is chosen.
- Another company and positively registered documents remain excluded.

## Task 1: Evidence and explicit posting selection
- [x] Add failing tests for historical-attempt retry and old active queue replacement.
- [x] Separate attempt overlay from posting evidence; remove corresponding RPA history gates while preserving evidence and atomic claim.
- [x] Run targeted backend tests and update tests of deliberately superseded lock behavior.

## Task 2: Runtime issue continuation
- [ ] Add failing backend and real Tk tests for Yes, No, preflight error and Save/New error context.
- [x] Return structured issue context, implement scheduling continuation, enable Continue and replace error-only modal with an operator question.
- [x] Remove automatic 40-record pause; preserve explicit controls and batch cap.
- [x] Run targeted and broad checks; adjust only expectations superseded by the new user requirements.

## Task 3: Review and delivery
- [x] Fresh-context review of the complete change; fix important findings with regressions.
- [ ] Update version/documentation and run complete Windows delivery gate.
- [ ] Validate archive privacy and publish verified ZIP/report/checksum on GitHub; verify remote SHA-256.

Pre-delivery ledger: targeted issue backend tests (11) and new Yes/No/preflight/New Tk cases pass. Broad discovery exposed old lock expectations, updated to the explicit user-requested behavior. One broad P9 UI case had a destroyed-widget error; isolated rerun passed without a product/test workaround. The final delivery gate must fully pass. Review findings resolved with regressions: only current-item preflight; profile mismatch is queue-wide. Native adapter source remains unchanged.
