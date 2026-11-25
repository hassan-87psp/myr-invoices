"""Native public-link lookup and submission core.
Private candidate only: no anonymous Internet routes until cutover.
Never return QR buyer PII to a subsequent holder of the token.
"""
import re
from uuid import uuid4
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb
from native_record_writes import require, WriteRejected, encode
from app import connect

def lookup(conn,token,lock=False):
    require(isinstance(token,str) and re.fullmatch(r"[A-Za-z0-9_-]{20,128}",token),"Link unavailable")
    sql="""SELECT l.company_id,l.kind,l.ref_id,l.expires_at,l.closed,l.meta,l.data,l.submits,c.name
        FROM myr_native.public_links l JOIN myr_native.companies c ON c.id=l.company_id
        WHERE l.token=%s AND c.status='active' AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'"""
    if lock:
        sql+=" FOR UPDATE OF l FOR SHARE OF c"
    row=conn.execute(sql,(token,)).fetchone()
    require(row is not None and not row[4] and row[3]>=datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date(),"Link unavailable")
    return row

def read_link(conn,token):
    cid,kind,ref,expiry,closed,meta,data,submits,name=lookup(conn,token)
    if kind=="qr":
        # A public form must not disclose a previous buyer's identity.
        meta={k:meta[k] for k in ("label","receipt","state") if k in meta}
        meta["received"]=bool(submits)
        data=None
    else:
        # Existing issued portal snapshot, not a live company database dump.
        require(isinstance(meta,dict) and isinstance(meta.get("invoice"),dict) and isinstance(meta.get("company"),dict),"Link unavailable")
        meta={k:meta[k] for k in ("invoice","company","paid") if k in meta}
        data=None
    return {"kind":kind,"expires_at":expiry,"closed":False,"meta":meta,"data":data,"company_name":name}

def submit_link(conn,token,payload):
    require(isinstance(payload,dict) and len(encode(payload))<=12000,"Invalid submission")
    cid,kind,ref,expiry,closed,meta,old,submits,name=lookup(conn,token,True)
    require(submits<10,"Submission limit reached")
    now=datetime.now(timezone.utc).isoformat()
    if kind=="qr":
        fields=("name","tin","idType","idValue","email","phone","receipt")
        require(set(payload)==set(fields)|{"addr","consent"} and payload["consent"] is True,"Consent and buyer details required")
        require(all(isinstance(payload[k],str) and len(payload[k])<=300 for k in fields),"Invalid buyer details")
        require(payload["name"].strip() and re.fullmatch(r"[A-Z]{1,2}\d{8,12}",payload["tin"].upper()) is not None,"Invalid buyer identity")
        require(payload["idType"] in ("BRN","NRIC","PASSPORT","ARMY") and payload["idValue"].strip(),"Invalid identity type")
        require(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",payload["email"]) is not None,"Invalid email")
        addr=payload["addr"]
        require(isinstance(addr,dict) and set(addr)=={"line","city","postcode","state","country"} and all(isinstance(v,str) and len(v)<=300 for v in addr.values()),"Invalid address")
        require(addr["line"].strip() and addr["city"].strip() and re.fullmatch(r"[A-Z]{3}",addr["country"]),"Invalid address")
        require(not old and submits==0,"Request already received")
        data={k:payload[k] for k in fields}
        data.update(addr=addr,at=now,consent=True)
    else:
        require(set(payload)=={"message","email"} and all(isinstance(v,str) for v in payload.values()),"Invalid correction")
        require(1<=len(payload["message"].strip())<=500 and len(payload["email"])<=254,"Invalid correction")
        require(not payload["email"] or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",payload["email"]),"Invalid email")
        require(old is None or isinstance(old,dict),"Invalid stored corrections")
        data=dict(old or {})
        corrections=data.get("corrections",[])
        require(isinstance(corrections,list) and len(corrections)<10,"Submission limit reached")
        data["corrections"]=corrections+[{"id":uuid4().hex,"message":payload["message"].strip(),"email":payload["email"],"at":now}]
    conn.execute("UPDATE myr_native.public_links SET data=%s,submits=submits+1 WHERE token=%s",(Jsonb(data),token))
    return {"status":"received"}

def test():
    uid,cid=uuid4(),uuid4()
    email="link-"+uid.hex+"@example.invalid"
    token,invoice_token,expired=uuid4().hex,uuid4().hex,uuid4().hex
    conn=connect()
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,disabled) VALUES(%s,%s,true)",(uid,email))
        conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Link rollback fixture',%s,%s)",(cid,uid,Jsonb({"requests":[{"id":"qr"}],"invoices":[{"id":"inv"}]})))
        for t,kind,ref,meta,delta in ((token,"qr","qr",{"label":"Test"},1),(invoice_token,"invoice","inv",{"invoice":{"id":"inv"},"company":{"name":"Test"},"paid":0},1),(expired,"qr","qr",{},-2)):
            conn.execute("INSERT INTO myr_native.public_links(token,company_id,kind,ref_id,expires_at,closed,meta) VALUES(%s,%s,%s,%s,current_date+%s,false,%s)",(t,cid,kind,ref,delta,Jsonb(meta)))
        assert read_link(conn,token)["data"] is None
        reject(lambda:read_link(conn,expired))
        p={"name":"Test Buyer","tin":"C12345678901","idType":"BRN","idValue":"123456789012","email":"buyer@example.invalid","phone":"000","receipt":"","consent":True,"addr":{"line":"Test","city":"Test","postcode":"00000","state":"14","country":"MYS"}}
        reject(lambda:submit_link(conn,token,{**p,"consent":False}))
        assert submit_link(conn,token,p)["status"]=="received"
        assert read_link(conn,token)["data"] is None
        reject(lambda:submit_link(conn,token,p))
        assert submit_link(conn,invoice_token,{"message":"Test correction","email":""})["status"]=="received"
        assert read_link(conn,invoice_token)["data"] is None
        conn.execute("UPDATE myr_native.public_links SET closed=true WHERE token=%s",(invoice_token,))
        reject(lambda:read_link(conn,invoice_token))
        conn.execute("UPDATE myr_native.companies SET status='suspended' WHERE id=%s",(cid,))
        reject(lambda:read_link(conn,token))
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.users WHERE id=%s",(uid,)).fetchone()[0]==0
    print("MYR_PUBLIC_LINK_SUBMISSION_ROLLBACK_OK")

if __name__=="__main__":
    test()
