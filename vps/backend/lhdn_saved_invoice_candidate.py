"""Read-only mapper for the existing MYR Invoice saved snapshot.
Offline candidate: caller must load an authorized company and invoice from the
server DB. No network, DB mutation, credential lookup or submission.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo
import math
import unittest
from lhdn_ubl_candidate import generate
from lhdn_protocol_candidate import require, make_submission

def numeric(value,precision):
    require(type(value) in (int,float,str,Decimal),"Invalid stored number")
    try:
        d=Decimal(str(value))
        require(d.is_finite() and 0<=d<=Decimal("100000000000"),"Invalid stored amount")
        require(d==d.quantize(Decimal(1).scaleb(-precision)),"Unsupported numeric precision")
    except InvalidOperation: raise ValueError("Invalid stored amount") from None
    return d

def sen(value):
    return numeric(value,0)

def rounded(d):
    return d.quantize(Decimal(1),rounding=ROUND_HALF_UP)

def select(rows,key):
    require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),"Invalid stored records")
    matched=[row for row in rows if row.get("id")==key]
    require(isinstance(key,str) and bool(key) and len(matched)==1,"Record not uniquely found")
    return matched[0]

def map_party(row,supplier):
    address=row.get("addr")
    require(isinstance(address,dict),"Stored address required")
    p={k:row.get(k,"") for k in ("name","tin","sst","email","phone")}
    p["brn"]=row.get("brn","") if supplier else row.get("idValue","")
    p["address"]={k:address.get(k,"") for k in ("line","city","postcode","state","country")}
    if supplier:
        p.update(msic=row.get("msic",""),msic_description=row.get("msicDesc",""),ttx=row.get("ttx",""))
    else:
        require(row.get("idType")=="BRN","Business buyer identity required")
    return p

def normalize(company,invoice_id,confirmed_total_sen,now):
    require(isinstance(company,dict) and not company.get("demo") and not company.get("vpsSyntheticWriteTest"),"Real company snapshot required")
    require(isinstance(now,datetime) and now.tzinfo is not None,"Trusted server clock required")
    inv=select(company.get("invoices"),invoice_id)
    require(inv.get("docType")=="01" and not inv.get("consolidated") and not inv.get("refInvoiceId"),"Only ordinary business invoice mapping is enabled")
    require(inv.get("appStatus")=="Ready","Invoice must be ready")
    if company.get("approvalRequired") is True:
        require(inv.get("approvalAction")=="approve" and bool(inv.get("approvalActor")) and inv.get("approvalActor")!=inv.get("createdBy"),"Independent approval required")
    lhdn=inv.get("lhdn")
    require(isinstance(lhdn,dict) and lhdn.get("status")=="Not Submitted" and not lhdn.get("attempts") and not any(lhdn.get(k) for k in ("submissionUid","uuid","longId","validatedAt")),"Existing LHDN activity requires reconciliation")
    require(not inv.get("payments") and not inv.get("share"),"Paid or shared invoice requires separate workflow")
    require(inv.get("issueDate")==now.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat(),"Current Malaysian issue date required for this pilot")
    buyer=select(company.get("customers"),inv.get("customerId"))
    require(not buyer.get("archived") and not buyer.get("system"),"Active business buyer required")
    items=inv.get("items")
    require(isinstance(items,list) and 1<=len(items)<=100,"Unsupported line count")
    normalized=[]; total=Decimal(0); ui_total=0; ids=set()
    for it in items:
        require(isinstance(it,dict) and isinstance(it.get("id"),str) and it["id"] and it["id"] not in ids,"Invalid line identity")
        ids.add(it["id"])
        qty=numeric(it.get("qty"),5); price=sen(it.get("price")); discount=sen(it.get("discount",0)); rate=numeric(it.get("taxRate",0),4)
        require(qty>0 and price>0 and rate<=100,"Invalid stored line values")
        gross=rounded(qty*price)
        require(discount<=gross,"Discount exceeds subtotal")
        net=gross-discount; tax=rounded(net*rate/100)
        # Mirror the existing positive-number JavaScript UI rounding, and refuse
        # any edge case that would differ from the exact decimal computation.
        ui_gross=math.floor(float(qty)*float(price)+0.5)
        ui_net=ui_gross-int(discount)
        ui_tax=math.floor(ui_net*float(rate)/100+0.5)
        require(gross==ui_gross and tax==ui_tax,"UI and exact decimal rounding differ")
        total+=net+tax;ui_total+=ui_net+ui_tax
        normalized.append({"description":it.get("desc",""),"classification":it.get("classCode",""),
            "quantity":qty,"unit_price":price/100,"discount":discount/100,
            "tax_type":it.get("taxType"),"tax_rate":rate,"unit_code":it.get("unitCode","")})
    require(total==ui_total==sen(confirmed_total_sen),"Confirmed total differs from stored invoice")
    currency=inv.get("currency")
    fx=inv.get("fxRate")
    require(currency!="MYR" or fx in ("",None,0,"0"),"Unexpected MYR exchange rate")
    result={"number":inv.get("number"),"issue_at":now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "currency":currency,"document_type":"01","supplier":map_party(company,True),"buyer":map_party(buyer,False),
        "lines":normalized,"expected_total":total/100}
    if currency!="MYR":result["fx_rate"]=numeric(fx,8)
    return result

def preview(company,invoice_id,confirmed_total_sen,now):
    snapshot=normalize(company,invoice_id,confirmed_total_sen,now)
    raw=generate(snapshot,now)
    return {"document":raw,"payload":make_submission(raw,snapshot["number"])}

class MapperTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,27,3,0,tzinfo=timezone.utc)
        p={"name":"Synthetic company","tin":"C1234567890","sst":"A01-1234-56789012","email":"","phone":"+60312345678",
           "addr":{"line":"Test street","city":"Petaling Jaya","postcode":"47810","state":"10","country":"MYS"}}
        self.inv={"id":"INV-ID","number":"INV-001","docType":"01","customerId":"CUST-ID","currency":"MYR","fxRate":"",
           "issueDate":"2026-11-27","appStatus":"Ready","lhdn":{"status":"Not Submitted","attempts":[]},"payments":[],
           "items":[{"id":"LINE-ID","desc":"Test service","classCode":"022","unitCode":"C62","qty":3,"price":1001,"discount":300,"taxType":"02","taxRate":8}]}
        self.company={**p,"id":"COMPANY","brn":"202001234567","ttx":"NA","msic":"46900","msicDesc":"Wholesale",
           "customers":[{**p,"id":"CUST-ID","tin":"C9876543210","idType":"BRN","idValue":"202001234568"}],"invoices":[self.inv]}
    def test_preview(self):
        import json
        x=preview(self.company,"INV-ID",2919,self.now)
        d=json.loads(x["document"])["Invoice"][0]
        self.assertEqual(d["LegalMonetaryTotal"][0]["PayableAmount"][0]["_"],29.19)
        self.assertEqual(d["InvoiceLine"][0]["AllowanceCharge"][0]["Amount"][0]["_"],3)
        self.assertEqual(x["payload"]["documents"][0]["codeNumber"],"INV-001")
    def test_total_mismatch(self):
        with self.assertRaises(ValueError):preview(self.company,"INV-ID",2918,self.now)
    def test_approval(self):
        self.company["approvalRequired"]=True
        with self.assertRaises(ValueError):preview(self.company,"INV-ID",2919,self.now)
        self.inv.update(approvalAction="approve",approvalActor="approver@example.invalid",createdBy="staff@example.invalid")
        preview(self.company,"INV-ID",2919,self.now)
    def test_existing_activity(self):
        self.inv["lhdn"]["attempts"]=[{"result":"unknown"}]
        with self.assertRaises(ValueError):preview(self.company,"INV-ID",2919,self.now)
    def test_invalid_buyer(self):
        self.company["customers"][0]["system"]=True
        with self.assertRaises(ValueError):preview(self.company,"INV-ID",2919,self.now)
    def test_wrong_date(self):
        self.inv["issueDate"]="2026-11-26"
        with self.assertRaises(ValueError):preview(self.company,"INV-ID",2919,self.now)
    def test_currency(self):
        self.inv.update(currency="USD",fxRate="4.12")
        self.assertIn(b'"currencyID":"USD"',preview(self.company,"INV-ID",2919,self.now)["document"])

if __name__=="__main__":
    unittest.main()
