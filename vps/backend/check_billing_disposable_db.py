"""Billing ledger integration tests against disposable PostgreSQL only."""
from pathlib import Path
from datetime import date
from uuid import uuid4
import psycopg
from check_lhdn_disposable_db import connect
from billing_ledger_candidate import create_period,record_receipt,owner_history

def reject(c,operation,exc=ValueError):
    try:
        with c.transaction():
            operation()
    except exc:
        return
    raise AssertionError("Expected rejection")

def main():
    with connect() as c:
        c.execute("""CREATE SCHEMA myr_native;
          CREATE TABLE myr_native.users(id uuid PRIMARY KEY,email text UNIQUE NOT NULL,
            name text, disabled boolean NOT NULL DEFAULT false,email_verified_at timestamptz,is_platform_admin boolean DEFAULT false);
          CREATE TABLE myr_native.companies(id uuid PRIMARY KEY,plan text NOT NULL,status text NOT NULL,data jsonb NOT NULL DEFAULT '{}'::jsonb);
          CREATE TABLE myr_native.company_members(company_id uuid REFERENCES myr_native.companies(id),
            email text REFERENCES myr_native.users(email),role text,status text,PRIMARY KEY(company_id,email));""")
        c.execute((Path(__file__).resolve().parent.parent/"billing-ledger.review.sql").read_text())
        admin,owner,other,company,second=uuid4(),uuid4(),uuid4(),uuid4(),uuid4()
        for uid,flag in ((admin,True),(owner,False),(other,False)):
            c.execute("INSERT INTO myr_native.users(id,email,email_verified_at,is_platform_admin) VALUES(%s,%s,now(),%s)",(uid,uid.hex+"@example.invalid",flag))
        for cid,uid,plan in ((company,owner,"Starter"),(second,other,"Pro")):
            c.execute("INSERT INTO myr_native.companies(id,plan,status) VALUES(%s,%s,'active')",(cid,plan))
            c.execute("INSERT INTO myr_native.company_members VALUES(%s,%s,'Owner','active')",(cid,uid.hex+"@example.invalid"))
        c.commit()
        month=date(2026,11,1)
        reject(c,lambda:create_period(c,owner,company,month))
        reject(c,lambda:create_period(c,admin,company,date(2026,11,2)))
        pid=create_period(c,admin,company,month)
        pid2=create_period(c,admin,second,month)
        assert owner_history(c,owner,company)[0][:5]==(month,"Starter",900,"MYR","unpaid")
        reject(c,lambda:owner_history(c,other,company))
        reject(c,lambda:create_period(c,admin,company,month),psycopg.errors.UniqueViolation)
        reject(c,lambda:record_receipt(c,owner,company,pid,900,"bank_transfer","TEST-1"))
        reject(c,lambda:record_receipt(c,admin,second,pid,900,"bank_transfer","TEST-1"))
        reject(c,lambda:record_receipt(c,admin,company,pid,899,"bank_transfer","TEST-1"))
        record_receipt(c,admin,company,pid,900,"bank_transfer","TEST-1")
        reject(c,lambda:record_receipt(c,admin,company,pid,900,"bank_transfer","TEST-2"),psycopg.errors.UniqueViolation)
        reject(c,lambda:record_receipt(c,admin,second,pid2,1900,"bank_transfer","test-1"),psycopg.errors.UniqueViolation)
        assert owner_history(c,owner,company)[0][4]=="recorded_paid"
        assert owner_history(c,other,second)[0][4]=="unpaid"
        assert c.execute("SELECT plan FROM myr_native.companies WHERE id=%s",(company,)).fetchone()==("Starter",)
        c.execute("UPDATE myr_native.users SET disabled=true WHERE id=%s",(admin,))
        reject(c,lambda:record_receipt(c,admin,second,pid2,1900,"duitnow","TEST-3"))
        c.rollback()
    from check_billing_api_candidate import exercise
    exercise(admin,owner,other,company,second)
    print("MYR_BILLING_LEDGER_DISPOSABLE_TEST_OK")
if __name__=="__main__":
    main()
