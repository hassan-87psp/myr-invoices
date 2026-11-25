"""Server-owned customer sharing and QR request mutations. All changes atomic."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from secrets import token_urlsafe
from uuid import uuid4
from psycopg.types.json import Jsonb
from native_record_writes import require, record_rows, text_id, WriteRejected
from native_team_workflow import locked_company
from native_payment_ops import persist
from business_links import read_link, submit_link
from app import connect

ROLES=("Owner","Admin","Accountant","Invoice Staff")
def today(): return datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date()
def stamp(): return datetime.now(timezone.utc).isoformat()
def pick(obj,keys): return {k:obj[k] for k in keys.split() if k in obj}
def public_snapshot(co,inv):
    customer=next((r for r in record_rows(co,"customers") if r["id"]==inv.get("customerId")),None)
    require(customer is not None,"Invoice customer missing")
    party="id name tin idType idValue brn sst msic msicDesc email phone addr"
    company=pick(co,party+" logo")
    company["lhdn"]={"env":(co.get("lhdn") or {}).get("env","sandbox")}
    company["customers"]=[pick(customer,party)]
    ref=next((r for r in record_rows(co,"invoices") if r["id"]==inv.get("refInvoiceId")),None)
    company["invoices"]=[pick(ref,"id number")] if ref else []
    public=pick(inv,"id number docType customerId issueDate dueDate currency fxRate payTerms notes consolidated refInvoiceId appStatus")
    public["items"]=[pick(r,"id desc classCode unitCode qty price discount taxType taxRate") for r in inv.get("items",[])]
    public["payments"]=[pick(p,"date amount method") for p in inv.get("payments",[])]
    public["lhdn"]=pick(inv.get("lhdn") or {},"status uuid longId validatedAt")
    return {"invoice":public,"company":company,"paid":sum(p.get("amount",0) for p in inv.get("payments",[]))}

def operate(conn,uid,email,cid,version,action,payload):
    v,old,_,plan=locked_company(conn,uid,email,cid,ROLES,synthetic=False)
    require(type(version) is int and v==version,"Company changed; reload")
    require(isinstance(payload,dict),"Invalid action")
    data=dict(old)
    kind="invoice" if action in ("share","revoke") else "qr"
    key="invoices" if kind=="invoice" else "requests"
    rows=record_rows(old,key)
    rid=payload.get("id")
    record=next((r for r in rows if r["id"]==rid),None)
    result={}
    if action=="share":
        require(record is not None and (record.get("lhdn") or {}).get("status")!="Cancelled","Invoice unavailable")
        share=record.get("share") or {}
        token=share.get("token")
        existing=conn.execute("""SELECT token,expires_at FROM myr_native.public_links WHERE token=%s
            AND company_id=%s AND kind='invoice' AND ref_id=%s AND NOT closed AND expires_at>=%s FOR UPDATE""",
            (token,cid,rid,today())).fetchone() if token else None
        if existing:
            return {"version":v,"company_data":old,"record":record}
        expiry=today()+timedelta(days=30)
        token=token_urlsafe(32)
        updated={**record,"share":{"token":token,"exp":expiry.isoformat()}}
        conn.execute("UPDATE myr_native.public_links SET closed=true WHERE company_id=%s AND kind='invoice' AND ref_id=%s",(cid,rid))
        conn.execute("""INSERT INTO myr_native.public_links(token,company_id,kind,ref_id,expires_at,closed,meta)
            VALUES(%s,%s,'invoice',%s,%s,false,%s)""",(token,cid,rid,expiry,Jsonb(public_snapshot(old,record))))
    elif action=="revoke":
        require(record is not None and record.get("share"),"No active share")
        conn.execute("UPDATE myr_native.public_links SET closed=true WHERE company_id=%s AND kind='invoice' AND ref_id=%s",(cid,rid))
        updated={**record,"share":None}
    elif action in ("qr_create","qr_regenerate"):
        if action=="qr_create":
            require(record is None and text_id(rid),"Invalid request ID")
            label,receipt,days=payload.get("label"),payload.get("receipt",""),payload.get("days")
            require(isinstance(label,str) and 1<=len(label.strip())<=200 and isinstance(receipt,str) and len(receipt)<=300 and type(days) is int and days in (1,3,7,30),"Invalid QR fields")
            if plan=="Starter":
                require(conn.execute("""SELECT count(*) FROM myr_native.public_links WHERE company_id=%s AND kind='qr'
                    AND NOT closed AND expires_at>=%s""",(cid,today())).fetchone()[0]<20,"Open request limit reached")
            record={"id":rid,"label":label.strip(),"receipt":receipt,"createdAt":stamp()}
        else:
            require(record is not None and record.get("status")=="Open","Only an open or expired request can be regenerated")
            existing=conn.execute("SELECT data,submits FROM myr_native.public_links WHERE token=%s AND company_id=%s FOR UPDATE",(record.get("token"),cid)).fetchone()
            require(existing is not None and not existing[0] and existing[1]==0,"Buyer already submitted; review instead")
            days=7
            conn.execute("UPDATE myr_native.public_links SET closed=true WHERE company_id=%s AND kind='qr' AND ref_id=%s",(cid,rid))
        expiry=today()+timedelta(days=days)
        token=token_urlsafe(32)
        updated={**record,"token":token,"expiresAt":expiry.isoformat(),"status":"Open","submits":0,"data":None}
        conn.execute("""INSERT INTO myr_native.public_links(token,company_id,kind,ref_id,expires_at,closed,meta)
            VALUES(%s,%s,'qr',%s,%s,false,%s)""",(token,cid,rid,expiry,Jsonb({"label":updated["label"],"receipt":updated.get("receipt",""),"state":"Open"})))
    elif action in ("qr_approve","qr_decline"):
        require(record is not None and record.get("status") in ("Open","Received"),"Request unavailable")
        link=conn.execute("""SELECT data,submits FROM myr_native.public_links WHERE token=%s AND company_id=%s
            AND kind='qr' AND ref_id=%s AND NOT closed FOR UPDATE""",(record.get("token"),cid,rid)).fetchone()
        require(link is not None and isinstance(link[0],dict) and link[1]>0,"No buyer submission")
        d=link[0]
        updated={**record,"status":"Approved" if action=="qr_approve" else "Declined","data":d,"submits":link[1]}
        if action=="qr_approve":
            customers=record_rows(old,"customers")
            matches=[c for c in customers if not c.get("system") and c.get("tin")==d.get("tin")]
            require(len(matches)<=1,"Duplicate customer TIN; resolve manually")
            c=matches[0] if matches else {"id":str(uuid4()),"creditDays":0,"archived":False,"createdAt":stamp(),"source":"qr"}
            require(not c.get("archived"),"Restore archived customer first")
            c={**c,**pick(d,"name tin idType idValue email phone addr"),"sst":d.get("sst","NA")}
            data["customers"]=[c if x["id"]==c["id"] else x for x in customers] if matches else customers+[c]
            updated["customerId"]=c["id"]
            result["customer_id"]=c["id"]
        conn.execute("""UPDATE myr_native.public_links SET closed=true,meta=jsonb_set(meta,'{state}',to_jsonb(%s::text))
            WHERE token=%s AND company_id=%s""",(updated["status"],record["token"],cid))
    else: raise WriteRejected("Unsupported link operation")
    data[key]=[updated if r["id"]==rid else r for r in rows] if any(r["id"]==rid for r in rows) else [updated]+rows
    persist(conn,uid,email,cid,v,old,data,"link."+action,rid)
    return {"version":v+1,"company_data":data,"record":updated,**result}

def test():
    uid,cid=uuid4(),uuid4()
    email="linkops-"+uid.hex+"@example.invalid"
    conn=connect()
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        invoice={"id":"inv","number":"INV-1","docType":"01","customerId":"cust","lhdn":{"status":"Not Submitted"},"items":[],"payments":[],"internal":"PRIVATE"}
        d={"name":"Test","customers":[{"id":"cust","name":"Buyer","tin":"C12345678901"}],"invoices":[invoice],"requests":[]}
        conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Link ops test',%s,%s)",(cid,uid,Jsonb(d)))
        conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
        def op(v,a,p): return operate(conn,uid,email,cid,v,a,p)
        share=op(1,"share",{"id":"inv"})["record"]["share"]
        assert "internal" not in read_link(conn,share["token"])["meta"]["invoice"]
        assert op(2,"share",{"id":"inv"})["version"]==2
        assert op(2,"revoke",{"id":"inv"})["version"]==3
        qr=op(3,"qr_create",{"id":"qr","label":"Sale","receipt":"1","days":7})["record"]
        p={"name":"Buyer","tin":"C12345678901","idType":"BRN","idValue":"123","email":"buyer@example.invalid","phone":"000","receipt":"1","consent":True,"addr":{"line":"Test","city":"Test","postcode":"00000","state":"14","country":"MYS"}}
        assert submit_link(conn,qr["token"],p)["status"]=="received"
        assert op(4,"qr_approve",{"id":"qr"})["customer_id"]=="cust"
        assert conn.execute("SELECT closed FROM myr_native.public_links WHERE token=%s",(qr["token"],)).fetchone()[0]
        conn.execute("UPDATE myr_native.company_members SET role='Read-Only' WHERE company_id=%s",(cid,))
        try: op(5,"share",{"id":"inv"})
        except WriteRejected: pass
        else: raise AssertionError("Read-only share allowed")
    finally:
        conn.rollback()
        conn.close()
    print("MYR_LINK_MANAGEMENT_ROLLBACK_OK")

if __name__=="__main__": test()
