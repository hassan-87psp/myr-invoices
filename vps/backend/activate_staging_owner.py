"""Operator-controlled activation of an existing verified staging owner.
Run only on the private VPS. Never changes the source account or its password.
"""
import getpass
from app import connect
from native_auth import hash_password
from account_lifecycle import normalize_email

def main():
    email=normalize_email(input("Existing MYR Invoice owner email: "))
    with connect() as conn:
        if conn.execute("SELECT current_database(),current_user").fetchone()!=("myrinvoice","myrinvoice_app"):
            raise SystemExit("Wrong database")
        if not conn.execute("SELECT to_regclass('myr_native.migration_source_archive')").fetchone()[0]:
            raise SystemExit("Staged migration not found")
        row=conn.execute("""SELECT u.id,u.disabled,u.password_hash,u.email_verified_at
            FROM myr_native.users u WHERE u.email=%s AND EXISTS (
              SELECT 1 FROM myr_native.company_members m
              JOIN myr_native.companies c ON c.id=m.company_id
              WHERE m.email=u.email AND m.role='Owner' AND m.status='active'
                AND c.status='active') FOR UPDATE""",(email,)).fetchone()
        if not row or not row[3]:
            raise SystemExit("No verified imported owner matched. No change.")
        if not row[1] and row[2]:
            print("STAGING_OWNER_ALREADY_ACTIVE")
            return
        if not row[1] or row[2]:
            raise SystemExit("Unexpected account state; no change.")
        if input("Activate this existing account for private staging only? Type YES: ")!="YES":
            raise SystemExit("Cancelled")
        password=getpass.getpass("New separate staging login password (12+ characters): ")
        if password!=getpass.getpass("Repeat staging login password: "):
            raise SystemExit("Passwords do not match")
        if not 12<=len(password)<=128:
            raise SystemExit("Password must contain 12 to 128 characters")
        uid=row[0]
        conn.execute("UPDATE myr_native.users SET password_hash=%s,disabled=false WHERE id=%s",
                     (hash_password(password),uid))
        conn.execute("UPDATE myr_native.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(uid,))
        conn.execute("INSERT INTO myr_native.audit_logs(actor,action,detail) VALUES (%s,'staging.owner.activate','Local operator activation for isolated preview')",(uid,))
    print("STAGING_OWNER_ACTIVATED")
if __name__=="__main__":
    main()
