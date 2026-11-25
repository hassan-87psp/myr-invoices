"""Opt-in synthetic-only private write rehearsal. Real imported data stays read-only."""
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from psycopg.types.json import Jsonb
from staging_api import api, db, bearer
from hybrid_workspace import verify_user, workspace, GRANT
from native_record_writes import save_record, WriteRejected
from app import connect
from native_payment_ops import add_payment, delete_record

WRITE_GRANT=GRANT.with_name("hybrid-write-test-company")
TEST_NAME="MYR VPS WRITE TEST (synthetic)"
def test_company(conn, uid, email):
    # Existing verified preview grant required; no broader access.
    workspace(conn,uid,email)
    try:
        cid=UUID(WRITE_GRANT.read_text().strip())
    except (OSError,ValueError):
        raise HTTPException(403,"Synthetic write rehearsal not enabled") from None
    row=conn.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.version,c.data,c.created_at
      FROM myr_native.companies c JOIN myr_native.company_members m ON c.id=m.company_id
      WHERE c.id=%s AND c.created_by=%s AND c.name=%s AND c.status='active'
        AND m.email=%s AND m.role='Owner' AND m.status='active'""",(cid,uid,TEST_NAME,email)).fetchone()
    if not row or row[6].get("vpsSyntheticWriteTest") is not True:
        raise HTTPException(403,"Synthetic test company unavailable")
    return dict(zip(("id","name","tin","plan","status","version","data","created_at"),row))

@api.get("/hybrid/write-workspace")
def read_test(request:Request,conn=Depends(db)):
    uid,email=verify_user(bearer(request))
    conn.execute("SET TRANSACTION READ ONLY")
    co=test_company(conn,uid,email)
    return {"profile":{"id":uid,"email":email,"name":"Test owner","is_platform_admin":False},
       "companies":[co],"members":[{"company_id":co["id"],"email":email,"name":"Test owner","role":"Owner","status":"active","created_at":co["created_at"]}],
       "documents":[],"links":[],"mode":"synthetic_write"}

class RecordBody(BaseModel):
    p_company_id:UUID
    p_kind:str
    p_record:dict
    p_expected:dict|None=None

@api.post("/hybrid/test-record")
def write_test(body:RecordBody,request:Request,conn=Depends(db)):
    uid,email=verify_user(bearer(request))
    co=test_company(conn,uid,email)
    if co["id"]!=body.p_company_id:
        raise HTTPException(403,"Only the synthetic test company can be changed")
    # Serialize and commit before acknowledging success.
    try:
        result=save_record(conn,uid,email,co["id"],body.p_kind,body.p_record,body.p_expected)
        conn.commit()
        return result
    except WriteRejected as exc:
        conn.rollback()
        raise HTTPException(409,str(exc)) from None

class PaymentBody(BaseModel):
    p_company_id:UUID
    p_invoice_id:str
    p_payment:dict

class DeleteBody(BaseModel):
    p_company_id:UUID
    p_kind:str
    p_expected:dict

def checked_operation(conn,request,cid,operation):
    uid,email=verify_user(bearer(request))
    co=test_company(conn,uid,email)
    if co["id"]!=cid:
        raise HTTPException(403,"Only the synthetic test company can be changed")
    try:
        result=operation(uid,email)
        conn.commit()
        return result
    except WriteRejected as exc:
        conn.rollback()
        raise HTTPException(409,str(exc)) from None

@api.post("/hybrid/test-payment")
def payment_test(body:PaymentBody,request:Request,conn=Depends(db)):
    return checked_operation(conn,request,body.p_company_id,
        lambda uid,email:add_payment(conn,uid,email,body.p_company_id,body.p_invoice_id,body.p_payment))

@api.post("/hybrid/test-delete")
def deletion_test(body:DeleteBody,request:Request,conn=Depends(db)):
    return checked_operation(conn,request,body.p_company_id,
        lambda uid,email:delete_record(conn,uid,email,body.p_company_id,body.p_kind,body.p_expected))

def setup():
    uid=UUID(GRANT.read_text().strip())
    with connect() as conn:
        row=conn.execute("SELECT email FROM myr_native.users WHERE id=%s",(uid,)).fetchone()
        if not row:
            raise SystemExit("Approved owner not found")
        email=row[0]
        workspace(conn,uid,email)
        if WRITE_GRANT.exists():
            test_company(conn,uid,email)
            print("VPS_SYNTHETIC_WRITE_COMPANY_ALREADY_READY")
            return
        cid=uuid4()
        data={"id":str(cid),"name":TEST_NAME,"plan":"Starter","tin":"","prefix":"TEST-","nextNo":1001,
           "customers":[],"products":[],"invoices":[],"requests":[],"imports":[],"audit":[],
           "vpsSyntheticWriteTest":True}
        conn.execute("""INSERT INTO myr_native.companies(id,name,created_by,data)
            VALUES(%s,%s,%s,%s)""",(cid,TEST_NAME,uid,Jsonb(data)))
        conn.execute("""INSERT INTO myr_native.company_members(company_id,email,name,role,status)
            VALUES(%s,%s,'Test owner','Owner','active')""",(cid,email))
        conn.commit()
    fd,name=tempfile.mkstemp(dir=WRITE_GRANT.parent,prefix=".hybrid-test-")
    with os.fdopen(fd,"w") as f:
        f.write(str(cid)+"\n")
    os.replace(name,WRITE_GRANT)
    print("VPS_SYNTHETIC_WRITE_COMPANY_READY")

if __name__=="__main__":
    setup()
