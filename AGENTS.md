# Mini ERP project instructions

This application prepares and reviews documents for EBS; it does not replace EBS.
Preserve the original EBS Agent/reference and the validated RPA sequence. Do not
post accounting entries, transmit to myDATA, or write to EBS without the explicitly
authorized, validated connector workflow. A local group/account approval is not
proof of EBS persistence or authoritative chart-of-accounts validation.

## Before delivering a ZIP

Run the project delivery gate against the current source:

- Cloud: `DISPLAY=:99 XDG_CACHE_HOME=/workspace/cloud-tools/cache /usr/bin/python3 scripts/verify_delivery.py`
- Windows: `py -3.12 scripts/verify_delivery.py --require-windows`

Reuse a working display or start the existing Xvfb helper when needed. Do not
skip GUI checks or disable tests to create a passing package. Do not present
an older ZIP as the result of a failed run. Deliver only the gate's successful
artifact with its verification report and SHA-256. `scripts/package_demo.py`
also routes through this gate; its low-level build function is for internal
candidate packages and tests, not an independent delivery approval.

Report Windows/EBS checks as unrun unless actually executed in the required
environment. Linux GUI success is not Windows launcher or EBS acceptance.
This checkout is already isolated; do not create a Git worktree unless requested.

Use only synthetic fixtures in tests and packages. Keep local databases, PDF
invoices, real customer Excel, credentials, legacy reference archives and Git
metadata out of delivery ZIPs. Preserve Decimal/integer cents, string VAT IDs,
raw provenance, tenant boundaries, migrations, atomic import and audit.

ECC verification-loop is a process reference, not a runtime dependency. Do not
install global ECC hooks or add unrelated product modules automatically.
