"""Private readiness route factory. Not mounted on the production application.
Integrate only with the existing verified identity dependency, never a browser actor.
No writes or external requests; no provider readiness is implied.
"""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from lhdn_readiness_candidate import readiness

class ReadinessBody(BaseModel):
    model_config=ConfigDict(extra="forbid")
    p_company_id:UUID
    p_invoice_id:str=Field(min_length=1,max_length=128)
    p_version:StrictInt=Field(gt=0)
    p_total_sen:StrictInt=Field(gt=0,le=100000000000)

def router_factory(db_dependency,identity_function,release_check):
    router=APIRouter()
    @router.post("/lhdn/readiness")
    def check(body:ReadinessBody,request:Request,conn=Depends(db_dependency)):
        if request.headers.get("origin")!="https://myrinvoice.com":
            raise HTTPException(403,"Origin rejected")
        release_check()
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        profile=identity_function(conn,request)
        if profile.get("is_platform_admin") or profile.get("onboarding_only"):
            raise HTTPException(403,"Business owner required")
        result=readiness(conn,UUID(str(profile["id"])),body.p_company_id,body.p_invoice_id,
                         body.p_version,body.p_total_sen,datetime.now(timezone.utc))
        if result["status"]=="unavailable":
            raise HTTPException(404,"Invoice unavailable")
        return result
    return router

if __name__=="__main__":
    import unittest
    from unittest.mock import patch
    from fastapi import FastAPI
    import asyncio
    import json
    from types import SimpleNamespace
    async def asgi_post(app,body,headers):
        payload=json.dumps(body).encode("utf-8")
        scope={"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},
               "http_version":"1.1","method":"POST","scheme":"https",
               "path":"/lhdn/readiness","raw_path":b"/lhdn/readiness","root_path":"",
               "query_string":b"","client":("127.0.0.1",12345),"server":("myrinvoice.com",443),
               "headers":[(b"content-type",b"application/json"),(b"content-length",str(len(payload)).encode())]+
                         [(k.lower().encode(),v.encode()) for k,v in headers.items()]}
        sent=False;messages=[]
        async def receive():
            nonlocal sent
            if not sent:
                sent=True
                return {"type":"http.request","body":payload,"more_body":False}
            return {"type":"http.disconnect"}
        async def send(message):
            messages.append(message)
        await app(scope,receive,send)
        status=next(m["status"] for m in messages if m["type"]=="http.response.start")
        data=b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
        return SimpleNamespace(status_code=status,json=lambda:json.loads(data))
    class Conn:
        def execute(self,sql):
            if sql!="SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY":
                raise AssertionError("Unexpected database command")
    class Tests(unittest.TestCase):
        def setUp(self):
            self.actor=UUID(int=1); self.company=UUID(int=2); self.enabled=True;self.admin=False
            def db():return Conn()
            def identity(conn,req):
                if req.headers.get("authorization")!="Bearer synthetic":raise HTTPException(401)
                return {"id":self.actor,"is_platform_admin":self.admin}
            def gate():
                if not self.enabled:raise HTTPException(503)
            app=FastAPI()
            app.include_router(router_factory(db,identity,gate))
            self.app=app
            self.headers={"Origin":"https://myrinvoice.com","Authorization":"Bearer synthetic"}
            self.body={"p_company_id":str(self.company),"p_invoice_id":"INV1","p_version":1,"p_total_sen":1000}
        def post(self,body=None,headers=None):
            return asyncio.run(asgi_post(self.app,self.body if body is None else body,self.headers if headers is None else headers))
        def test_success_is_not_submission(self):
            with patch(__name__+".readiness",return_value={"status":"offline_preview_ready","submission_enabled":False}) as check:
                r=self.post()
            self.assertEqual(r.status_code,200)
            self.assertFalse(r.json()["submission_enabled"])
            self.assertEqual(check.call_args.args[1:6],(self.actor,self.company,"INV1",1,1000))
        def test_origin(self):
            self.assertEqual(self.post(headers={"Origin":"https://example.invalid"}).status_code,403)
        def test_auth(self):
            self.assertEqual(self.post(headers={"Origin":"https://myrinvoice.com"}).status_code,401)
        def test_gate(self):
            self.enabled=False
            self.assertEqual(self.post().status_code,503)
        def test_admin(self):
            self.admin=True
            self.assertEqual(self.post().status_code,403)
        def test_actor_injection(self):
            self.assertEqual(self.post({**self.body,"actor_id":str(self.actor)}).status_code,422)
        def test_foreign_company(self):
            with patch(__name__+".readiness",return_value={"status":"unavailable","submission_enabled":False}):
                self.assertEqual(self.post().status_code,404)
    unittest.main()
