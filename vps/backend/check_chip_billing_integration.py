"""Exercise billing router with real owner/admin guards and synthetic provider responses.
Disposable PostgreSQL only; no network, no public route, no live entitlement.
"""
import asyncio,json
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from check_lhdn_disposable_db import connect
from chip_billing_integration_candidate import build_router
import business_api as b

def exercise(admin,owner,other,company,second):
    api=FastAPI()
    def db():
        with connect() as c:yield c
    def verified(request,conn):
        uid={"admin":admin,"owner":owner,"other":other}.get(request.headers.get("authorization",""))
        if uid is None:raise HTTPException(401,"Test identity required")
        return uid,uid.hex+"@example.invalid"
    enabled=False;calls=[];pid=str(uuid4())
    def gate():
        if not enabled:raise HTTPException(503,"Not released")
    def bridge(req):
        calls.append(req)
        base={"ok":True,"is_test":True,"amount_sen":1900,"intent_id":req["intent_id"],
              "purchase_id":pid,"entitlement_changed":False}
        if req["action"]=="create_reserved_test":return {**base,"status":"created","checkout_url":"https://gate.chip-in.asia/p/"+pid+"/"}
        return {**base,"status":"paid","verified_test_paid":True}
    api.include_router(build_router(db,b.identity,b.owner_company,b.admin_identity,gate,bridge))
    async def call(method,path,body,token,origin):
        payload=json.dumps(body).encode() if body is not None else b""
        headers=[(b"content-type",b"application/json"),(b"origin",origin.encode()),(b"authorization",token.encode())]
        scope={"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},"http_version":"1.1","method":method,
          "scheme":"http","path":path,"raw_path":path.encode(),"query_string":b"","root_path":"",
          "headers":headers,"client":("127.0.0.1",12345),"server":("localhost",8765)}
        received=False;messages=[]
        async def receive():
            nonlocal received
            if not received:
                received=True
                return {"type":"http.request","body":payload,"more_body":False}
            await asyncio.Event().wait()
        async def send(message):messages.append(message)
        await asyncio.wait_for(api(scope,receive,send),timeout=15)
        code=next(m["status"] for m in messages if m["type"]=="http.response.start")
        return code,json.loads(b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body"))
    def req(method,path,body=None,token="admin",expected=200,origin="https://myrinvoice.com"):
        status,data=asyncio.run(call(method,path,body,token,origin))
        assert status==expected,(method,path,status,expected)
        return data
    h="/billing/customer/"+str(company);a="/billing/admin/sandbox";c=a+"/checkout";v=a+"/verify"
    body={"company_id":str(company),"plan":"Pro"}
    with patch.object(b,"verified_identity",verified):
        req("GET",h,token="",expected=401)
        req("GET",h,token="other",expected=404)
        req("GET",h,token="admin",expected=403)
        assert req("GET",h,token="owner")["checkout_enabled"] is False
        req("GET",a,token="owner",expected=403)
        req("POST",c,body,expected=503)
        enabled=True
        req("POST",c,body,token="owner",expected=403)
        req("POST",c,body,origin="https://evil.invalid",expected=403)
        req("POST",c,{**body,"amount_sen":1},expected=422)
        req("POST",c,{**body,"plan":"invalid"},expected=422)
        assert not calls
        result=req("POST",c,body)
        assert result["status"]=="created" and result["mode"]=="test"
        req("POST",c,body,expected=409)
        verify={"intent_id":result["intent_id"]}
        req("POST",v,verify,token="owner",expected=403)
        assert req("POST",v,verify)["status"]=="verified_test_paid"
        assert req("POST",v,verify)["entitlement_changed"] is False
        assert sum(x["action"]=="create_reserved_test" for x in calls)==1
        status=req("GET",a)
        assert status["test_paid_count"]==1 and status["live_revenue_sen"] is None
        assert req("GET",h,token="owner")["history"]==[]
        with connect() as conn:
            assert conn.execute("SELECT plan FROM myr_native.companies WHERE id=%s",(company,)).fetchone()==("Starter",)
            assert conn.execute("SELECT count(*) FROM myr_native.chip_test_receipts").fetchone()==(1,)
    print("MYR_CHIP_BILLING_INTEGRATION_API_OK")
