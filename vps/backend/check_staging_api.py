"""ASGI requests against staging API with one rollback-only database transaction."""
import asyncio
import json
from uuid import uuid4
from app import connect
from native_auth import hash_password
from staging_api import api, db

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
    check((await request("POST","/auth/logout",token=token))[0]==204,"Logout failed")
    check((await request("GET","/auth/me",token=token))[0]==401,"Revoked session accepted")

with connect() as conn:
    try:
        check(conn.execute("SELECT current_database(),current_user").fetchone()
              ==("myrinvoice","myrinvoice_app"),"Wrong database")
        api.dependency_overrides[db]=lambda:conn
        asyncio.run(run(conn))
        print("NATIVE_API_TESTS_OK")
    finally:
        api.dependency_overrides.clear()
        conn.rollback()
print("All synthetic test records rolled back.")
