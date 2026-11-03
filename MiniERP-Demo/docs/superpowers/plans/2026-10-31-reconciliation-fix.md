# Approved reconciliation correction
User requested technical decimal false differences corrected, incomplete identity rows and configured group2 VAT identities excluded. No cent tolerance approved; preserve genuine monetary differences and posting engine.
1. Reproduce numeric ODS serialization artifacts versus genuine fractions with synthetic tests.
2. Normalize only numeric spreadsheet cent representation within two IEEE ULPs, capped below1e-9 EUR, preserve raw/text inputs.
3. Exclude blank VAT/reference rows and configured purchase creditors from reconciliation candidates, preserve audit source and normal expense evidence.
4. Regression test source preview, commit, results, tenant boundaries and unchanged real financial differences. Existing frozen matches require reimport of source.
5. Full Windows source/package gate then authorized GitHub delivery; live EBS not run.
