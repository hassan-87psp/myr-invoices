"""Billplz sandbox candidate, no live endpoint or real billing receipt writes.
One committed reservation per period. Network uncertainty must be reconciled
by an operator, never by silently issuing another payable bill.
"""
import base64, hashlib, hmac, json, re
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from urllib.parse import urlencode, parse_qsl
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

ORIGIN="https://www.billplz-sandbox.com"
API=ORIGIN+"/api/v3/bills"
CALLBACK="https://myrinvoice.com/billing/sandbox/billplz/callback"
REDIRECT="https://myrinvoice.com/billing/sandbox/billplz/return"
ID=re.compile(r"[A-Za-z0-9_-]{1,100}")
EMAIL=re.compile(r"[^@\s<>|]+@[^@\s<>|]+\.[^@\s<>|]+")
class Reject(ValueError):pass
def require(ok,message):
    if not ok:raise Reject(message)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def request_json(method,bill_id,params,key):
    require(isinstance(key,str) and 1<=len(key)<=512 and not any(x in key for x in ":\r\n"),"Invalid sandbox credential")
    require((method=="POST" and bill_id is None) or (method=="GET" and isinstance(bill_id,str) and ID.fullmatch(bill_id)),"Invalid API operation")
    auth=base64.b64encode((key+":").encode()).decode()
    body=urlencode(params).encode() if method=="POST" else None
    req=Request(API+("/"+bill_id if bill_id else ""),data=body,method=method,
        headers={"Authorization":"Basic "+auth,"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json"})
    with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=20) as res:
        require(res.status in ((200,201) if method=="POST" else (200,)),"Provider response rejected")
        data=res.read(65537)
        require(len(data)<=65536,"Provider response too large")
        out=json.loads(data)
        require(isinstance(out,dict),"Invalid provider response")
        return out

def signature_payload(params):
    return "|".join(sorted((k+v for k,v in params.items() if k!="x_signature"),key=str.lower)).encode()
def parse_callback(body,key):
    require(isinstance(body,bytes) and 0<len(body)<=8192,"Invalid callback size")
    require(isinstance(key,str) and 1<=len(key)<=512,"Invalid signing key")
    pairs=parse_qsl(body.decode("utf-8"),keep_blank_values=True,strict_parsing=True,max_num_fields=40,errors="strict")
    require(len({k.lower() for k,v in pairs})==len(pairs),"Duplicate callback key")
    require(all(re.fullmatch(r"[a-z][a-z0-9_]{0,60}",k) and "|" not in v and not any(ord(c)<32 for c in v) for k,v in pairs),"Ambiguous callback")
    params=dict(pairs)
    sig=params.get("x_signature","")
    require(re.fullmatch(r"[a-fA-F0-9]{64}",sig) and hmac.compare_digest(hmac.new(key.encode(),signature_payload(params),hashlib.sha256).hexdigest(),sig.lower()),"Invalid callback signature")
    require(ID.fullmatch(params.get("id","")) and ID.fullmatch(params.get("collection_id","")),"Invalid callback identifiers")
    return params

def guard(conn):
    require(conn.execute("SELECT current_database(),current_user,inet_server_addr()").fetchone() in
        (("myr_lhdn_rehearsal","myr_lhdn_test",None),("myr_billing_sandbox","myr_billing_sandbox_worker",None)),"Isolated sandbox DB required")

def provider_state(data,collection,amount,bill_id):
    require(isinstance(data,dict) and data.get("id")==bill_id and data.get("collection_id")==collection,"Provider identity mismatch")
    require(type(data.get("amount")) is int and data["amount"]==amount,"Provider amount mismatch")
    paid=data.get("paid");state=data.get("state");actual=data.get("paid_amount")
    if paid is True and state=="paid" and type(actual) is int and actual==amount:return "paid"
    if paid is False and state in ("due","deleted") and type(actual) is int and actual==0:return state
    raise Reject("Ambiguous provider settlement")

