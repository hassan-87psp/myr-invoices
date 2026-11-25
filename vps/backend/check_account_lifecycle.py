"""Synthetic account lifecycle tests; no mail, no persistent records."""
from uuid import uuid4
from app import connect
from native_auth import authenticate, issue_session, session_user
from account_lifecycle import begin_signup, begin_reset, finish_password, digest

def check(ok,label):
    if not ok:
        raise RuntimeError(label)

with connect() as conn:
    try:
        check(conn.execute("SELECT current_database(),current_user").fetchone()
              ==("myrinvoice","myrinvoice_app"),"Wrong database")
        email=f"lifecycle-{uuid4()}@example.invalid"
        p1,p2="Synthetic-only-first-2026!","Synthetic-only-second-2026!"
        stale=begin_signup(conn,email)
        token=begin_signup(conn,email)
        check(bool(token) and stale!=token,"Signup token issuance")
        check(not finish_password(conn,stale,p1,"verify_email"),"Old token accepted")
        check(authenticate(conn,email,p1) is None,"Unverified account login")
        check(not finish_password(conn,token,p1,"reset_password"),"Cross-purpose token accepted")
        check(finish_password(conn,token,p1,"verify_email","Synthetic user"),"Verification failed")
        check(not finish_password(conn,token,p1,"verify_email"),"Verification replay accepted")
        uid=authenticate(conn,email,p1)
        check(uid is not None,"Verified login failed")
        check(begin_signup(conn,email) is None,"Existing account signup overwritten")
        session=issue_session(conn,uid)
        expired=begin_reset(conn,email)
        conn.execute("UPDATE myr_native.auth_tokens SET expires_at=now()-interval '1 second' WHERE token_digest=%s",(digest(expired),))
        check(not finish_password(conn,expired,p2,"reset_password"),"Expired token accepted")
        reset=begin_reset(conn,email)
        check(finish_password(conn,reset,p2,"reset_password"),"Reset failed")
        check(not finish_password(conn,reset,p2,"reset_password"),"Reset replay accepted")
        check(session_user(conn,session) is None,"Old session survived reset")
        check(authenticate(conn,email,p1) is None,"Old password accepted")
        check(authenticate(conn,email,p2)==uid,"New password rejected")
        check(begin_reset(conn,f"missing-{uuid4()}@example.invalid") is None,"Unknown account reset")
        print("ACCOUNT_LIFECYCLE_TESTS_OK")
    finally:
        conn.rollback()
print("Synthetic accounts rolled back; no emails sent.")
