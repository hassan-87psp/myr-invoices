"""Separate VPS production API candidate. Not the private staging app.

Only verified, imported Supabase identities and active owners may access real
company snapshots. Writes fail closed unless an operator explicitly enables
them after reconciliation and complete frontend acceptance. Bind loopback only.
"""
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app import connect
from hybrid_workspace import verify_user
from native_record_writes import save_record, WriteRejected
from native_payment_ops import add_payment, delete_record
from business_onboarding import create_company, update_profile

api=FastAPI(title="MYR business API",docs_url=None,redoc_url=None,openapi_url=None)
WRITE_FLAG=Path.home()/".config/myrinvoice/production-writes-enabled"

def db():
    with connect() as conn:
        yield conn

@api.middleware("http")
async def headers(request,call_next):
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response

def verified_identity(request):
    scheme,_,token=request.headers.get("authorization","").partition(" ")
    if scheme.lower()!="bearer" or not token:
        raise HTTPException(401,"Authentication required")
    return verify_user(token)

def identity(conn,request):
    uid,email=verified_identity(request)
    row=conn.execute("""SELECT id,email,name,is_platform_admin FROM myr_native.users
        WHERE id=%s AND email=%s AND email_verified_at IS NOT NULL""",(uid,email)).fetchone()
    if not row:
        raise HTTPException(403,"Verified account not provisioned")
    # Imported native password accounts are disabled. Supabase is the sole
    # external identity authority; native password login is not exposed here.
    return dict(zip(("id","email","name","is_platform_admin"),row))

def owner_company(conn,profile,cid,lock=False):
    if profile["is_platform_admin"]:
        raise HTTPException(403,"Business owner required")
    sql="""SELECT c.id FROM myr_native.companies c JOIN myr_native.company_members m
        ON m.company_id=c.id WHERE c.id=%s AND c.status='active'
        AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
        AND m.email=%s AND m.role='Owner' AND m.status='active'"""
    if lock:
        sql+=" FOR UPDATE OF c FOR SHARE OF m"
    if not conn.execute(sql,(cid,profile["email"])).fetchone():
        raise HTTPException(404,"Company unavailable")

def workspace(conn,profile):
    if profile["is_platform_admin"]:
        raise HTTPException(403,"Business owner required")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.version,c.data,c.created_at
            FROM myr_native.companies c JOIN myr_native.company_members m ON m.company_id=c.id
            WHERE m.email=%s AND m.role='Owner' AND m.status='active' AND c.status='active'
            AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
            ORDER BY c.created_at,c.id""",(profile["email"],))
        companies=cur.fetchall()
        ids=[c["id"] for c in companies]
        cur.execute("""SELECT company_id,email,name,role,status,created_at
            FROM myr_native.company_members WHERE company_id=ANY(%s) AND status<>'removed'""",(ids,))
        members=cur.fetchall()
        cur.execute("""SELECT company_id,invoice_id,environment,code_number,submission_uid,uuid,long_id,status,validated_at,errors,accepted_at,updated_at
            FROM myr_native.lhdn_documents WHERE company_id=ANY(%s)""",(ids,))
        documents=cur.fetchall()
        cur.execute("""SELECT token,company_id,kind,ref_id,closed,data,submits
            FROM myr_native.public_links WHERE company_id=ANY(%s)""",(ids,))
        links=cur.fetchall()
    return {"profile":profile,"companies":companies,"members":members,"documents":documents,"links":links,
            "mode":"native_candidate","writes_enabled":False}

@api.get("/health")
def health(conn=Depends(db)):
    conn.execute("SELECT 1").fetchone()
    return {"status":"ok","database":"vps","stage":"candidate","writes_enabled":False}

@api.get("/workspace")
def read_workspace(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return workspace(conn,identity(conn,request))

# No production writes exposed yet. These entry points deliberately fail
# closed while the source remains live, even if a client tries direct requests.
def checked_write(conn,request,cid,operation):
    profile=identity(conn,request)
    owner_company(conn,profile,cid,lock=True)
    require_cutover()
    return run_write(conn,lambda:operation(profile["id"],profile["email"]))

def require_cutover():
    # Hard gate: no live writes until the source is frozen, verified and
    # full business functionality has passed acceptance. Never toggle via HTTP.
    raise HTTPException(503,"Production cutover not released")

def run_write(conn,operation):
    try:
        result=operation()
        conn.commit()
        return result
    except WriteRejected as exc:
        conn.rollback()
        raise HTTPException(409,str(exc)) from None

class ProfileBody(BaseModel):
    p_company_id:UUID
    p_version:int
    p_profile:dict

class OnboardBody(BaseModel):
    p_profile:dict

@api.post("/onboard")
def onboard(body:OnboardBody,request:Request,conn=Depends(db)):
    uid,email=verified_identity(request)
    require_cutover()
    return run_write(conn,lambda:create_company(conn,uid,email,body.p_profile))

@api.post("/profile")
def profile(body:ProfileBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:update_profile(conn,uid,email,body.p_company_id,body.p_version,body.p_profile))

class RecordBody(BaseModel):
    p_company_id:UUID
    p_kind:str
    p_record:dict
    p_expected:dict|None=None
    p_auto:bool=False

class PaymentBody(BaseModel):
    p_company_id:UUID
    p_invoice_id:str=Field(max_length=128)
    p_payment:dict

class DeleteBody(BaseModel):
    p_company_id:UUID
    p_kind:str
    p_expected:dict

@api.post("/records")
def records(body:RecordBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:save_record(conn,uid,email,body.p_company_id,body.p_kind,body.p_record,body.p_expected,body.p_auto))

@api.post("/payments")
def payments(body:PaymentBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:add_payment(conn,uid,email,body.p_company_id,body.p_invoice_id,body.p_payment))

@api.post("/delete")
def delete(body:DeleteBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:delete_record(conn,uid,email,body.p_company_id,body.p_kind,body.p_expected))

def test():
    uid,cid,other,synthetic=uuid4(),uuid4(),uuid4(),uuid4()
    email="candidate-"+uid.hex+"@example.invalid"
    conn=connect()
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        for company,marker in ((cid,False),(other,False),(synthetic,True)):
            conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Candidate fixture',%s,%s)",(company,uid,Jsonb({"vpsSyntheticWriteTest":marker,"customers":[],"products":[],"invoices":[]})))
        for company in (cid,synthetic):
            conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(company,email))
        profile={"id":uid,"email":email,"name":"Test","is_platform_admin":False}
        result=workspace(conn,profile)
        assert [x["id"] for x in result["companies"]]==[cid]
        assert result["writes_enabled"] is False
        owner_company(conn,profile,cid)
        for blocked in (other,synthetic):
            try: owner_company(conn,profile,blocked)
            except HTTPException as exc: assert exc.status_code==404
            else: raise AssertionError("Cross-tenant or synthetic access")
        conn.execute("UPDATE myr_native.company_members SET role='Read-Only' WHERE company_id=%s AND email=%s",(cid,email))
        assert workspace(conn,profile)["companies"]==[]
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.companies WHERE id=ANY(%s)",([cid,other,synthetic],)).fetchone()[0]==0
    print("MYR_PRODUCTION_CANDIDATE_ISOLATION_OK")
# Keep the candidate on the private loopback service only.
from fastapi.staticfiles import StaticFiles
candidate=Path.home()/"myr-staging"/"business-candidate"
if candidate.is_dir():
    api.mount("/candidate",StaticFiles(directory=candidate,html=True),name="business-candidate")

if __name__=="__main__":
    test()
