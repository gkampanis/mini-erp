# Automatic filtered batch after first trial

User-selected behavior: «Μία δοκιμή και μετά αυτόματα όλες».

The explicit posting action authorizes the eligible snapshot of the filtered view. Execute its first document normally, then automatically continue the same immutable queue after successful Save/New. Remove the historical pilot_at single-record cap and separate activation requirement; never mark that timestamp or EBS persistence as verified automatically. Expose one derived first_record_done flag from existing item/Save-audit state, not a new database or approval system.

Approaches: the user selected automatic continuation after the first record, rather than a single/all checkbox or the old manual pilot activation. Preserve explicit single-document posting. Main filtered posting queues the entire visible eligible scope. Automatically cross the existing successful 40-record checkpoint through the existing resume API; explicit user Pause/Stop and any failed/uncertain result always stop it. Native adapter, field order, Save/New implementation, reconciliation and duplicate/tenant/group-2 protections remain unchanged.

No new controls, migrations, runtime dependencies, screenshots or production tests. Tests use real SQLite/Tk scheduling with only OS input replaced. Windows/EBS live checks remain unrun here. Deliver only the mandatory gate's verified GitHub artifact and report.
