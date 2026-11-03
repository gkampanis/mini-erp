# Approved audit corrections

User approved the six findings and implementation on 2026-10-26, after discussion.
Restore point: checkpoint-2026.10.26-before-audit-fixes (P6 45c830e).

Constraints: preserve IDs, raw source, audit, company boundaries, cents, and field order fill → Save → New. No live AADE/EBS tests. No unrelated skills staged. Test/production fully isolated; no automatic promotion. Windows/EBS acceptance remains explicitly unrun here.

- [ ] Persist cancellation observations independently of invoice arrival; backfill known evidence; test pages, syncs, restart, company/environment isolation and RPA preflight.
- [ ] Make non-executed purchase exclusion consistently non-attempted; preserve actual attempts/history and test reversal + fresh queue.
- [ ] Isolate test/production business identities without erasing existing documents or weakening live-source checks; regression test both arrival orders and Excel association.
- [ ] Enforce browser URL policy before requests including recovery/popups; bound transfers before buffering, cleanup cancellation; controlled synthetic tests.
- [ ] Separately assess focus-after-click guard. Preserve exact field/Save/New order; no guessed EBS editor topology. If unavailable Windows evidence prevents safe change, explicitly report unimplemented.
- [ ] Review combined changes, full backend/GUI source and extracted ZIP delivery gate, then verified GitHub upload with SHA-256.

Review focus: cancellations observed before local Excel imports; old databases with cancelled audit evidence; duplicate queued purchase histories; test and production sharing MARK but different identities; provider cookies/redirects/download temp data; EBS F2 editors vs modal focus.
