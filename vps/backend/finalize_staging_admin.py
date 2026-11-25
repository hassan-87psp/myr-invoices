"""Establish the designated sole platform admin in the isolated VPS staging DB.
Do not change source Supabase, tenant ownership, or public DNS.
"""
import getpass
from app import connect
from native_auth import hash_password, authenticate, issue_session, session_user, revoke_session
EMAIL="invoicesmyr@gmail.com"
OLD="hassanrazza33445@gmail.com"

def main():
    print("Designated Super Admin:",EMAIL)
    print("Imported company ownership remains unchanged.")
    print("The disabled imported owner's platform-admin flag will be removed.")
    if input("Confirm you control the new admin email. Type YES: ")!="YES":
        raise SystemExit("Cancelled")
    with connect() as conn:
        if conn.execute("SELECT current_database(),current_user").fetchone()!=("myrinvoice","myrinvoice_app"):
            raise SystemExit("Wrong database")
        if not conn.execute("SELECT to_regclass('myr_native.migration_source_archive')").fetchone()[0]:
            raise SystemExit("Staging migration not found")
        conn.execute("LOCK TABLE myr_native.users IN SHARE ROW EXCLUSIVE MODE")
        row=conn.execute("SELECT id,is_platform_admin,disabled,password_hash IS NOT NULL FROM myr_native.users WHERE email=%s",(EMAIL,)).fetchone()
        old=conn.execute("SELECT id,disabled FROM myr_native.users WHERE email=%s",(OLD,)).fetchone()
        if not old:
            raise SystemExit("Expected imported owner missing; no change")
        if conn.execute("SELECT count(*) FROM myr_native.users WHERE is_platform_admin AND email NOT IN (%s,%s)",(EMAIL,OLD)).fetchone()[0]:
            raise SystemExit("Unexpected additional platform admin; no change")
        if not old[1]:
            raise SystemExit("Imported owner is active; separate role review required")
        if row and row[1:]!=(True,False,True):
            raise SystemExit("Existing new admin account has unexpected state; no change")
        if row:
            password=getpass.getpass("Existing new Super Admin staging password: ")
            uid=row[0]
        else:
            password=getpass.getpass("New Super Admin staging password (12+ characters): ")
            if not 12<=len(password)<=128:
                raise SystemExit("Password must contain 12 to 128 characters")
            if password!=getpass.getpass("Repeat new Super Admin staging password: "):
                raise SystemExit("Passwords do not match")
            uid=conn.execute("""INSERT INTO myr_native.users
                (email,name,password_hash,email_verified_at,is_platform_admin,disabled)
                VALUES (%s,'MYR Invoice Super Admin',%s,now(),true,false) RETURNING id""",
                (EMAIL,hash_password(password))).fetchone()[0]
            conn.execute("""INSERT INTO myr_native.audit_logs(actor,actor_email,action,detail)
                VALUES (%s,%s,'staging.admin.create','Local operator attestation; production mailbox verification pending')""",(uid,EMAIL))
        if authenticate(conn,EMAIL,password)!=uid:
            raise SystemExit("Admin login check failed; no role change committed")
        token=issue_session(conn,uid)
        identity=session_user(conn,token)
        if not identity or identity[0]!=uid or not identity[3]:
            raise SystemExit("Admin authorization check failed")
        # Remove only the known disabled imported account's platform privilege.
        changed=conn.execute("UPDATE myr_native.users SET is_platform_admin=false WHERE id=%s AND disabled AND is_platform_admin RETURNING id",(old[0],)).fetchone()
        if changed:
            conn.execute("UPDATE myr_native.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(old[0],))
            conn.execute("""INSERT INTO myr_native.audit_logs(actor,actor_email,action,detail)
                VALUES (%s,%s,'staging.admin.role_transfer','Imported disabled account retains company ownership')""",(uid,EMAIL))
        if conn.execute("SELECT email FROM myr_native.users WHERE is_platform_admin").fetchall()!=[(EMAIL,)]:
            raise SystemExit("Sole platform admin assertion failed")
        if not conn.execute("""SELECT EXISTS(SELECT 1 FROM myr_native.company_members
            WHERE email=%s AND role='Owner' AND status='active')""",(OLD,)).fetchone()[0]:
            raise SystemExit("Imported owner membership assertion failed")
        revoke_session(conn,token)
    print("STAGING_SUPER_ADMIN_VERIFIED")
    print("IMPORTED_COMPANY_OWNERSHIP_PRESERVED")
if __name__=="__main__":
    main()
