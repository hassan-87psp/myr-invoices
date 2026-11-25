"""Real native account routes, mock mail provider and rollback-only database."""
import asyncio
from uuid import uuid4
from unittest.mock import patch
from fastapi import HTTPException
from app import connect
import business_api as b
import business_native_auth as n
import check_hybrid_asgi as h
from native_auth import authenticate,issue_session,session_user

def main():
    email="mail-test-"+uuid4().hex+"@example.invalid"
    password="Synthetic-mail-only-2026!"
    conn=connect()
    sent=[]
    def fake_send(recipient,token,event):
        assert recipient==email
        sent.append((event,token))
    def override():
        with conn.transaction():
            yield h.RollbackConnection(conn)
    def call(route,body,expected=200,origin="https://myrinvoice.com",token=None):
        with patch.object(h,"api",b.api):
            code,data=asyncio.run(h.request("POST",route,body,token,extra_headers=[(b"origin",origin.encode())]))
        assert code==expected,(route,code,expected,data)
        return data
    try:
        conn.execute("SELECT 1")
        b.api.dependency_overrides[n.db]=override
        b.api.dependency_overrides[b.db]=override
        b.api.dependency_overrides[n.sender]=lambda:fake_send
        call("/native/auth/signup",{"email":email},403,origin="https://example.invalid")
        assert not sent
        call("/native/auth/signup",{"email":email},202)
        assert sent[0][0]=="verify_email" and len(sent[0][1])==43
        verify=sent[0][1]
        assert authenticate(conn,email,password) is None
        result=call("/native/auth/verify-email",{"token":verify,"password":password,"name":"Mail test"})
        assert result["welcome_email"]=="accepted" and sent[1]==("welcome",None)
        uid=authenticate(conn,email,password)
        assert uid is not None
        call("/native/auth/verify-email",{"token":verify,"password":password},400)
        assert len(sent)==2
        call("/native/auth/login",{"email":email,"password":password})
        session=issue_session(conn,uid)
        call("/native/auth/reset-request",{"email":email},202)
        reset=sent[2][1]
        assert sent[2][0]=="reset_password"
        call("/native/auth/reset-password",{"token":reset,"password":password+"2"})
        assert session_user(conn,session) is None
        assert authenticate(conn,email,password+"2")==uid
        with patch.object(b,"verify_user",lambda _: (uid,email)):
            call("/onboard",{"p_profile":{}},401,token="legacy")
        print("MYR_NATIVE_ACCOUNT_MAIL_ROLLBACK_OK")
    finally:
        for dep in (n.db,n.sender,b.db): b.api.dependency_overrides.pop(dep,None)
        conn.rollback()
        conn.close()
    with connect() as c:
        assert c.execute("SELECT count(*) FROM myr_native.users WHERE email=%s",(email,)).fetchone()[0]==0

if __name__=="__main__": main()
