"""Exercise candidate routes on the same disposable cluster.
Synthetic authentication only; no public mount, no production credentials.
"""
import asyncio,json
from fastapi import FastAPI,HTTPException
from unittest.mock import patch
from check_lhdn_disposable_db import connect
from billing_api_candidate import build_router
import business_api as b

def exercise(admin,owner,other,company,second):
    api=FastAPI()
    def db():
        with connect() as c:yield c
    def verified(request,conn):
        tokens={"admin":admin,"owner":owner,"other":other}
        uid=tokens.get(request.headers.get("authorization",""))
        if uid is None:raise HTTPException(401,"Test identity required")
        return uid,uid.hex+"@example.invalid"
    enabled=False
    def gate():
        if not enabled:raise HTTPException(503,"Not released")
    api.include_router(build_router(db,b.identity,b.owner_company,b.admin_identity,gate))
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
        data=json.loads(b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body"))
        return code,data
    def req(method,path,body=None,token="admin",expected=200,origin="https://myrinvoice.com"):
        status,data=asyncio.run(call(method,path,body,token,origin))
        assert status==expected,(method,path,status,expected)
        return data
    p="/billing/admin/period";r="/billing/admin/receipt";h="/billing/history/"+str(company)
    body={"company_id":str(company),"period_start":"2026-11-01"}
    with patch.object(b,"verified_identity",verified):
        req("GET",h,token="",expected=401)
        req("GET",h,token="other",expected=404)
        req("POST",p,body,token="owner",expected=403)
        req("POST",p,body,expected=503)
        enabled=True
        req("POST",p,body,origin="https://example.invalid",expected=403)
        pid=req("POST",p,body)["period_id"]
        req("POST",p,body,expected=409)
        receipt={"company_id":str(company),"period_id":pid,"amount_sen":900,"method":"duitnow","reference":"API-TEST-1"}
        req("POST",r,{**receipt,"company_id":str(second)},expected=409)
        req("POST",r,{**receipt,"amount_sen":899},expected=409)
        req("POST",r,{**receipt,"amount_sen":"900"},expected=422)
        assert req("POST",r,receipt)["entitlement_changed"] is False
        req("POST",r,receipt,expected=409)
        assert req("GET",h,token="owner")["history"][0]["status"]=="recorded_paid"
        req("GET",h,token="admin",expected=403)
    print("MYR_BILLING_API_DISPOSABLE_TEST_OK")
