"""Run only on dedicated staging DB; all test writes roll back."""
from uuid import uuid4
from app import connect
from native_auth import (hash_password, authenticate, issue_session,
                         session_user, revoke_session, tenant_role)

def check(condition, label):
    if not condition:
        raise RuntimeError(label)

with connect() as conn:
    try:
        check(conn.execute("SELECT current_database(),current_user").fetchone()
              == ("myrinvoice", "myrinvoice_app"), "Wrong database")
        uid, cid = uuid4(), uuid4()
        email = f"smoke-{uid}@example.invalid"
        password = "Staging-test-only-2026!"
        ph = hash_password(password)
        conn.execute(
            """INSERT INTO myr_native.users
               (id,email,password_hash,email_verified_at,disabled)
               VALUES (%s,%s,%s,now(),false)""", (uid,email,ph))
        check(authenticate(conn,email,password)==uid,"Valid login failed")
        check(authenticate(conn,email,"wrong-password") is None,"Wrong password accepted")
        check(authenticate(conn,"missing@example.invalid",password) is None,"Unknown account accepted")
        token = issue_session(conn,uid)
        check(session_user(conn,token)[0]==uid,"Session lookup failed")
        conn.execute(
            """INSERT INTO myr_native.companies(id,name,created_by)
               VALUES (%s,'Rollback smoke test',%s)""",(cid,uid))
        check(tenant_role(conn,uid,cid) is None,"Unassigned company access")
        conn.execute(
            """INSERT INTO myr_native.company_members(company_id,email,role,status)
               VALUES (%s,%s,'Read-Only','active')""",(cid,email))
        check(tenant_role(conn,uid,cid)=="Read-Only","Membership lookup failed")
        check(tenant_role(conn,uid,cid,["Owner","Admin"]) is None,"Role escalation")
        check(tenant_role(conn,uid,uuid4()) is None,"Cross-tenant access")
        conn.execute("UPDATE myr_native.companies SET status='suspended' WHERE id=%s",(cid,))
        check(tenant_role(conn,uid,cid) is None,"Suspended company access")
        revoke_session(conn,token)
        check(session_user(conn,token) is None,"Revoked session accepted")
        token = issue_session(conn,uid)
        conn.execute("UPDATE myr_native.users SET disabled=true WHERE id=%s",(uid,))
        check(session_user(conn,token) is None,"Disabled user session accepted")
        check(authenticate(conn,email,password) is None,"Disabled user login")
        conn.execute("UPDATE myr_native.users SET disabled=false,email_verified_at=NULL WHERE id=%s",(uid,))
        check(authenticate(conn,email,password) is None,"Unverified email login")
        print("NATIVE_AUTH_TENANT_TESTS_OK")
    finally:
        conn.rollback()
print("All test records rolled back. No customer data changed.")
