"""Seeded synthetic property/mutation coverage with an independent decimal oracle."""
from decimal import Decimal,ROUND_HALF_UP
from collections import defaultdict
from copy import deepcopy
import random,unittest
import xml.etree.ElementTree as ET
from app.infrastructure.aade.lines import extract_lines
from app.application.vat_lines import compact_rows
from tests.test_mydata_lines import invoice
rates={1:24,2:13,3:6,4:17,5:9,6:4,7:0,8:0,9:3,10:4}


class VATGenerativeTests(unittest.TestCase):
    def test_exact_ingestion_compaction_and_corrupt_inputs_against_decimal_oracle(self):
        rng=random.Random(20261031);scenarios=1000;mutations=0
        for case in range(scenarios):
            categories=[1,7]+[rng.choice(list(rates)) for _ in range(rng.randrange(0,11))]
            expected=[];raw=[]
            for index,cat in enumerate(categories,1):
                net=rng.randrange(0,10000001)
                tax=int((Decimal(net)*Decimal(rates[cat])/Decimal(100)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
                values=dict(lineNumber=str(index),netValue=str(Decimal(net)/100),vatCategory=str(cat),vatAmount=str(Decimal(tax)/100))
                if cat==7:values['vatExemptionCategory']='27'
                raw.append(values);expected.append((index,net,tax,cat,27 if cat==7 else None))
            net=sum(x[1] for x in expected);tax=sum(x[2] for x in expected)
            summary=dict(totalNetValue=str(Decimal(net)/100),totalVatAmount=str(Decimal(tax)/100),totalGrossValue=str(Decimal(net+tax)/100))
            node=invoice(raw,summary);analysis=extract_lines(node)
            assert analysis['status']=='verified',(case,analysis['errors'])
            assert [(r['line_number'],r['net_minor'],r['tax_minor'],r['vat_category'],r['vat_exemption']) for r in analysis['lines']]==expected
            rows=[dict(r,account='64.03.'+str(r['vat_category'])) for r in analysis['lines']]
            compact=compact_rows(rows)
            before=defaultdict(lambda:[0,0]);after=defaultdict(lambda:[0,0])
            for group,items in ((before,rows),(after,compact)):
                for r in items:
                    k=(r['account'],r['vat_category'],r['vat_exemption']);group[k][0]+=r['net_minor'];group[k][1]+=r['tax_minor']
            assert dict(before)==dict(after)
            assert len(compact)==len(before)
            assert len({(r["account"],r["vat_category"],r.get("vat_exemption")) for r in compact})==len(compact)
            assert sorted(n for r in compact for n in r['source_line_numbers'])==list(range(1,len(rows)+1))
            for mutation in ('summary','duplicate','precision'):
                bad=deepcopy(node)
                if mutation=='summary':bad.find('invoiceSummary/totalNetValue').text=str(Decimal(net+1)/100)
                elif mutation=='duplicate':bad.findall('invoiceDetails')[1].find('lineNumber').text='1'
                else:bad.find('invoiceDetails/netValue').text='0.001'
                assert extract_lines(bad)['status']=='invalid',(case,mutation)
                mutations+=1
        self.assertEqual(mutations,3000)


if __name__=="__main__":unittest.main()
