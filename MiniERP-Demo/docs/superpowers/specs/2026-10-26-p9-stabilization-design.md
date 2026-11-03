# Mini ERP P9 — approved design

Approved by the user’s P9 specification, 26 October 2026. Baseline 1d8e63f (2026.10.26-P8), checkpoint checkpoint-P8-20261026-before-final-audit.

Keep native/RPA/Save-New/checkpoints/account-mapping algorithms and database schema unchanged. Reuse existing purchase rules and undo, account_group, importers and reconciliation. No production calls or data in fixtures.

1. Pending tab is an immutable incoming financial, non-purchase, non-registered/non-submitted dataset before view filters; unreconciled documents remain visibly unresolved, never automatically executable. Known8.6/movement excluded; credit notes/value invoices with delivery flags retained. Registered access remains in existing Reconciliation.
2. Explicit card group transitions reuse SupplierPurchases with existing protections; account edits alone never silently undo purchase rules. Workspace uses existing account_group. No second group store.
3. Three posting actions remain: up to40, selected, one. Optional simulation and pause/resume stay. Simplify only UI redundant confirmations/controls; backend identity/account/duplicate/uncertain-save guards remain.
4. Excel column mapping has one entry/shared interaction, with distinct document-ingest and EBS-evidence backends. Detect known layouts, reuse saved stage-specific mappings, preserve XLSX/XLSM/ODS and current format limits. No unsupported XLS claim. Preserve company/period/full-export attestations.
5.429: normalized key, deadline never shortened, cooldown before every HTTP attempt/page/retry; honest partial UI and stop. No automatic429 retry or sync rewrite.

Alternatives rejected: merging EBS evidence into document-ingest schema loses data semantics; rewriting engine/schema is prohibited; new group subsystem duplicates existing protected rules. Implementation follows existing services with minimal shared column UI.
