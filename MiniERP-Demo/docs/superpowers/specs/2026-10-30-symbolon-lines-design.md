# Σύμβολον ERP — accurate myDATA detail lines and VAT account rules

Status: approved by operator 2026-10-30; proceed inline in current chat.

## Intent and scope

The operator wants the application to evolve over the working P9.2.6/P9.3.0 workflow.
Priority is exact AADE ingestion. Keep the interaction simple: invoice detail lines,
their amounts and VAT, operator-selected accounts, and remembered creditor rules.
No new tax-policy interpretation, voucher eligibility logic or general accounting
classification. The operator decides the accounts and accounting treatment.

The display name becomes **Σύμβολον ERP**, with a modern original mark. The document
list becomes the dominant work area; compact company/period/import/search controls
and a smaller idle status area recover height. Keep familiar tabs, filters and
posting actions. Preserve user column widths and preferences.

## Evidence already obtained

- Official AADE ERP REST API v2.0.2 (September 2026), sections 4.2.6, 5.4, 5.6, 8.2:
  `RequestDocs` includes invoiceDetails; lineNumber, netValue, vatCategory,
  vatAmount and, where applicable, vatExemptionCategory identify detail values.
- The archived XML corresponding to the operator's example was read without writes.
  Two lines: net 126.38, VAT category 1, VAT 30.33; net 2006.00, VAT category 7,
  VAT 0.00, exemption 27. Summary net 2132.38, VAT 30.33, gross 2162.71.
  This verifies this archived snapshot, not a new live API fetch.
- Read-only archive audit: 6 invoice-response archives; 4162 unique invoice identities
  in the scanned snapshots, all with details, 15611 detail lines; 155 invoices with
  multiple VAT/exemption signatures. In 4156 ordinary invoices, exact decimal line
  net and VAT sums match summaries. Six contain special line types and are recorded
  separately rather than incorrectly certified by the ordinary summation check.
  One other archive was outside the invoice-reader's accepted structure; the audit
  does not classify it as an AADE ingestion failure.
- Current `providers/xml_parser.py` retains original XML but exposes summary totals.
  `aade/client.py:parsed_page` does not expose detail lines in normalized records.
  `mydata.py` archives complete responses but persists summary-oriented record_json.
  `rpa.py:payload` emits one account and one total net amount; the native field
  sequence writes that one row. This is the data gap demonstrated by the example.

## Approach

Use the existing read-only RequestDocs path and original archives. Extend the
normalized data to retain complete source detail lines and exact monetary values,
then resolve operator-approved accounts against those lines. This matches the
operator's requested one-time decision and reuse; no inference from average VAT
or OCR is involved. Keep summary amounts and raw provenance alongside details.

1. **Exact detail extraction.** Preserve source line order/number, lexical source
   values, exact integer cents, VAT category and exemption, and other source fields
   required to interpret totals. Keep source XML/hash and invoice MARK association.
   Explicitly distinguish missing analysis, invalid analysis and valid analysis.
   Validate fields before claiming readiness; retain the archived source when a
   value cannot be interpreted. Never silently repair or discard a line.
   Existing summary-only synthetic fixtures and Excel-only records retain their
   existing interpretation; they are not labelled verified detailed AADE records.

2. **Existing records.** Recover detail information from their own linked archived
   RequestDocs pages, using company/environment/MARK and verified invoice identity.
   No broad name/date or amount-only association. A future refresh must not silently
   leave old detail lines associated with changed invoice data. No production data
   writes during development. Application upgrade/backfill is audited and tested
   on synthetic copies, with a dry-run before any operator-side use.

3. **Remembered creditor accounts.** Store rules scoped to company, environment,
   creditor and VAT category/exemption. The existing primary account stays the
   source for the normal VAT line. On first mixed-VAT posting, show the actual line
   analysis with the primary account prefilled and request the missing secondary
   account. Explicit approval saves the mapping for future matching invoices.
   A rule may reference the current primary account rather than freeze an old copy;
   editing the primary account must leave every screen and unstarted queue consistent.
   Unknown future categories require only the new missing decision. Users can edit
   rules in the creditor card; registered history is preserved.

4. **One invoice, multiple EBS rows.** Click the next mapped row as the operator
   confirmed; fill its account and net value, then Save once for the entire invoice.
   Existing first-row sequence and Save/New flow remain intact. Use explicit mapping
   for additional account/net cells, recorded once through the existing mapping UI;
   do not invent a row height, reuse the first row's coordinates or overwrite it.
   All needed positions must be verified before typing. Preserve exact source net
   and VAT totals; avoid regrouping that changes VAT rounding. Store the original
   lines even when a posting view can safely combine equivalent lines. Keep the
   first implementation's native coverage limited to positions actually mapped;
   never claim arbitrary scrolling/unmapped-row support.
   The account's configured VAT behavior must reproduce the source VAT in a real
   acceptance run; the existing net-only engine does not establish that by itself.
   Do not introduce automatic Save retries. An issue follows the user's existing
   keep-pending / ask-to-continue handling.

5. **Presentation.** After the AADE detail model is proved, apply the approved new
   name and more dominant list. A compact modern sigma-based identity and consistent
   visible dropdown arrows are implementation choices; no new runtime UI library.

## Boundaries and builder calls

- Work in a fresh development copy extracted from verified P9.3.0 ZIP. Preserve
  both published P9.3.0 and frozen stable P9.2.6; no edits in the old dirty checkout.
- Retain MiniERP internal storage and startup names for compatibility.
- Purchase group 2 remains outside RPA; operator-selected accounts obey the existing
  expense workflow. Do not expand the chart/accounting scope without instruction.
- Add the smallest account-rule persistence model required; no ERP framework rewrite.
- All new detail/account snapshots participate in existing queue freshness checks.
- Do not operate live EBS or production AADE during automated tests. Explain any
  required local GUI window phase before running it and announce its completion.
- Exact live VAT equality is a separate acceptance claim from synthetic tests.

## Required proof before delivery

1. Source XML → extracted lines: exact category, exemption, number, net and VAT;
   namespace/escaped envelopes, pagination boundaries, repeated pages, missing or
   duplicate line numbers, missing fields, decimal precision, 0% vs no-VAT category,
   discounts/credit types and special source-line types. No guessed data.
2. Existing archive recovery: correct invoice/company/environment, missing archive,
   conflicting snapshot, repeated recovery and unchanged approvals/history.
3. Rules: initial primary+secondary selection, reuse without another prompt,
   different creditor/company isolation, future category, primary-account edit,
   rule edit with a queued invoice, and immutable registered history.
4. Native orchestration with synthetic drivers: header once, first row preserved,
   second-row click and net-focus verification, exact amounts, one Save/one New,
   failure in row two means no Save, no automatic replay; unchanged single-row tests.
5. GUI: dominant list at common window sizes, accessible actions, arrows and all
   control states, first-use prompt and rule editing. No production writes.
6. Fresh code review and full Windows delivery gate on source and extracted ZIP,
   zero skipped required tests; ZIP/hash/report upload and verified GitHub download.
7. Real EBS multirow/VAT acceptance remains NOT_RUN until actually observed in an
   authorized run. Tests and a matching archived XML are not called 100% live acceptance.

## Sources

- https://www.aade.gr/sites/default/files/2026-09/myDATA%20API%20Documentation%20v2.0.2_official_erp_1.pdf
- Local shipped P9.3.0 source and read-only aggregate audit in work/symbolon-mydata-audit.json.
  No actual customer XML, credentials or invoice identifiers enter the package/tests.
