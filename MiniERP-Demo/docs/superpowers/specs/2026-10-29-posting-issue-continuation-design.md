# Operator-controlled posting after an issue

User instructions supersede earlier no-replay workflow requirements: remove runtime blockers 2 (old active queues) and 4 (previous attempts); simplify repeated pre-input checks 10; replace permanent uncertainty locks 8/15 and arbitrary batch interruption 14. User explicitly chose: on an issue, retain the document in the not-posted list, show the issue, and ask whether to continue.

Use the existing Python/Tk/SQLite application and Save → New native adapter. Old attempts remain immutable history, not eligibility locks. Real EBS Excel/manual registration evidence, company scope, group-6-only restriction, and field-target/net-focus checks remain. Reconciliation may expose attempt information for display, but posting eligibility uses underlying EBS evidence without local attempt overlay. Successful sends remain outside the pending view until actual confirmation; failed sends remain visible even when Save might have been sent.

An explicit posting action can create a new selected scope despite old paused/running/uncertain history. The UI still prevents a second action while its worker is running. Unstarted matching queues may be reused; previous attempted documents are not excluded solely by history.

After a runtime issue, the worker stops and returns item, phase and whether Save may have been sent. The UI shows a Yes/No question when other queued items remain. Yes skips only the failed scheduling item and continues the remaining queue on a fresh form; No leaves execution paused. Neither choice silently retries the failed document or sends another Save. A later explicit posting action can select that document without a history-unlock step. Errors on the last item show the issue and leave the item visible for a later action.

Keep explicit Pause/Stop controls and the "up to 40" selection limit. Remove the automatic 40-record pause within a selected batch. Repeated approval/attempt/reconciliation checks immediately around the input claim are removed; each item is checked on its own turn; its latest approved payload is read before typing, real EBS registration evidence remains enforced, and an atomic item claim prevents the same queued item being claimed twice.

Approaches: a permanent history lock is rejected by the user; automatic retry of the failed document is not requested. The selected approach is operator-controlled skip-and-continue with informative history. Production data and EBS are not modified during development or verification.

Review corrections: validate only the current document, so a later changed/registered document cannot be attributed to a healthy predecessor. Classify profile mismatch as queue-wide; preserve all queued documents and request a new posting action with current settings rather than offering item skipping.
