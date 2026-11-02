# P9.2.6 account consistency and new TED readiness

User asks to fix three account-edit locations, remove historical attempt approval blocker, and tolerate readiness latency after a successful posting. Preserve the now-working fill and Save sequence. Notify before interactive Windows test runs and when finished.

Evidence: P9.2.5 diagnostic 20261029T213705111765 reports phase new, after Save, SendMessageTimeoutW new TED activation timeout. No evidence that Save failed. Other diagnostic phase fill is separate mapping ownership failure after modal/fresh-form trouble; do not weaken ownership checks.

Implementation tasks:
1. Add failing backend tests for old-attempt local approval, all same-group pending + card propagation, historical payload preservation, actual registered evidence protection, atomic rollback and mixed-group scope.
2. Reuse SupplierAccounts.save from Workspace approval with caller-owned transaction and classification disabled for document-only group changes. Keep real registered history immutable, no native input calls from account edits.
3. Use same approval service in single-document UI; make checkbox scope explicit and enabled by default. Refresh pristine open editors; detect conflicting dirty edits before saving.
4. Add typed transient activation timeout; retry readiness observation/activation only within existing open_new deadline. Never repeat New or Save. Preserve all fill/mapping/health/ownership validation.
5. Review source delta against verified P9.2.5 ZIP; meaningful Tk tests, full delivery gate Windows source and extracted package; only then upload verified ZIP/report/hash/guide to existing downloads branch and verify raw download bytes.

No production DB writes or live EBS input. Backend and GUI use synthetic fixtures. EBS live acceptance NOT_RUN for this revision; user reported P9.2.5 posting success.
