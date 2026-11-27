"""Offline UBL 2.1 JSON candidate for domestic MYR business invoices.
Not an LHDN-approved document generator. No network, database or signing.
Requires a trusted normalized snapshot, explicit tax/classification choices,
and independently confirmed invoice total. Unsupported cases fail closed.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import json
import re
import unittest
from lhdn_protocol_candidate import require, text_value, make_submission

CENT=Decimal("0.01")
ZERO=Decimal(0)
def dec(v,places=2):
    require(type(v) in (int,str,Decimal),"Decimal string or integer required")
    try:
        d=Decimal(v)
        require(d.is_finite() and ZERO<=d<=Decimal("1000000000"),"Amount outside pilot range")
        require(d==d.quantize(Decimal(1).scaleb(-places)),"Excess decimal precision")
    except InvalidOperation:
        raise ValueError("Invalid decimal") from None
    return d

def cents(d):
    return d.quantize(CENT,rounding=ROUND_HALF_UP)

def leaf(value,**attrs):
    return [{"_":value,**attrs}]

def money(value):
    return leaf(cents(value),currencyID="MYR")

def exact_json(value):
    # Decimal is emitted as a JSON number, not a float or quoted amount.
    if isinstance(value,Decimal):
        require(value.is_finite(),"Invalid JSON number")
        return format(value,"f")
    if isinstance(value,dict):
        return "{"+",".join(json.dumps(k)+":"+exact_json(v) for k,v in value.items())+"}"
    if isinstance(value,list):
        return "["+",".join(exact_json(v) for v in value)+"]"
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":"))

def fields(value,keys):
    require(isinstance(value,dict) and set(value)==set(keys.split()),"Unsupported or missing normalized fields")

def pattern(value,regex,message):
    require(isinstance(value,str) and re.fullmatch(regex,value),message)
    return value

def party(value,supplier):
    fields(value,"name tin brn sst email phone address msic msic_description" if supplier else "name tin brn sst email phone address")
    addr=value["address"]
    fields(addr,"line city postcode state country")
    require(addr["country"]=="MYS","Domestic MYR pilot only")
    tin=pattern(value["tin"],r"[A-Z]{1,3}[0-9]{1,13}","TIN required")
    brn=pattern(value["brn"],r"[A-Z0-9-]{1,20}","Business registration number required")
    sst=pattern(value["sst"],r"(?:NA|[A-Z0-9-]{1,35}(?:;[A-Z0-9-]{1,35})?)","Explicit SST registration or NA required")
    phone=pattern(value["phone"],r"\+?[0-9]{7,20}","Contact number required")
    p={
        "PartyIdentification":[{"ID":leaf(tin,schemeID="TIN")},{"ID":leaf(brn,schemeID="BRN")},{"ID":leaf(sst,schemeID="SST")}],
        "PostalAddress":[{
            "CityName":leaf(text_value(addr["city"],50)),
            "PostalZone":leaf(pattern(addr["postcode"],r"[0-9]{5}","Malaysian postcode required")),
            "CountrySubentityCode":leaf(pattern(addr["state"],r"0[1-9]|1[0-6]","Malaysian state code required")),
            "AddressLine":[{"Line":leaf(text_value(addr["line"],150))}],
            "Country":[{"IdentificationCode":leaf("MYS",listID="ISO3166-1",listAgencyID="6")}]
        }],
        "PartyLegalEntity":[{"RegistrationName":leaf(text_value(value["name"],300))}],
        "Contact":[{"Telephone":leaf(phone)}],
    }
    if value["email"]:
        p["Contact"][0]["ElectronicMail"]=leaf(pattern(value["email"],r"[^@\s]{1,100}@[^@\s]{1,100}\.[^@\s]{1,50}","Invalid email"))
    if supplier:
        p["IndustryClassificationCode"]=leaf(pattern(value["msic"],r"[0-9]{5}","MSIC required"),name=text_value(value["msic_description"],300))
    return [{"Party":[p]}]

def category(code):
    return [{"ID":leaf(code),"TaxScheme":[{"ID":leaf("OTH",schemeID="UN/ECE 5153",schemeAgencyID="6")}]}]

def subtotal(code,net,tax,rate=None):
    s={"TaxableAmount":money(net),"TaxAmount":money(tax),"TaxCategory":category(code)}
    if rate is not None and code!="06":s["Percent"]=leaf(rate)
    return s

def generate(snapshot,now):
    fields(snapshot,"number issue_at currency document_type supplier buyer lines expected_total")
    require(snapshot["currency"]=="MYR" and snapshot["document_type"]=="01","Only ordinary MYR invoices supported")
    require(isinstance(now,datetime) and now.tzinfo is not None,"Trusted UTC clock required")
    issued=datetime.fromisoformat(snapshot["issue_at"].replace("Z","+00:00"))
    require(issued.tzinfo is not None,"Invoice issue timezone required")
    issued=issued.astimezone(timezone.utc)
    require(now-timedelta(hours=72)<=issued<=now,"Issue time outside conservative pilot window")
    number=text_value(snapshot["number"],80)
    require(isinstance(snapshot["lines"],list) and 1<=len(snapshot["lines"])<=100,"Invalid line count")
    supplier=party(snapshot["supplier"],True)
    buyer=party(snapshot["buyer"],False)
    require(snapshot["supplier"]["tin"]!=snapshot["buyer"]["tin"],"Same-party invoices not supported")
    lines=[]; groups=defaultdict(lambda:[ZERO,ZERO]); net_total=ZERO; tax_total=ZERO
    for i,x in enumerate(snapshot["lines"],1):
        fields(x,"description classification quantity unit_price tax_type tax_rate")
        qty=dec(x["quantity"],5); price=dec(x["unit_price"])
        require(qty>0 and price>0,"Positive quantities and prices required")
        code=x["tax_type"]; rate=dec(x["tax_rate"],4)
        require(code in ("01","02","06") and (rate==0 if code=="06" else 0<rate<=100),"Unsupported tax treatment")
        net=cents(qty*price);tax=cents(net*rate/100)
        require(net>0,"Zero-value line outside pilot")
        groups[code][0]+=net;groups[code][1]+=tax
        net_total+=net;tax_total+=tax
        lines.append({
            "ID":leaf(str(i)),"InvoicedQuantity":leaf(qty),
            "LineExtensionAmount":money(net),
            "TaxTotal":[{"TaxAmount":money(tax),"TaxSubtotal":[subtotal(code,net,tax,rate)]}],
            "Item":[{"Description":leaf(text_value(x["description"],300)),
                     "CommodityClassification":[{"ItemClassificationCode":leaf(pattern(x["classification"],r"[0-9]{3}","Classification required"),listID="CLASS")}]}],
            "Price":[{"PriceAmount":money(price)}],
            "ItemPriceExtension":[{"Amount":money(net)}]
        })
    total=net_total+tax_total
    require(total==dec(snapshot["expected_total"]),"Confirmed invoice total differs from computed total")
    invoice={
        "ID":leaf(number),"IssueDate":leaf(issued.date().isoformat()),"IssueTime":leaf(issued.strftime("%H:%M:%SZ")),
        "InvoiceTypeCode":leaf("01",listVersionID="1.0"),"DocumentCurrencyCode":leaf("MYR"),
        "AccountingSupplierParty":supplier,"AccountingCustomerParty":buyer,
        "TaxTotal":[{"TaxAmount":money(tax_total),"TaxSubtotal":[subtotal(code,*groups[code]) for code in sorted(groups)]}],
        "LegalMonetaryTotal":[{"LineExtensionAmount":money(net_total),"TaxExclusiveAmount":money(net_total),
            "TaxInclusiveAmount":money(total),"PayableAmount":money(total)}],
        "InvoiceLine":lines
    }
    root={"_D":"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
        "_A":"urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "_B":"urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2","Invoice":[invoice]}
    return exact_json(root).encode("utf-8")

class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,27,3,0,tzinfo=timezone.utc)
        p={"name":"Synthetic Sdn Bhd","tin":"C1234567890","brn":"202001234567","sst":"NA","phone":"+60312345678","email":"",
           "address":{"line":"Test street","city":"Petaling Jaya","postcode":"47810","state":"10","country":"MYS"}}
        self.s={"number":"TEST-1","issue_at":self.now.isoformat(),"currency":"MYR","document_type":"01",
          "supplier":{**p,"msic":"46900","msic_description":"Wholesale"},
          "buyer":{**p,"tin":"C9876543210","brn":"202001234568"},
          "lines":[{"description":"Fixture","classification":"022","quantity":"3","unit_price":"10.01","tax_type":"02","tax_rate":"8"}],
          "expected_total":"32.43"}
    def test_exact_totals(self):
        raw=generate(self.s,self.now)
        d=json.loads(raw,parse_float=Decimal)["Invoice"][0]
        self.assertEqual(d["LegalMonetaryTotal"][0]["PayableAmount"][0]["_"],Decimal("32.43"))
        self.assertEqual(d["TaxTotal"][0]["TaxAmount"][0]["_"],Decimal("2.40"))
        self.assertEqual(make_submission(raw,"TEST-1")["documents"][0]["codeNumber"],"TEST-1")
        self.assertEqual(raw,generate(self.s,self.now))
    def test_mismatch(self):
        self.s["expected_total"]="32.44"
        with self.assertRaises(ValueError):generate(self.s,self.now)
    def test_unsupported(self):
        for key,value in (("currency","USD"),("document_type","02"),("discount","10")):
            with self.assertRaises(ValueError):generate({**self.s,key:value},self.now)
    def test_missing_identity(self):
        self.s["buyer"]["tin"]=""
        with self.assertRaises(ValueError):generate(self.s,self.now)
    def test_tax(self):
        self.s["lines"][0]["tax_type"]="06"
        with self.assertRaises(ValueError):generate(self.s,self.now)
        self.s["lines"][0]["tax_rate"]="0";self.s["expected_total"]="30.03"
        self.assertIn(b'"PayableAmount":[{"_":30.03',generate(self.s,self.now))
    def test_stale(self):
        with self.assertRaises(ValueError):generate(self.s,self.now+timedelta(days=4))

if __name__=="__main__":
    unittest.main()
