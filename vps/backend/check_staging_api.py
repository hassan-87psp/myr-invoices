"""ASGI requests against staging API with one rollback-only database transaction."""
import asyncio
import json
from uuid import uuid4
from app import connect
from native_auth import hash_password
from staging_api import api, db
from account_mail import staging_mailer, compose_account_mail

async def request(method, path, payload=None, token=None, host="127.0.0.1"):
    body = json.dumps(payload).encode() if payload is not None else b""
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", ("Bearer "+token).encode()))
    scope = {"type":"http","asgi":{"version":"3.0","spec_version":"2.4"},
             "http_version":"1.1","method":method,"scheme":"http",
             "path":path,"raw_path":path.encode(),"query_string":b"",
             "root_path":"","headers":headers,"client":(host,12345),
             "server":("127.0.0.1",8000)}
    messages=[]
    delivered=False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True
            return {"type":"http.request","body":body,"more_body":False}
        await asyncio.Future()
    async def send(message):
        messages.append(message)
    await api(scope,receive,send)
    start=next(m for m in messages if m["type"]=="http.response.start")
    raw=b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
    return start["status"], json.loads(raw) if raw else None

def check(ok, label):
    if not ok:
        raise RuntimeError(label)

async def run(conn):
    uid, own, other = uuid4(),uuid4(),uuid4()
    email=f"api-smoke-{uid}@example.invalid"
    password="Staging-test-only-2026!"
    conn.execute("""INSERT INTO myr_native.users
       (id,email,password_hash,email_verified_at,disabled)
       VALUES (%s,%s,%s,now(),false)""",(uid,email,hash_password(password)))
    for cid in (own,other):
        conn.execute("INSERT INTO myr_native.companies(id,name,created_by) VALUES (%s,'Smoke test',%s)",(cid,uid))
    conn.execute("""INSERT INTO myr_native.company_members(company_id,email,role,status)
                    VALUES (%s,%s,'Read-Only','active')""",(own,email))
    check((await request("GET","/companies"))[0]==401,"Anonymous access")
    check((await request("GET","/companies",host="192.0.2.1"))[0]==403,"Nonlocal request")
    check((await request("POST","/auth/login",{"email":email,"password":"incorrect"}))[0]==401,"Bad password")
    status,result=await request("POST","/auth/login",{"email":email,"password":password})
    check(status==200,"Login failed")
    token=result["access_token"]
    status,result=await request("GET","/auth/me",token=token)
    check(status==200 and result["id"]==str(uid),"Identity mismatch")
    status,result=await request("GET","/companies",token=token)
    check(status==200 and len(result)==1 and result[0]["id"]==str(own),"Tenant isolation failed")
    check((await request("GET",f"/companies/{own}/summary",token=token))[0]==200,"Own company unavailable")
    check((await request("GET",f"/companies/{other}/summary",token=token))[0]==404,"Cross-tenant summary exposed")
    check((await request("POST","/auth/logout",token=token))[0]==204,"Logout failed")
    check((await request("GET","/auth/me",token=token))[0]==401,"Revoked session accepted")

async def lifecycle_api():
    email=f"mail-smoke-{uuid4()}@example.invalid"
    p1,p2="Synthetic-only-first-2026!","Synthetic-only-second-2026!"
    check((await request("POST","/auth/signup",{"email":email}))[0]==503,"Unconfigured mail not blocked")
    sent=[]
    def fake_sender(recipient,token,purpose):
        msg=compose_account_mail(recipient,token,purpose,"https://staging.example.invalid","noreply@example.invalid")
        check(msg["To"]==recipient and token in msg.get_content(),"Invalid mail composition")
        sent.append((recipient,token,purpose))
    api.dependency_overrides[staging_mailer]=lambda:fake_sender
    status,result=await request("POST","/auth/signup",{"email":email})
    check(status==202 and result=={"status":"accepted"} and len(sent)==1,"Signup email failed")
    t=sent[-1][1]
    check((await request("POST","/auth/verify-email",{"token":t,"password":p1,"name":"Synthetic"}))[0]==200,"Verify API failed")
    check((await request("POST","/auth/verify-email",{"token":t,"password":p1}))[0]==400,"Verification replay")
    status,result=await request("POST","/auth/login",{"email":email,"password":p1})
    check(status==200,"Verified login failed")
    session=result["access_token"]
    status,result=await request("POST","/auth/reset-request",{"email":email})
    check(status==202 and result=={"status":"accepted"} and sent[-1][2]=="reset_password","Reset email failed")
    check((await request("POST","/auth/reset-password",{"token":sent[-1][1],"password":p2}))[0]==200,"Reset API failed")
    check((await request("GET","/auth/me",token=session))[0]==401,"Old session accepted")
    check((await request("POST","/auth/login",{"email":email,"password":p2}))[0]==200,"New password rejected")
    count=len(sent)
    status,result=await request("POST","/auth/reset-request",{"email":f"missing-{uuid4()}@example.invalid"})
    check(status==202 and result=={"status":"accepted"} and len(sent)==count,"Unknown user disclosure")
    print("STAGED_ACCOUNT_MAIL_API_TESTS_OK")

with connect() as conn:
    try:
        check(conn.execute("SELECT current_database(),current_user").fetchone()
              ==("myrinvoice","myrinvoice_app"),"Wrong database")
        api.dependency_overrides[db]=lambda:conn
        asyncio.run(run(conn))
        asyncio.run(lifecycle_api())
        print("NATIVE_API_TESTS_OK")
    finally:
        api.dependency_overrides.clear()
        conn.rollback()
print("All synthetic test records rolled back.")
