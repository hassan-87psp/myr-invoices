"""VPS native record-write core; not yet exposed by the private web preview.

Run this module directly for a rollback-only database acceptance test. All
fixtures are synthetic. No Supabase, email, LHDN or public link requests.
"""
import copy
import json
import math
from uuid import uuid4
from psycopg.types.json import Jsonb
from app import connect

KINDS = {"customers", "products", "invoices"}
LHDN_EMPTY = {"status": "Not Submitted", "submissionUid": "", "uuid": "",
              "longId": "", "validatedAt": "", "errors": [], "attempts": []}
ROLES = ("Owner", "Admin", "Accountant", "Invoice Staff")

class WriteRejected(Exception):
    pass

def require(ok, message):
    if not ok:
        raise WriteRejected(message)

def text_id(value):
    return isinstance(value, str) and 1 <= len(value) <= 128

def encode(value):
    try:
        return json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WriteRejected("Invalid JSON payload") from None

def number(value):
    return type(value) in (int, float) and math.isfinite(value)

def record_rows(data, kind):
    rows = data.get(kind, [])
    require(isinstance(rows, list) and all(isinstance(r, dict) and text_id(r.get("id")) for r in rows), "Invalid existing records")
    require(len({r["id"] for r in rows}) == len(rows), "Duplicate existing record IDs")
    return rows

def save_record(conn, actor_id, actor_email, company_id, kind, record, expected):
    """One authorized transaction; caller must supply a VERIFIED identity.

    Only upserts ordinary customer/product records and unpaid, unsubmitted
    invoice drafts. No deletion, payment, approval, team or company mutation.
    """
    require(kind in KINDS, "Unsupported record type")
    require(isinstance(record, dict) and len(encode(record)) <= 500000, "Invalid record payload")
    rid = record.get("id")
    require(text_id(rid), "Invalid record ID")
    row = conn.execute("""SELECT c.version,c.data FROM myr_native.companies c
        JOIN myr_native.company_members m ON m.company_id=c.id
        JOIN myr_native.users u ON u.email=m.email
        WHERE c.id=%s AND c.status='active' AND u.id=%s AND u.email=%s
          AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
          AND m.status='active' AND m.role=ANY(%s)
        FOR UPDATE OF c FOR SHARE OF m,u""",
        (company_id, actor_id, actor_email, list(ROLES))).fetchone()
    require(row is not None, "Not authorized for this company")
    version, previous = row
    require(isinstance(previous, dict), "Invalid company snapshot")
    data = copy.deepcopy(previous)
    rows = record_rows(data, kind)
    old = next((r for r in rows if r["id"] == rid), None)
    # Full expected-record comparison prevents stale record overwrite.
    require(old == expected, "Record changed; reload before editing")
    rec = copy.deepcopy(record)
    if kind != "invoices":
        require(isinstance(rec.get("name"), str) and 0 < len(rec["name"].strip()) <= 300, "Record name required")
        if kind == "customers":
            require(not rec.get("system") and not (old or {}).get("system"), "System customer is protected")
    else:
        require(rec.get("appStatus") in ("Draft", "Ready"), "Only draft/ready invoices are enabled")
        require(rec.get("docType") == "01", "Only ordinary invoices are enabled in this stage")
        require(not rec.get("payments"), "Payments are disabled in this stage")
        require(not rec.get("share"), "Public invoice links are disabled")
        require(not old or (old.get("appStatus") in ("Draft", "Ready") and not old.get("payments") and not old.get("share")
            and (old.get("lhdn") or {}).get("status", "Not Submitted") == "Not Submitted"), "Existing invoice is protected")
        require(conn.execute("SELECT 1 FROM myr_native.lhdn_documents WHERE company_id=%s AND invoice_id=%s",(company_id,rid)).fetchone() is None, "Official invoice is protected")
        n = rec.get("number")
        require(isinstance(n,str) and 0 < len(n.strip()) <= 80, "Invoice number required")
        require(not any(r["id"] != rid and str(r.get("number","")).strip().casefold() == n.strip().casefold() for r in rows), "Duplicate invoice number")
        require(not old or old.get("number") == n, "Existing invoice number cannot change")
        require(any(c["id"] == rec.get("customerId") and not c.get("archived") for c in record_rows(data,"customers")), "Active customer required")
        items = rec.get("items")
        require(isinstance(items,list) and 0 < len(items) <= 1000, "Invoice items required")
        for it in items:
            require(isinstance(it,dict) and text_id(it.get("id")), "Invalid invoice line")
            require(all(number(it.get(k,0)) and 0 <= it.get(k,0) <= 10**12 for k in ("qty","price","discount","taxRate")), "Invalid invoice amounts")
            require(it.get("qty",0)>0 and it.get("taxRate",0)<=100, "Invalid quantity or tax")
        require(len({it["id"] for it in items}) == len(items), "Duplicate invoice line IDs")
        rec["lhdn"] = copy.deepcopy(LHDN_EMPTY)
        rec["payments"] = []
        rec["createdBy"] = old.get("createdBy",actor_email) if old else actor_email
        if old:
            rec["createdAt"] = old.get("createdAt")
        else:
            # Counter must advance only for the exact current automatic number.
            prefix, counter = data.get("prefix","INV-"), data.get("nextNo",1001)
            require(isinstance(prefix,str) and type(counter) is int and 0 < counter < 10**12, "Invalid invoice counter")
            if n == prefix + str(counter):
                data["nextNo"] = counter+1
    data[kind] = [rec if r["id"] == rid else r for r in rows] if old else rows+[rec]
    conn.execute("""INSERT INTO myr_native.company_revisions(company_id,version,data)
        VALUES(%s,%s,%s) ON CONFLICT(company_id,version) DO NOTHING""",
        (company_id,version,Jsonb(previous)))
    conn.execute("""UPDATE myr_native.companies SET data=%s,version=%s,updated_at=now()
        WHERE id=%s""",(Jsonb(data),version+1,company_id))
    conn.execute("""INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail)
        VALUES(%s,%s,%s,%s,%s)""",(company_id,actor_id,actor_email,
        kind+(".update" if old else ".create"),"Record "+rid))
    return {"version":version+1,"company_data":data,"record":rec,
            "kind":kind,"operation":"updated" if old else "created"}

