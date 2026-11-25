"""Transactional manual payment logging for private native rehearsals.
No payment processing, bank calls, email or LHDN requests.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from uuid import uuid4
from psycopg.types.json import Jsonb
from native_record_writes import require, text_id, record_rows, ROLES, WriteRejected, encode
from app import connect

def round_sen(value):
    return int(value.quantize(Decimal("1"),rounding=ROUND_HALF_UP))

def decimal_value(value):
    require(type(value) in (int,float) and 0<=value<=10**12,"Invalid invoice amount")
    return Decimal(str(value))

def total_sen(invoice):
    items=invoice.get("items")
    require(isinstance(items,list) and 0<len(items)<=1000,"Invalid invoice lines")
    total=0
    for line in items:
        require(isinstance(line,dict),"Invalid invoice line")
        gross=round_sen(decimal_value(line.get("qty",0))*decimal_value(line.get("price",0)))
        net=Decimal(gross)-min(decimal_value(line.get("discount",0)),Decimal(gross))
        rate=decimal_value(line.get("taxRate",0))
        require(rate<=100 and net==int(net),"Invalid tax or discount")
        total+=int(net)+round_sen(net*rate/100)
    require(0<=total<=9007199254740991,"Invoice total outside safe range")
    return total

def lock_company(conn,uid,email,cid):
    row=conn.execute("""SELECT c.version,c.data FROM myr_native.companies c
        JOIN myr_native.company_members m ON m.company_id=c.id
        JOIN myr_native.users u ON u.email=m.email
        WHERE c.id=%s AND c.status='active' AND u.id=%s AND u.email=%s
        AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
        AND m.status='active' AND m.role=ANY(%s)
        FOR UPDATE OF c FOR SHARE OF m,u""",(cid,uid,email,list(ROLES))).fetchone()
    require(row is not None,"Not authorized for this company")
    return row

def persist(conn,uid,email,cid,version,previous,data,action,detail):
    conn.execute("""INSERT INTO myr_native.company_revisions(company_id,version,data)
        VALUES(%s,%s,%s) ON CONFLICT(company_id,version) DO NOTHING""",(cid,version,Jsonb(previous)))
    conn.execute("UPDATE myr_native.companies SET data=%s,version=%s,updated_at=now() WHERE id=%s",(Jsonb(data),version+1,cid))
    conn.execute("""INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail)
        VALUES(%s,%s,%s,%s,%s)""",(cid,uid,email,action,detail))

def add_payment(conn,uid,email,cid,invoice_id,payment):
    require(text_id(invoice_id) and isinstance(payment,dict) and len(encode(payment))<=10000,"Invalid payment")
    pid,amount=payment.get("id"),payment.get("amount")
    require(text_id(pid) and type(amount) is int and 0<amount<=9007199254740991,"Positive integer sen required")
    try:
        day=date.fromisoformat(payment.get("date",""))
        require(day.isoformat()==payment.get("date") and day<=datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date(),"Invalid payment date")
    except (ValueError,TypeError):
        raise WriteRejected("Invalid payment date") from None
    method,ref=payment.get("method"),payment.get("ref","")
    require(isinstance(method,str) and 0<len(method)<=100 and isinstance(ref,str) and len(ref)<=300,"Invalid payment details")
    version,previous=lock_company(conn,uid,email,cid)
    invoices=record_rows(previous,"invoices")
    inv=next((r for r in invoices if r["id"]==invoice_id),None)
    require(inv is not None and inv.get("docType")=="01" and inv.get("appStatus") in ("Draft","Ready"),"Invoice unavailable")
    require((inv.get("lhdn") or {}).get("status")=="Not Submitted","Official invoice protected in preview")
    require(conn.execute("SELECT 1 FROM myr_native.lhdn_documents WHERE company_id=%s AND invoice_id=%s",(cid,invoice_id)).fetchone() is None,"Official invoice protected")
    payments=inv.get("payments",[])
    require(isinstance(payments,list) and all(isinstance(p,dict) and type(p.get("amount")) is int and p["amount"]>0 for p in payments),"Invalid existing payments")
    safe={"id":pid,"date":day.isoformat(),"amount":amount,"method":method,"ref":ref,"by":email}
    existing=next((p for p in payments if p.get("id")==pid),None)
    if existing:
        require(all(existing.get(k)==v for k,v in safe.items()),"Payment ID already used")
        return {"version":version,"company_data":previous,"existing":True}
    require(not any(p.get("id")==pid for r in invoices for p in r.get("payments",[])),"Payment ID already used")
    require(sum(p["amount"] for p in payments)+amount<=total_sen(inv),"Payment exceeds remaining balance")
    safe["at"]=datetime.now(timezone.utc).isoformat()
    updated={**inv,"payments":payments+[safe]}
    data={**previous,"invoices":[updated if r["id"]==invoice_id else r for r in invoices]}
    persist(conn,uid,email,cid,version,previous,data,"payment.record","Invoice "+invoice_id+" payment "+pid)
    return {"version":version+1,"company_data":data,"invoice":updated,"existing":False}

def delete_record(conn,uid,email,cid,kind,expected):
    require(kind in ("products","invoices") and isinstance(expected,dict) and text_id(expected.get("id")),"Invalid deletion")
    rid=expected["id"]
    version,previous=lock_company(conn,uid,email,cid)
    rows=record_rows(previous,kind)
    old=next((r for r in rows if r["id"]==rid),None)
    require(old is not None and old==expected,"Record changed; reload before deleting")
    if kind=="invoices":
        status=old.get("lhdn") or {}
        require(old.get("appStatus") in ("Draft","Ready") and status.get("status")=="Not Submitted" and not status.get("attempts") and not old.get("payments") and not old.get("share"),"Invoice protected")
        require(conn.execute("SELECT 1 FROM myr_native.lhdn_documents WHERE company_id=%s AND invoice_id=%s",(cid,rid)).fetchone() is None,"Official invoice protected")
        require(not any(r.get("refInvoiceId")==rid for r in rows if r["id"]!=rid),"Invoice is referenced by another document")
    data={**previous,kind:[r for r in rows if r["id"]!=rid]}
    persist(conn,uid,email,cid,version,previous,data,kind+".delete","Record "+rid)
    return {"version":version+1,"company_data":data}

def test():
    uid,cid=uuid4(),uuid4()
    email="test-"+uid.hex+"@example.invalid"
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    product={"id":"product","name":"Dummy"}
    invoice={"id":"invoice","docType":"01","appStatus":"Draft","items":[{"qty":2,"price":1000,"discount":100,"taxRate":10}],"payments":[],"lhdn":{"status":"Not Submitted"}}
    assert total_sen(invoice)==2090
    conn=connect()
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Synthetic payment rollback',%s,%s)",(cid,uid,Jsonb({"products":[product],"invoices":[invoice]})))
        conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
        p={"id":"p1","amount":1000,"date":date.today().isoformat(),"method":"Cash","ref":""}
        def pay(x): return add_payment(conn,uid,email,cid,"invoice",x)
        assert pay(p)["version"]==2
        assert pay(p)["existing"] is True
        reject(lambda:pay({**p,"amount":999}))
        reject(lambda:pay({**p,"id":"p2","amount":1091}))
        reject(lambda:delete_record(conn,uid,email,cid,"invoices",invoice))
        assert pay({**p,"id":"p2","amount":1090})["version"]==3
        assert delete_record(conn,uid,email,cid,"products",product)["version"]==4
        reject(lambda:delete_record(conn,uid,email,cid,"products",product))
        conn.execute("UPDATE myr_native.company_members SET role='Read-Only' WHERE company_id=%s AND email=%s",(cid,email))
        reject(lambda:pay({**p,"id":"p3"}))
        assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s",(cid,)).fetchone()[0]==3
    finally:
        conn.rollback()
        conn.close()
    with connect() as c:
        assert c.execute("SELECT count(*) FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]==0
    print("VPS_PAYMENT_AND_DELETE_ROLLBACK_OK")
if __name__=="__main__":
    test()
