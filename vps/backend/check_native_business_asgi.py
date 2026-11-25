"""Native-session business identity integration: private, rollback-only."""
import asyncio
from uuid import uuid4
from unittest.mock import patch
from psycopg.types.json import Jsonb
import business_api as b
import business_native_auth as native
import check_hybrid_asgi as harness
from native_auth import hash_password,issue_session,revoke_session
from app import connect

def main():
    uid,other,cid,othercid=uuid4(),uuid4(),uuid4(),uuid4()
    email="native-bridge-"+uid.hex+"@example.invalid"
    conn=connect()
    def override():
        with conn.transaction():
            yield harness.RollbackConnection(conn)
    def call(method,path,body=None,token=None,session=None,origin="https://myrinvoice.com",expected=200):
        headers=[]
        if session is not None: headers.append((b"cookie",(native.COOKIE+"="+session).encode()))
        if origin is not None: headers.append((b"origin",origin.encode()))
        with patch.object(harness,"api",b.api):
            code,data=asyncio.run(harness.request(method,path,body,token,extra_headers=headers))
        assert code==expected,(path,code,expected,data)
        return data
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled,password_hash) VALUES(%s,%s,now(),false,%s)",(uid,email,hash_password("Synthetic-only-native-2026!")))
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(other,"other-"+other.hex+"@example.invalid"))
        for company,actor in ((cid,uid),(othercid,other)):
            conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Native rollback fixture',%s,%s)",(company,actor,Jsonb({"customers":[],"products":[],"invoices":[],"nextNo":1001,"prefix":"INV-"})))
        conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
        session=issue_session(conn,uid)
        b.api.dependency_overrides[b.db]=override
        # Private workspace read executes SET TRANSACTION READ ONLY: exercise identity
        # and mutations via actual ASGI; read authorization itself is checked below.
        body={"p_company_id":str(cid),"p_kind":"customers","p_record":{"id":"test","name":"Native fixture"}}
        call("POST","/records",body,session=session,expected=401)
        with patch.object(b,"native_enabled",lambda:True),patch.object(b,"require_cutover",lambda:None):
            call("POST","/records",body,session=session,origin=None,expected=403)
            call("POST","/records",body,session=session,origin="https://example.invalid",expected=403)
            call("POST","/records",body,session=session,token="legacy",expected=401)
            call("POST","/records",{**body,"p_company_id":str(othercid)},session=session,expected=404)
            result=call("POST","/records",body,session=session)
            assert result["version"]==2
            assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(othercid,)).fetchone()[0]==1
            p={"id":uid,"email":email,"name":None,"is_platform_admin":False}
            assert [x["id"] for x in b.workspace(conn,p)["companies"]]==[cid]
            revoke_session(conn,session)
            call("POST","/records",body,session=session,expected=401)
        print("MYR_NATIVE_SESSION_BUSINESS_ROLLBACK_OK")
    finally:
        b.api.dependency_overrides.pop(b.db,None)
        conn.rollback()
        conn.close()
    with connect() as c:
        assert c.execute("SELECT count(*) FROM myr_native.users WHERE id=ANY(%s)",([uid,other],)).fetchone()[0]==0

if __name__=="__main__": main()
