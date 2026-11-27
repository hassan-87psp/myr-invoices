"""Disposable PostgreSQL integration rehearsal. No production DB access.
Only accepts a private Unix socket directory created by the test launcher.
Minimal synthetic schema matches the fields used by lifecycle helpers;
this is not a rehearsal against a clone of the full production schema.
"""
import os
import stat
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import psycopg
from psycopg.types.json import Jsonb
from lhdn_saved_invoice_candidate import MapperTests
from lhdn_lifecycle_candidate import prepare,reserve,row,accept,sync,outcome_unknown,cancel_plan
from lhdn_readiness_candidate import readiness

def connect():
    root=Path(sys.argv[1]).resolve()
    if not root.name.startswith("myr-lhdn-rehearsal-") or root.stat().st_uid!=os.getuid() or stat.S_IMODE(root.stat().st_mode)!=0o700:
        raise RuntimeError("Private temporary directory required")
    socket=root/"socket"
    if not socket.is_dir() or socket.stat().st_uid!=os.getuid():
        raise RuntimeError("Private test socket required")
    conn=psycopg.connect(host=str(socket),port=55439,dbname="myr_lhdn_rehearsal",user="myr_lhdn_test",connect_timeout=5,sslmode="disable")
    if conn.execute("SELECT current_database(),current_user,inet_server_addr()").fetchone()!=("myr_lhdn_rehearsal","myr_lhdn_test",None):
        conn.close()
        raise RuntimeError("Wrong database identity")
    conn.commit()
    return conn

def reject(conn,operation,exc=ValueError):
    try:
        with conn.transaction():
            operation()
    except exc:
        return
    raise AssertionError("Operation should have been rejected")

def main():
    with connect() as c:
        c.execute("""CREATE SCHEMA myr_native;
        CREATE TABLE myr_native.users(id uuid PRIMARY KEY,email text UNIQUE NOT NULL,
          disabled boolean NOT NULL DEFAULT false,email_verified_at timestamptz,is_platform_admin boolean DEFAULT false);
        CREATE TABLE myr_native.companies(id uuid PRIMARY KEY,version bigint NOT NULL DEFAULT 1,tin text NOT NULL,
          status text NOT NULL DEFAULT 'active',data jsonb NOT NULL);
        CREATE TABLE myr_native.company_members(company_id uuid REFERENCES myr_native.companies(id),
          email text REFERENCES myr_native.users(email),role text NOT NULL,status text NOT NULL,PRIMARY KEY(company_id,email));
        CREATE TABLE myr_native.lhdn_documents(company_id uuid REFERENCES myr_native.companies(id),invoice_id text NOT NULL,
          PRIMARY KEY(company_id,invoice_id));""")
        c.commit()
        sql=(Path(__file__).resolve().parent.parent/"lhdn-submission-intents.review.sql").read_text()
        c.execute(sql)
        c.commit()
        now=datetime.now(timezone.utc)
        from zoneinfo import ZoneInfo
        f=MapperTests();f.setUp()
        f.inv["issueDate"]=now.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
        owner,outsider,company,other=uuid4(),uuid4(),uuid4(),uuid4()
        for uid in (owner,outsider):
            c.execute("INSERT INTO myr_native.users(id,email,email_verified_at) VALUES(%s,%s,now())",(uid,uid.hex+"@example.invalid"))
        for cid,uid in ((company,owner),(other,outsider)):
            c.execute("INSERT INTO myr_native.companies(id,tin,data) VALUES(%s,%s,%s)",(cid,f.company["tin"],Jsonb(f.company)))
            c.execute("INSERT INTO myr_native.company_members VALUES(%s,%s,'Owner','active')",(cid,uid.hex+"@example.invalid"))
        c.commit()
        key=(company,"INV-ID","sandbox")
        def prep(cid=company,actor=owner,version=1):
            return prepare(c,cid,"INV-ID","sandbox",version,actor,2919,datetime.now(timezone.utc))
        assert readiness(c,owner,company,"INV-ID",1,2919,now)["status"]=="offline_preview_ready"
        assert readiness(c,outsider,company,"INV-ID",1,2919,now)["status"]=="unavailable"
        reject(c,lambda:prep(actor=outsider))
        reject(c,lambda:prep(version=2))
        assert prep()["state"]=="prepared"
        c.commit()
        reject(c,prep)
        reject(c,lambda:c.execute("UPDATE myr_native.companies SET data=jsonb_set(data,'{invoices}','[]') WHERE id=%s",(company,)),psycopg.errors.CheckViolation)
        reject(c,lambda:c.execute("UPDATE myr_native.companies SET data=jsonb_set(data,'{invoices,0,number}','\"CHANGED\"') WHERE id=%s",(company,)),psycopg.errors.CheckViolation)
        c.execute("UPDATE myr_native.company_members SET status='removed' WHERE company_id=%s",(company,))
        c.commit()
        reject(c,lambda:reserve(c,*key,1,datetime.now(timezone.utc)))
        c.execute("UPDATE myr_native.company_members SET status='active' WHERE company_id=%s",(company,))
        c.commit()
        payload=reserve(c,*key,1,datetime.now(timezone.utc))
        assert payload["documents"][0]["codeNumber"]=="INV-001"
        c.commit()
        # A different DB connection sees committed reservation and cannot reserve again.
        with connect() as c2:
            assert row(c2,key,False)["state"]=="dispatching"
            reject(c2,lambda:reserve(c2,*key,1,datetime.now(timezone.utc)))
        response={"submissionUid":"SYNTHETIC-SUB","acceptedDocuments":[{"uuid":"SYNTHETIC-DOC","invoiceCodeNumber":"INV-001"}],"rejectedDocuments":[]}
        reject(c,lambda:accept(c,*key,200,response,datetime.now(timezone.utc)))
        assert accept(c,*key,202,response,datetime.now(timezone.utc)).uuid=="SYNTHETIC-DOC"
        c.commit()
        now=datetime.now(timezone.utc)
        result={"submissionUid":"SYNTHETIC-SUB","documentSummary":[{"uuid":"SYNTHETIC-DOC","submissionUid":"SYNTHETIC-SUB",
            "internalId":"INV-001","issuerTin":f.company["tin"],"status":"Valid","longId":"SYNTHETIC-LONG","dateTimeValidated":now.isoformat()}]}
        assert sync(c,*key,result,now)["state"]=="valid"
        c.commit()
        assert "preprod." in sync(c,*key,result,now)["verification_url"]
        assert cancel_plan(row(c,key),now,"Synthetic correction")[1]["status"]=="cancelled"
        c.commit()
        result["documentSummary"][0]["status"]="Cancelled"
        assert sync(c,*key,result,now)["state"]=="cancelled"
        c.commit()
        result["documentSummary"][0]["status"]="Valid"
        reject(c,lambda:sync(c,*key,result,now))
        assert prep(other,outsider)["state"]=="prepared"
        c.commit()
        second=(other,"INV-ID","sandbox")
        reserve(c,*second,1,datetime.now(timezone.utc))
        c.commit()
        outcome_unknown(c,*second,datetime.now(timezone.utc))
        c.commit()
        reject(c,lambda:reserve(c,*second,1,datetime.now(timezone.utc)))
        assert c.execute("SELECT count(*) FROM myr_native.lhdn_documents").fetchone()[0]==0
        print("MYR_LHDN_DISPOSABLE_DB_REHEARSAL_OK")
        print("Synthetic schema, committed reservations, mutation protection, role revocation, tenant checks, status and uncertain outcomes passed.")
if __name__=="__main__":
    main()
