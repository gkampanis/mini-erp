# Parastio UI design — approved scope

The user selected the supplied dark desktop mockup with the existing tabs, search, filters, table, Auto width / Columns controls and posting actions. They approved the proposed uniform presentation and chose Parastio with a new graphic. Preserve stable P9.2.6 at GitHub branch stable-2026.10.30-P9.2.6 and use a separate development copy/branch.

Deliver consistent compact ttk styling with readable Segoe UI text, saved light/dark appearance, resizable/optional columns with persistent widths and sorting, clipped-cell tooltips, clear selection counts and integer-cent totals explicitly labelled as visible rows. Auto width sizes displayed content sensibly; manual widths survive refresh. Hiding a column must not change row data, filters, posting IDs or PDF actions. Existing active filters remain visible even when their columns are hidden. Keep a way to reset the layout.

Remove the two always-visible reconciliation buttons shown by the user: optical confirmation and history. Preserve history and confirmation handlers; normalized-match confirmation remains accessible in comparison details and existing attempt confirmation paths remain intact. History may be accessed from a secondary Options menu. No approval/evidence semantics change.

Branding: Parastio, a simple original document/check mark, crisp application icon and header. Internal MiniERP data path, database schema, configuration identifiers, launchers and connector workflow stay compatible. Ship logo PNG in the existing docs PNG allowlist; source SVG is a separate branding deliverable.

No application/domain/infrastructure or migrations changes, especially no native EBS edits. UI preferences live in ui-preferences.json, never the accounting DB. Tests use synthetic data only. Notify before Windows GUI tests and when closed. Publish only after the full Windows delivery gate and verify GitHub bytes. No live EBS input.

User follow-up: dark controls must remain clearly visible. Explicitly theme normal/hover/pressed/focused/disabled control states, dropdown arrows and selection marks; verify contrast on both palettes.
