"""Operator-only Sandbox dispatch adapter. No CLI or public route.
Requires a separate local Sandbox database, exact private grant, operator-approved
TIN and BRN, committed reservation and separate Edge secret. Never use live app.connect.
"""
from datetime import datetime,timezone,timedelta
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
from hashlib import sha256
import json,re,ssl
from uuid import UUID
import business_lhdn as central
from lhdn_lifecycle_candidate import reserve,row,accept,outcome_unknown,scoped
from lhdn_protocol_candidate import require,parse_time,_unique_object

URL="https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-lhdn-sandbox-dispatch"
def grant():
    d=json.loads(central.private_text("sandbox-dispatch-grant.json"),object_pairs_hook=_unique_object)
    require(isinstance(d,dict) and set(d)=={"tenant_id","taxpayer","document_hash","code_number","expires_at"},"Exact private grant required")
    require(isinstance(d["tenant_id"],str) and str(UUID(d["tenant_id"]))==d["tenant_id"],"Invalid grant tenant")
    require(isinstance(d["taxpayer"],str) and central.TIN.fullmatch(d["taxpayer"]),"Invalid grant TIN")
    require(isinstance(d["document_hash"],str) and re.fullmatch("[a-f0-9]{64}",d["document_hash"]),"Invalid grant hash")
    require(isinstance(d["code_number"],str) and 0<len(d["code_number"])<=50,"Invalid grant code")
    return d
def verify_grant(g,company_id,tin,brn,x,now):
    require(isinstance(now,datetime) and now.tzinfo is not None,"UTC clock required")
    require(timedelta(0)<parse_time(g["expires_at"])-now<=timedelta(minutes=15),"Grant expired or too broad")
    require(g["tenant_id"]==str(company_id) and g["taxpayer"]==tin==x["tin"],"Grant tenant mismatch")
    require(central.approved_target(company_id,tin,brn,"sandbox")==tin,"Approved corporate Sandbox pilot required")
    require(g["document_hash"]==x["hash"]==sha256(bytes(x["bytes"])).hexdigest() and g["code_number"]==x["code"],"Grant document mismatch")
def post_once(g,payload):
    key=central.private_text("sandbox-dispatch-secret").strip()
    require(re.fullmatch("[a-f0-9]{64}",key),"Invalid dispatch secret")
    data=json.dumps({"environment":"sandbox","tenant_id":g["tenant_id"],"taxpayer":g["taxpayer"],"payload":payload},separators=(",",":")).encode()
    require(len(data)<=350000,"Envelope too large")
    req=Request(URL,data=data,method="POST",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"})
    opener=build_opener(ProxyHandler({}),central.NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(req,timeout=60) as response:
        require(response.status==200,"Dispatch requires review")
        raw=response.read(65537)
        require(len(raw)<=65536,"Oversized response")
        result=json.loads(raw,object_pairs_hook=_unique_object)
    require(isinstance(result,dict) and result.get("state")=="accepted" and result.get("http_status")==202,"Dispatch requires reconciliation")
    return result["receipt"]
def check_database(conn):
    identity=conn.execute("SELECT current_database(),current_user").fetchone()
    require(identity==("myr_lhdn_sandbox","myr_lhdn_sandbox_worker"),"Only isolated sandbox worker DB is permitted")
    conn.commit()
def bind(conn,key):
    company=conn.execute("SELECT tin,data->>'brn' FROM myr_native.companies WHERE id=%s AND status='active' FOR UPDATE",(key[0],)).fetchone()
    require(company is not None,"Company unavailable")
    x=row(conn,key)
    return company[0],company[1],x
def run_once(connect,company_id,invoice_id,version):
    """Call only from a reviewed private operator harness. No recurring job yet."""
    key=scoped(company_id,invoice_id,"sandbox")
    g=grant()
    with connect() as c:
        check_database(c)
        tin,brn,x=bind(c,key)
        verify_grant(g,key[0],tin,brn,x,datetime.now(timezone.utc))
        payload=reserve(c,*key,version,datetime.now(timezone.utc))
        c.commit()
    # Reservation is durable before any network operation.
    try:
        require(grant()==g,"Operator grant changed")
        with connect() as c:
            check_database(c)
            tin,brn,x=bind(c,key)
            require(x["state"]=="dispatching","Reservation changed")
            verify_grant(g,key[0],tin,brn,x,datetime.now(timezone.utc))
        receipt=post_once(g,payload)
        with connect() as c:
            check_database(c)
            r=accept(c,*key,202,receipt,datetime.now(timezone.utc))
            c.commit()
        return {"state":"accepted","uuid":r.uuid,"environment":"sandbox"}
    except Exception:
        # Do not unlock or replay on any ambiguous result.
        with connect() as c:
            check_database(c)
            outcome_unknown(c,*key,datetime.now(timezone.utc))
            c.commit()
        return {"state":"outcome_unknown","retry_enabled":False,"environment":"sandbox"}
