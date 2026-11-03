# User-approved one-time account history import
Use uploaded workbook columns creditor name, date, EBSreference, expenseaccount. Choose mostfrequent account per normalizedname; ties require operatorchoice. Match existing company production creditorcards by unique normalizedname; approximate suggestions are never automatic identities. No new cards without VAT, no customerdata bundled, no RPA changes.
1. Synthetic RED/GREEN tests for frequency, duplicate source records, collisions/ties, sourceimmutability, company/group2 boundaries.
2. HistoryAccounts service previews source and cardcurrentaccount; per-rowmanual choice supports fuzzy/name differences; existing SupplierAccounts.save apply_pending=False classify_supplier=False atomically applies only approved cards. Preserve historical docs/VATrules, recordaudit/sourcehash and prevent repeat same source/card.
3. Small one-time import dialog under Creditors: choose localExcel, inspect table, choosecard/account for unresolved, applyselectedreviewedrows. No startup/imports unless userinvokes.
4. Backend and GUI synthetic regression checks, read-only userpreview counts, fresh review, fullWindows source+ZIP gate, GitHub delivery. Productiondata remains unchanged until operatorapplies reviewedchoices.

User follow-up explicitly requires card updates to propagate to pending invoices. Implemented via existing apply_pending, excluding registered/realattempted and purchase docs; queued snapshots rebind through existing service. Whole batch atomic. No posting engine changes.
