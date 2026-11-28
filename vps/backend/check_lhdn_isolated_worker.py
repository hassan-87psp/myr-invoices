"""Synthetic integration test for private Sandbox worker and real PostgreSQL locks.
No production connection, credentials, real taxpayer or external request."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch,Mock
import os,sys,stat
import psycopg
from psycopg.types.json import Jsonb
from lhdn_saved_invoice_candidate import MapperTests
from lhdn_lifecycle_candidate import prepare,reserve,row
import lhdn_sandbox_dispatch_candidate as dispatch
import lhdn_sandbox_poll_candidate as poll
import business_lhdn as central

def connect(role):
    root=Path(sys.argv[1]).resolve(strict=True)
    assert root.name.startswith("myr-lhdn-isolated-") and root.stat().st_uid==os.getuid()
    assert stat.S_IMODE(root.stat().st_mode)==0o700
    assert role in ("myr_lhdn_sandbox_admin","myr_lhdn_sandbox_worker")
    c=psycopg.connect(host=str(root/"socket"),port=55441,dbname="myr_lhdn_sandbox",user=role,sslmode="disable",connect_timeout=5,options="-c statement_timeout=10000 -c lock_timeout=5000")
    if c.execute("SELECT current_database(),current_user,inet_server_addr()").fetchone()!=("myr_lhdn_sandbox",role,None):
        c.close();raise RuntimeError("Unexpected database identity")
    c.commit()
    return c

def admin():return connect("myr_lhdn_sandbox_admin")
def worker():return connect("myr_lhdn_sandbox_worker")
def reject(c,f,errors=(ValueError,)):
    try:
        with c.transaction():f()
    except errors:return
    raise AssertionError("Expected rejection")

def main():
    now=datetime.now(timezone.utc)
    f=MapperTests();f.setUp()
    f.inv["issueDate"]=now.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
    tin=f.company["tin"];brn=f.company["brn"]
    pairs=[(uuid4(),uuid4()) for _ in range(4)]
    with admin() as c:
        for cid,uid in pairs:
            email=uid.hex+"@example.invalid"
            c.execute("INSERT INTO myr_native.users(id,email,email_verified_at) VALUES(%s,%s,now())",(uid,email))
            c.execute("INSERT INTO myr_native.companies(id,tin,data) VALUES(%s,%s,%s)",(cid,tin,Jsonb(f.company)))
            c.execute("INSERT INTO myr_native.company_members VALUES(%s,%s,'Owner','active')",(cid,email))
    cid,uid=pairs[0];key=(cid,"INV-ID","sandbox")
    with worker() as c:
        dispatch.check_database(c)
        assert not c.execute("SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()[0]
        reject(c,lambda:c.execute("UPDATE myr_native.companies SET version=2 WHERE id=%s",(cid,)),(psycopg.errors.InsufficientPrivilege,))
        reject(c,lambda:c.execute("UPDATE myr_native.users SET disabled=true WHERE id=%s",(uid,)),(psycopg.errors.InsufficientPrivilege,))
        reject(c,lambda:c.execute("UPDATE myr_native.company_members SET status='removed' WHERE company_id=%s",(cid,)),(psycopg.errors.InsufficientPrivilege,))
        reject(c,lambda:c.execute("INSERT INTO myr_native.lhdn_documents VALUES(%s,'INV-ID')",(cid,)),(psycopg.errors.InsufficientPrivilege,))
        reject(c,lambda:prepare(c,cid,"INV-ID","sandbox",1,pairs[1][1],2919,now))
        c.commit()
        assert prepare(c,cid,"INV-ID","sandbox",1,uid,2919,now)["state"]=="prepared"
        c.commit()
        x=row(c,key,False)
        reject(c,lambda:c.execute("UPDATE myr_native.lhdn_submission_intents SET document_hash=%s WHERE company_id=%s",("f"*64,cid)),(psycopg.errors.InsufficientPrivilege,))
        reject(c,lambda:c.execute("DELETE FROM myr_native.lhdn_submission_intents WHERE company_id=%s",(cid,)),(psycopg.errors.InsufficientPrivilege,))
        c.commit()
    g={"tenant_id":str(cid),"taxpayer":tin,"document_hash":x["hash"],"code_number":x["code"],"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat().replace("+00:00","Z")}
    sub,doc="S"*26,"D"*26
    receipt={"submissionUid":sub,"acceptedDocuments":[{"uuid":doc,"invoiceCodeNumber":x["code"]}],"rejectedDocuments":[]}
    def mock_send(grant,payload):
        assert grant==g and payload["documents"][0]["documentHash"]==x["hash"]
        with worker() as c:assert row(c,key,False)["state"]=="dispatching"
        return receipt
    with patch.object(central,"approved_target",return_value=tin),patch.object(dispatch,"grant",return_value=g),patch.object(dispatch,"post_once",side_effect=mock_send) as send:
        assert dispatch.run_once(worker,cid,"INV-ID",1)["state"]=="accepted"
        assert send.call_count==1
        try:dispatch.run_once(worker,cid,"INV-ID",1)
        except ValueError:pass
        else:raise AssertionError("Duplicate dispatch accepted")
        assert send.call_count==1
    with worker() as c:
        x=row(c,key,False)
        assert x["state"]=="accepted" and x["submission"]==sub and x["uuid"]==doc
        assert x["validated_at"] is None
    g=g|{"submission_uid":sub,"uuid":doc}
    t=x["updated_at"]+timedelta(seconds=6)
    response={"submissionUid":sub,"documentSummary":[{"uuid":doc,"submissionUid":sub,"internalId":x["code"],"issuerTin":tin,"status":"Valid","longId":"SYNTHETIC-LONG","dateTimeValidated":t.isoformat()}]}
    def mock_poll(grant):
        assert grant==g
        with worker() as c:
            assert c.execute("SELECT poll_claim IS NOT NULL FROM myr_native.lhdn_submission_intents WHERE company_id=%s",(cid,)).fetchone()[0]
        return {"state":"polled","http_status":200,"response":response}
    with patch.object(central,"approved_target",return_value=tin),patch.object(poll,"grant",return_value=g):
        out=poll.run_poll_once(worker,cid,"INV-ID",mock_poll,lambda:t)
        assert out["state"]=="valid" and out["verification_url"].startswith("https://preprod.myinvois.hasil.gov.my/")
    # Real concurrent transactions race for one reservation.
    cid2,uid2=pairs[1];key2=(cid2,"INV-ID","sandbox")
    with worker() as c:prepare(c,cid2,"INV-ID","sandbox",1,uid2,2919,datetime.now(timezone.utc))
    barrier=Barrier(2)
    def reserve_race():
        try:
            with worker() as c:
                barrier.wait(timeout=5)
                reserve(c,*key2,1,datetime.now(timezone.utc))
            return "reserved"
        except ValueError:return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(reserve_race) for _ in range(2)]
        assert sorted(x.result(timeout=15) for x in futures)==["blocked","reserved"]
    # Owner revoked after prepare: no provider call.
    cid3,uid3=pairs[2]
    with worker() as c:
        prepare(c,cid3,"INV-ID","sandbox",1,uid3,2919,datetime.now(timezone.utc))
        c.commit();z=row(c,(cid3,"INV-ID","sandbox"),False)
    with admin() as c:c.execute("UPDATE myr_native.company_members SET status='removed' WHERE company_id=%s",(cid3,))
    g3={"tenant_id":str(cid3),"taxpayer":tin,"document_hash":z["hash"],"code_number":z["code"],"expires_at":g["expires_at"]}
    with patch.object(central,"approved_target",return_value=tin),patch.object(dispatch,"grant",return_value=g3),patch.object(dispatch,"post_once") as send:
        try:dispatch.run_once(worker,cid3,"INV-ID",1)
        except ValueError:pass
        else:raise AssertionError("Revoked owner accepted")
        send.assert_not_called()
    # Ambiguous result stays uncertain and cannot be blindly resent.
    cid4,uid4=pairs[3]
    with worker() as c:
        prepare(c,cid4,"INV-ID","sandbox",1,uid4,2919,datetime.now(timezone.utc))
        c.commit();z=row(c,(cid4,"INV-ID","sandbox"),False)
    g4=g3|{"tenant_id":str(cid4),"document_hash":z["hash"],"code_number":z["code"]}
    with patch.object(central,"approved_target",return_value=tin),patch.object(dispatch,"grant",return_value=g4),patch.object(dispatch,"post_once",side_effect=TimeoutError) as send:
        assert dispatch.run_once(worker,cid4,"INV-ID",1)["state"]=="outcome_unknown"
        try:dispatch.run_once(worker,cid4,"INV-ID",1)
        except ValueError:pass
        else:raise AssertionError("Uncertain dispatch retried")
        assert send.call_count==1
    with admin() as c:
        assert c.execute("SELECT count(*) FROM myr_native.lhdn_documents").fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM myr_native.lhdn_submission_intents WHERE environment<>'sandbox'").fetchone()[0]==0
        assert c.execute("SELECT state FROM myr_native.lhdn_submission_intents WHERE company_id=%s",(cid,)).fetchone()[0]=="valid"
    print("MYR_SANDBOX_WORKER_REHEARSAL_OK",flush=True)
if __name__=="__main__":main()
