"""Create the explicitly designated platform administrator for private staging.
No company membership is added, and imported accounts remain untouched.
"""
import getpass
from app import connect
from native_auth import hash_password

EMAIL="invoicesmyr@gmail.com"

def main():
    print("Private staging Super Admin:",EMAIL)
    with connect() as conn:
        if conn.execute("SELECT current_database(),current_user").fetchone()!=("myrinvoice","myrinvoice_app"):
            raise SystemExit("Wrong database")
        if not conn.execute("SELECT to_regclass('myr_native.migration_source_archive')").fetchone()[0]:
            raise SystemExit("Staged migration not found")
        row=conn.execute("SELECT is_platform_admin,disabled,password_hash IS NOT NULL FROM myr_native.users WHERE email=%s",(EMAIL,)).fetchone()
        if row:
            if row==(True,False,True):
                print("STAGING_SUPER_ADMIN_ALREADY_ACTIVE")
                return
            raise SystemExit("Account already exists in another state; no overwrite.")
        if input("Confirm you control this email and authorize local staging admin creation. Type YES: ")!="YES":
            raise SystemExit("Cancelled")
        password=getpass.getpass("New Super Admin staging password (12+ characters): ")
        if not 12<=len(password)<=128:
            raise SystemExit("Password must contain 12 to 128 characters")
        if password!=getpass.getpass("Repeat Super Admin staging password: "):
            raise SystemExit("Passwords do not match")
        # Operator-attested identity for this isolated staging environment only.
        uid=conn.execute("""INSERT INTO myr_native.users
            (email,name,password_hash,email_verified_at,is_platform_admin,disabled)
            VALUES (%s,'MYR Invoice Admin',%s,now(),true,false) RETURNING id""",
            (EMAIL,hash_password(password))).fetchone()[0]
        conn.execute("""INSERT INTO myr_native.audit_logs(actor,actor_email,action,detail)
            VALUES (%s,%s,'staging.admin.create','Operator-attested staging identity; email delivery verification pending')""",(uid,EMAIL))
    print("STAGING_SUPER_ADMIN_CREATED")
if __name__=="__main__":
    main()
