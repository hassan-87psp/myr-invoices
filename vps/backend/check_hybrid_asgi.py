"""Exercise the actual ASGI write routes with real PostgreSQL and synthetic auth.
Runs in a separate process, uses temporary grant files, and rolls back all
fixtures. Never patches the running server or invokes real Supabase Auth.
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from psycopg.types.json import Jsonb
from fastapi import HTTPException
import hybrid_workspace as hw
import hybrid_write_test as ht
from staging_api import db
from private_preview import api
from app import connect

async def request(method,path,body=None,token="owner",client="127.0.0.1"):
    payload=json.dumps(body).encode() if body is not None else b""
    headers=[(b"content-type",b"application/json")]
    if token is not None:
        headers.append((b"authorization",("Bearer "+token).encode()))
    scope={"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},
       "http_version":"1.1","method":method,"scheme":"http","path":path,
       "raw_path":path.encode(),"query_string":b"","root_path":"",
       "headers":headers,"client":(client,12345),"server":("localhost",8765)}
    sent=False
    wait=asyncio.Event()
    messages=[]
    async def receive():
        nonlocal sent
        if not sent:
            sent=True
            return {"type":"http.request","body":payload,"more_body":False}
        await wait.wait()
        return {"type":"http.disconnect"}
    async def send(message):
        messages.append(message)
    await asyncio.wait_for(api(scope,receive,send),timeout=20)
    status=next(m["status"] for m in messages if m["type"]=="http.response.start")
    raw=b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
    return status,json.loads(raw) if raw else None

class RollbackConnection:
    """Prevent route commits escaping the outer fixture transaction."""
    def __init__(self,conn): self.conn=conn
    def execute(self,*args,**kwargs): return self.conn.execute(*args,**kwargs)
    def cursor(self,*args,**kwargs): return self.conn.cursor(*args,**kwargs)
    def commit(self): pass
    def rollback(self): pass

def main():
    uid,real,cid,other=uuid4(),uuid4(),uuid4(),uuid4()
    email="api-test-"+uid.hex+"@example.invalid"
    conn=connect()
    def fake_verify(token):
        if token=="owner": return uid,email
        if token=="stranger": return uuid4(),"unknown@example.invalid"
        raise HTTPException(401,"Synthetic auth rejected")
    def override_db():
        # Nested transaction ensures SQL exceptions cannot contaminate other requests.
        with conn.transaction():
            yield RollbackConnection(conn)
    def call(path,body,code=200,token="owner",client="127.0.0.1"):
        status,data=asyncio.run(request("POST",path,body,token,client))
        assert status==code, (path,status,code)
        return data
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        for company,name,marker in [(real,"Synthetic imported fixture",False),(cid,ht.TEST_NAME,True),(other,"Unauthorized fixture",False)]:
            data={"id":str(company),"name":name,"customers":[],"products":[],"invoices":[],"prefix":"TEST-","nextNo":1,"vpsSyntheticWriteTest":marker}
            conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,%s,%s,%s)",(company,name,uid,Jsonb(data)))
            if company!=other:
                conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(company,email))
        with tempfile.TemporaryDirectory() as d:
            grant=Path(d)/"read"
            write=Path(d)/"write"
            grant.write_text(str(uid))
            write.write_text(str(cid))
            api.dependency_overrides[db]=override_db
            with patch.object(hw,"GRANT",grant),patch.object(ht,"WRITE_GRANT",write),patch.object(ht,"verify_user",fake_verify):
                customer={"id":str(uuid4()),"name":"Dummy customer"}
                product={"id":str(uuid4()),"name":"Dummy product"}
                def rec(kind,value,expected=None,company=cid,auto=False):
                    return {"p_company_id":str(company),"p_kind":kind,"p_record":value,"p_expected":expected,"p_auto":auto}
                call("/hybrid/test-record",rec("customers",customer),401,None)
                call("/hybrid/test-record",rec("customers",customer),401,"expired")
                call("/hybrid/test-record",rec("customers",customer),403,"stranger")
                call("/hybrid/test-record",rec("customers",customer),403,"owner","192.0.2.10")
                call("/hybrid/test-record",rec("customers",customer,company=real),403)
                call("/hybrid/test-record",rec("customers",customer,company=other),403)
                assert call("/hybrid/test-record",rec("customers",customer))["version"]==2
                assert call("/hybrid/test-record",rec("products",product))["version"]==3
                invoice={"id":str(uuid4()),"number":"TEST-1","docType":"01","appStatus":"Draft","customerId":customer["id"],"items":[{"id":"line","qty":1,"price":1000,"discount":0,"taxRate":0}],"payments":[]}
                result=call("/hybrid/test-record",rec("invoices",invoice,auto=True))
                old=result["record"]
                assert result["version"]==4 and old["number"]=="TEST-1"
                edited={**old,"notes":"Edited"}
                assert call("/hybrid/test-record",rec("invoices",edited,old))["version"]==5
                call("/hybrid/test-record",rec("invoices",edited,old),409)
                payment={"id":"payment-1","date":datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat(),"amount":400,"method":"Cash","ref":""}
                p={"p_company_id":str(cid),"p_invoice_id":invoice["id"],"p_payment":payment}
                assert call("/hybrid/test-payment",p)["version"]==6
                assert call("/hybrid/test-payment",p)["existing"] is True
                call("/hybrid/test-payment",{**p,"p_payment":{**payment,"id":"payment-2","amount":601}},409)
                assert call("/hybrid/test-delete",{"p_company_id":str(cid),"p_kind":"products","p_expected":product})["version"]==7
                profile={k:"" for k in ("name","tin","brn","sst","ttx","msic","msicDesc","email","phone")}
                profile.update(name=ht.TEST_NAME,phone="000",addr={k:"" for k in ("line","city","postcode","state","country")})
                assert call("/hybrid/test-profile",{"p_company_id":str(cid),"p_version":7,"p_profile":profile})["version"]==8
                assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(real,)).fetchone()[0]==1
                assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]==8
                assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s",(cid,)).fetchone()[0]==7
                team={"p_company_id":str(cid),"p_operation":"invite","p_email":"test-staff-"+uid.hex+"@example.invalid","p_role":"Invoice Staff"}
                assert call("/hybrid/test-team",team)["version"]==9
                assert call("/hybrid/test-team",{**team,"p_operation":"remove"})["version"]==10
                call("/hybrid/test-onboard",{"p_name":"Extra"},401,None)
                call("/hybrid/test-onboard",{"p_name":"Extra"},403,"stranger")
                second=call("/hybrid/test-onboard",{"p_name":"Extra"})["id"]
                assert call("/hybrid/test-record",rec("customers",{**customer,"id":str(uuid4())},company=second))["version"]==2
                call("/hybrid/test-onboard",{"p_name":"Third"})
                call("/hybrid/test-onboard",{"p_name":"Fourth"})
                call("/hybrid/test-onboard",{"p_name":"Over limit"},409)
                assert conn.execute("SELECT count(*) FROM myr_native.companies WHERE created_by=%s AND data->>'vpsSyntheticWriteTest'='true'",(uid,)).fetchone()[0]==4
                print("VPS_SYNTHETIC_ONBOARDING_ASGI_OK")
    finally:
        api.dependency_overrides.pop(db,None)
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.companies WHERE id=ANY(%s)",([real,cid,other],)).fetchone()[0]==0
    print("VPS_ASGI_WRITE_ROLLBACK_OK")
    print("Actual request parsing, route authorization, stale edits, payments, deletion and profile tested with synthetic identity.")
    print("Real Supabase login and browser acceptance remain pending.")

if __name__=="__main__":
    main()