def checkout(conn,actor,company,period,collection,key,send=request_json):
    guard(conn)
    require(isinstance(collection,str) and ID.fullmatch(collection),"Invalid collection")
    row=conn.execute("""SELECT p.amount_sen,p.plan,p.period_start,u.email
       FROM myr_native.billing_periods p JOIN myr_native.companies c ON c.id=p.company_id
       JOIN myr_native.company_members m ON m.company_id=c.id
       JOIN myr_native.users u ON u.email=m.email
       WHERE p.id=%s AND c.id=%s AND u.id=%s AND u.email_verified_at IS NOT NULL AND NOT u.disabled
       AND m.role='Owner' AND m.status='active' AND c.status='active' AND p.plan=c.plan
       AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
       AND NOT EXISTS (SELECT 1 FROM myr_native.billing_receipts r WHERE r.period_id=p.id)
       FOR UPDATE OF c""",(period,company,actor)).fetchone()
    require(row is not None,"Checkout not available")
    amount,plan,month,email=row
    require(month==datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().replace(day=1),"Current billing period required")
    require(amount in (900,1900,3900) and isinstance(email,str) and EMAIL.fullmatch(email),"Invalid checkout details")
    attempt=uuid4()
    inserted=conn.execute("""INSERT INTO myr_native.billing_gateway_sandbox(period_id,attempt_id,collection_id,amount_sen,state)
       VALUES(%s,%s,%s,%s,'reserved') ON CONFLICT(period_id) DO NOTHING RETURNING period_id""",(period,attempt,collection,amount)).fetchone()
    require(inserted is not None,"Existing attempt; reconcile before any retry")
    conn.commit()
    payload={"collection_id":collection,"email":email,"name":"MYR Invoice sandbox customer",
        "amount":amount,"description":"MYR Invoice "+plan+" "+month.isoformat(),
        "callback_url":CALLBACK,"redirect_url":REDIRECT,"deliver":"false",
        "reference_1_label":"Billing attempt","reference_1":str(attempt)}
    try:
        data=send("POST",None,payload,key)
        bill=data.get("id")
        require(isinstance(bill,str) and ID.fullmatch(bill),"Invalid bill identifier")
        require(data.get("url")==ORIGIN+"/bills/"+bill,"Unexpected checkout URL")
        require(provider_state(data,collection,amount,bill)=="due","Unexpected new bill state")
        require(data.get("reference_1")==str(attempt),"Attempt reference mismatch")
        conn.execute("""UPDATE myr_native.billing_gateway_sandbox SET state='due',bill_id=%s,updated_at=now()
          WHERE period_id=%s AND state='reserved'""",(bill,period))
        conn.commit()
        return data["url"]
    except Exception:
        conn.rollback()
        conn.execute("""UPDATE myr_native.billing_gateway_sandbox SET state='unknown',updated_at=now()
          WHERE period_id=%s AND state='reserved'""",(period,))
        conn.commit()
        raise Reject("Checkout outcome unknown; do not create another bill") from None

def reconcile_callback(conn,body,signing_key,api_key,send=request_json):
    guard(conn)
    params=parse_callback(body,signing_key)
    row=conn.execute("""SELECT period_id,collection_id,amount_sen,state FROM myr_native.billing_gateway_sandbox
        WHERE bill_id=%s""",(params["id"],)).fetchone()
    require(row is not None and row[1]==params["collection_id"],"Unknown sandbox bill")
    period,collection,amount,previous=row
    require(params.get("amount")==str(amount),"Callback amount mismatch")
    data=send("GET",params["id"],None,api_key)
    state=provider_state(data,collection,amount,params["id"])
    # Lock after the remote read, then recheck state to prevent stale callbacks
    # overwriting a verified terminal result.
    current=conn.execute("SELECT state FROM myr_native.billing_gateway_sandbox WHERE period_id=%s FOR UPDATE",(period,)).fetchone()[0]
    if current in ("paid","deleted"):
        require(state==current or state=="due","Conflicting terminal status")
        state=current
    else:
        conn.execute("UPDATE myr_native.billing_gateway_sandbox SET state=%s,updated_at=now() WHERE period_id=%s",(state,period))
    conn.commit()
    return {"sandbox_state":state,"real_payment_recorded":False,"entitlement_changed":False}
