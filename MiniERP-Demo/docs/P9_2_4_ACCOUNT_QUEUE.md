# P9.2.4 — account approvals and pending queues

This release fixes account provenance, without changing the native EBS field sequence.

- Bulk document approval refreshes the selected document snapshots in queued or paused jobs, atomically with the approval and audit. Running queues must be paused first.
- Previously attempted live documents cannot have their approval/history rewritten by bulk approval. They require operator review; no automatic replay or status reset is performed.
- Supplier-card application repairs pending snapshots even when the document approval already contains the selected account.
- Planning a new selection preserves an explicitly approved document account. A saved supplier default is applied when document approval is missing. Changing the card with the existing apply-pending action remains explicit propagation.
- The main list column “Λογαριασμός καρτέλας” describes the supplier rule. The RPA preview shows the account approved for that document; intentional per-document exceptions remain possible.

Local evidence established a real difference between current approval/card and an older queue snapshot. The observed account edits occurred after the original EBS focus failure, so this fix does not establish that account drift caused that earlier failure.

Production data was inspected read-only. No production approvals or queue records were changed, and no EBS Save was invoked. Synthetic regression tests cover propagation, rollback, attempted-document protection, and explicit overrides. Windows package checks do not substitute for live EBS acceptance. The existing P9.2.3 net-editor focus protection remains in place.

Windows smoke tests do not capture desktop pixels. Screenshot documentation is optional, and capturing the whole workstation could place unrelated business data in a synthetic package. All Tk functional assertions remain required. Existing synthetic documentation images are retained.
