"""Apply and exercise billing schema only in the private restored backup cluster.
Never uses production connection helpers. All fixture and migration work rolls back.
"""
import os,sys,stat
from pathlib import Path
from datetime import date
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
from billing_ledger_candidate import create_period,record_receipt,owner_history

def main():
    root=Path(sys.argv[1]).resolve()
    if (not root.name.startswith(".myr-restore-rehearsal-") or root.parent!=Path.home()
        or root.stat().st_uid!=os.getuid() or stat.S_IMODE(root.stat().st_mode)!=0o700):
        raise RuntimeError("Private restored database required")
    with psycopg.connect(host=str(root/"socket"),port=55440,dbname="myr_restore_rehearsal",
          user="myr_restore_test",sslmode="disable",connect_timeout=5) as conn:
        assert conn.execute("SELECT current_database(),current_user,inet_server_addr()").fetchone()==("myr_restore_rehearsal","myr_restore_test",None)
        try:
            conn.execute((Path(__file__).resolve().parent.parent/"billing-ledger.review.sql").read_text())
            conn.execute("""CREATE ROLE myr_billing_rehearsal NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                GRANT USAGE ON SCHEMA myr_native TO myr_billing_rehearsal;
                GRANT SELECT ON myr_native.users,myr_native.companies,myr_native.company_members TO myr_billing_rehearsal;
                GRANT UPDATE(id) ON myr_native.users,myr_native.companies TO myr_billing_rehearsal;
                GRANT SELECT,INSERT ON myr_native.billing_periods,myr_native.billing_receipts TO myr_billing_rehearsal;""")
            admin,owner,cid=uuid4(),uuid4(),uuid4()
            for uid,flag in ((admin,True),(owner,False)):
                conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,is_platform_admin,disabled) VALUES(%s,%s,now(),%s,false)",(uid,uid.hex+"@example.invalid",flag))
            conn.execute("INSERT INTO myr_native.companies(id,name,created_by,plan,status,data) VALUES(%s,'Billing rehearsal',%s,'Starter','active',%s)",(cid,owner,Jsonb({"plan":"Starter","invoices":[],"customers":[],"products":[]})))
            conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,owner.hex+"@example.invalid"))
            conn.execute("SET LOCAL ROLE myr_billing_rehearsal")
            assert conn.execute("SELECT current_user").fetchone()==("myr_billing_rehearsal",)
            pid=create_period(conn,admin,cid,date(2026,11,1))
            record_receipt(conn,admin,cid,pid,900,"duitnow","RESTORE-"+uuid4().hex)
            assert owner_history(conn,owner,cid)[0][4]=="recorded_paid"
            for table in ("billing_periods","billing_receipts"):
                for privilege in ("UPDATE","DELETE","TRUNCATE"):
                    assert not conn.execute("SELECT has_table_privilege(current_user,%s,%s)",("myr_native."+table,privilege)).fetchone()[0]
            try:
                with conn.transaction():
                    conn.execute("DELETE FROM myr_native.billing_receipts WHERE period_id=%s",(pid,))
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise AssertionError("Receipt delete unexpectedly allowed")
        finally:
            conn.rollback()
    print("MYR_BILLING_RESTORED_SCHEMA_AND_RESTRICTED_ROLE_OK")

if __name__=="__main__":main()
