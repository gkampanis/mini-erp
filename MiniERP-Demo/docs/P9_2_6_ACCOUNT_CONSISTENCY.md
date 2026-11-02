# P9.2.6

Account edits share one supplier/pending propagation service. Remember updates card, eligible pending same-group documents, and queued payloads in one transaction; document-only overrides remain explicit. Previous attempt history does not block local approval and is not rewritten. Actual registered preparations remain protected. Document approval does not globally reclassify supplier purchase rules. Pristine open editors refresh; dirty conflicting editors reload before saving.

The observed post-Save issue was a 500ms timeout activating a newly observed TED. A typed transient timeout now stays inside the existing 12s readiness loop. Only readiness activation is retried; New, Save and fill are not replayed. Mapping, fill sequence, net focus, Save implementation and deadline stay unchanged. A persistent failure or EBS modal remains an issue.

Delivery requires full Windows gate. Live EBS acceptance of this revision is NOT_RUN.