def test():
    uid,cid,other = uuid4(),uuid4(),uuid4()
    email = "test-"+uid.hex+"@example.invalid"
    def expect_reject(fn):
        try:
            fn()
        except WriteRejected:
            return
        raise AssertionError("Expected rejection")
    conn=connect()
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        for company in (cid,other):
            conn.execute("""INSERT INTO myr_native.companies(id,name,created_by,data)
                VALUES(%s,'Synthetic rollback test',%s,%s)""",
                (company,uid,Jsonb({"customers":[],"products":[],"invoices":[],"prefix":"TEST-","nextNo":1})))
        conn.execute("""INSERT INTO myr_native.company_members(company_id,email,role,status)
            VALUES(%s,%s,'Owner','active')""",(cid,email))
        customer={"id":str(uuid4()),"name":"Synthetic customer","archived":False}
        product={"id":str(uuid4()),"name":"Synthetic product","price":1000}
        invoice={"id":str(uuid4()),"number":"TEST-1","docType":"01","appStatus":"Draft",
                 "customerId":customer["id"],"items":[{"id":str(uuid4()),"qty":1,"price":1000,"discount":0,"taxRate":0}],"payments":[]}
        def save(k,r,e=None,company=cid):
            return save_record(conn,uid,email,company,k,r,e)
        assert save("customers",customer)["version"]==2
        assert save("products",product)["version"]==3
        r=save("invoices",invoice)
        assert r["version"]==4 and r["company_data"]["nextNo"]==2
        assert r["record"]["lhdn"]["status"]=="Not Submitted"
        old=r["record"]
        edited={**old,"notes":"Synthetic update"}
        assert save("invoices",edited,old)["version"]==5
        expect_reject(lambda:save("invoices",edited,old))
        expect_reject(lambda:save("invoices",{**invoice,"id":str(uuid4())}))
        expect_reject(lambda:save("customers",customer,company=other))
        expect_reject(lambda:save("invoices",{**invoice,"id":str(uuid4()),"number":"TEST-2","payments":[{"amount":100}]}))
        expect_reject(lambda:save("invoices",{**invoice,"id":str(uuid4()),"number":"TEST-2","appStatus":"Submitted"}))
        conn.execute("UPDATE myr_native.company_members SET role='Read-Only' WHERE company_id=%s AND email=%s",(cid,email))
        expect_reject(lambda:save("products",{**product,"id":str(uuid4())}))
        assert conn.execute("SELECT count(*) FROM myr_native.company_revisions WHERE company_id=%s",(cid,)).fetchone()[0]==4
        assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s",(cid,)).fetchone()[0]==4
        assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]==5
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.companies WHERE id=ANY(%s)",([cid,other],)).fetchone()[0]==0
    print("VPS_NATIVE_RECORD_WRITE_ROLLBACK_TEST_OK")
    print("Draft invoice, customer, product, revision, audit, stale edit and tenant rejection tested.")
    print("HTTP/UI writes remain disabled; synthetic records rolled back.")

if __name__=="__main__":
    test()
