"""Separate VPS production API candidate. Not the private staging app.

Only verified, provisioned Supabase identities and active members may access real
company snapshots. Writes fail closed unless an operator explicitly enables
them after reconciliation and complete frontend acceptance. Bind loopback only.
"""
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
import os, stat
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app import connect
from hybrid_workspace import verify_user
from native_record_writes import save_record, WriteRejected
from native_payment_ops import add_payment, delete_record
from business_onboarding import create_company, update_profile
from native_team_workflow import team_change, invoice_workflow, accept_invites
from business_admin import admin_company_rows, set_company, link_inventory, dashboard
from business_links import read_link, submit_link
from business_link_ops import operate as link_operation
import business_native_auth as native

api=FastAPI(title="MYR business API",docs_url=None,redoc_url=None,openapi_url=None)
WRITE_FLAG=Path.home()/".config/myrinvoice/production-writes-enabled"
NATIVE_FLAG=Path.home()/".config/myrinvoice/native-auth-pilot-enabled"
api.include_router(native.router)

def db():
    with connect() as conn:
        yield conn

@api.middleware("http")
async def headers(request,call_next):
    if os.environ.get("MYR_PRODUCTION_RELEASE") and request.url.path.startswith("/native/") and not native_enabled():
        response=JSONResponse({"detail":"Native authentication not released"},status_code=503)
    else:
        response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response

def native_enabled():
    if not writes_enabled():
        return False
    try:
        st=NATIVE_FLAG.lstat()
        return (stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and not(st.st_mode & 0o077)
                and NATIVE_FLAG.read_text().strip()==os.environ.get("MYR_PRODUCTION_RELEASE"))
    except OSError:
        return False

def verified_identity(request,conn):
    # Native and legacy are explicit alternative credentials, never mixed.
    cookie=request.cookies.get(native.COOKIE)
    authorization=request.headers.get("authorization","")
    if cookie is not None:
        if not native_enabled():
            raise HTTPException(401,"Native authentication not released")
        if authorization:
            raise HTTPException(401,"Conflicting credentials")
        if request.method not in ("GET","HEAD","OPTIONS"):
            if request.headers.get("origin")!="https://myrinvoice.com":
                raise HTTPException(403,"Origin rejected")
            if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
                raise HTTPException(415,"JSON request required")
        p=native.current(conn,request)
        return p["id"],p["email"]
    scheme,_,token=authorization.partition(" ")
    if scheme.lower()!="bearer" or not token:
        raise HTTPException(401,"Authentication required")
    # Retain legacy access during the private preparation phase. Account authority
    # cutover is separate and must be accepted before exposing native routes.
    return verify_user(token)

def identity(conn,request):
    uid,email=verified_identity(request,conn)
    row=conn.execute("""SELECT id,email,name,is_platform_admin FROM myr_native.users
        WHERE id=%s AND email=%s AND email_verified_at IS NOT NULL""",(uid,email)).fetchone()
    if not row:
        raise HTTPException(403,"Verified account not provisioned")
    # Both credentials resolve the same account UUID and tenant memberships.
    # Native access remains separately gated until pilot approval.
    return dict(zip(("id","email","name","is_platform_admin"),row))

def workspace_identity(conn,request):
    """Unprovisioned verified accounts may see only an empty onboarding shell.
    An email collision must never inherit an existing tenant or administrator.
    """
    uid,email=verified_identity(request,conn)
    row=conn.execute("SELECT id,email,name,is_platform_admin,email_verified_at FROM myr_native.users WHERE id=%s OR email=%s",(uid,email)).fetchall()
    if not row:
        return {"id":uid,"email":email,"name":None,"is_platform_admin":False,"onboarding_only":True}
    if len(row)!=1 or row[0][0]!=uid or row[0][1]!=email or row[0][4] is None:
        raise HTTPException(403,"Verified account identity conflict")
    return dict(zip(("id","email","name","is_platform_admin"),row[0][:4]))

def owner_company(conn,profile,cid,lock=False,roles=('Owner',)):
    if profile["is_platform_admin"]:
        raise HTTPException(403,"Business owner required")
    sql="""SELECT c.id FROM myr_native.companies c JOIN myr_native.company_members m
        ON m.company_id=c.id WHERE c.id=%s AND c.status='active'
        AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
        AND m.email=%s AND m.role=ANY(%s) AND m.status='active'"""
    if lock:
        sql+=" FOR UPDATE OF c FOR SHARE OF m"
    if not conn.execute(sql,(cid,profile["email"],list(roles))).fetchone():
        raise HTTPException(404,"Company unavailable")

def workspace(conn,profile):
    if profile.get("onboarding_only"):
        return {"profile":profile,"companies":[],"members":[],"documents":[],"links":[],
                "mode":"native_candidate","writes_enabled":writes_enabled()}
    if profile["is_platform_admin"]:
        return {"profile":profile,"companies":[],"members":[],"documents":[],"links":[],
                "mode":"native_candidate","writes_enabled":writes_enabled()}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.version,c.data,c.created_at
            FROM myr_native.companies c JOIN myr_native.company_members m ON m.company_id=c.id
            WHERE m.email=%s AND m.role IN ('Owner','Admin','Accountant','Invoice Staff','Approver','Read-Only') AND m.status='active' AND c.status='active'
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
            "mode":"native_candidate","writes_enabled":writes_enabled()}

@api.get("/health")
def health(conn=Depends(db)):
    conn.execute("SELECT 1").fetchone()
    return {"status":"ok","database":"vps","stage":"production_core" if writes_enabled() else "candidate","writes_enabled":writes_enabled()}

@api.get("/workspace")
def read_workspace(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return workspace(conn,workspace_identity(conn,request))

@api.get("/native/workspace")
def native_workspace(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return workspace(conn,native.current(conn,request))

# No production writes exposed yet. These entry points deliberately fail
# closed while the source remains live, even if a client tries direct requests.
def checked_write(conn,request,cid,operation,roles=('Owner',)):
    profile=identity(conn,request)
    owner_company(conn,profile,cid,lock=True,roles=roles)
    require_cutover()
    return run_write(conn,lambda:operation(profile["id"],profile["email"]))

def writes_enabled():
    # Only the separately pinned production service can consume the marker.
    # Candidate services and rollback test processes never open this gate.
    import os, re, stat
    release=os.environ.get("MYR_PRODUCTION_RELEASE","")
    if not re.fullmatch(r"[0-9a-f]{40}",release):
        return False
    try:
        info=WRITE_FLAG.lstat()
        return (stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid()
                and not (info.st_mode & 0o077) and WRITE_FLAG.read_text().strip()==release)
    except OSError:
        return False

def require_cutover():
    if not writes_enabled():
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
    uid,email=verified_identity(request,conn)
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
        lambda uid,email:save_record(conn,uid,email,body.p_company_id,body.p_kind,body.p_record,body.p_expected,body.p_auto),roles=("Owner","Admin","Accountant","Invoice Staff"))

@api.post("/payments")
def payments(body:PaymentBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:add_payment(conn,uid,email,body.p_company_id,body.p_invoice_id,body.p_payment),roles=("Owner","Admin","Accountant"))

@api.post("/delete")
def delete(body:DeleteBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,
        lambda uid,email:delete_record(conn,uid,email,body.p_company_id,body.p_kind,body.p_expected),roles=("Owner","Admin","Accountant","Invoice Staff"))

class TeamBody(BaseModel):
    p_company_id:UUID
    p_operation:str=Field(max_length=16)
    p_email:str=Field(max_length=254)
    p_role:str|None=None

class ApprovalBody(BaseModel):
    p_company_id:UUID
    p_invoice_id:str=Field(max_length=128)
    p_version:int
    p_action:str=Field(max_length=16)

@api.post("/team/accept")
def accept_team(request:Request,conn=Depends(db)):
    uid,email=verified_identity(request,conn)
    require_cutover()
    return run_write(conn,lambda:accept_invites(conn,uid,email))

@api.post("/team")
def team(body:TeamBody,request:Request,conn=Depends(db)):
    def op(uid,email):
        version=team_change(conn,uid,email,body.p_company_id,body.p_operation,body.p_email,body.p_role,synthetic=False)
        return {"version":version,"email_sent":False}
    return checked_write(conn,request,body.p_company_id,op)

@api.post("/approval")
def approval(body:ApprovalBody,request:Request,conn=Depends(db)):
    profile=identity(conn,request)
    require_cutover()
    return run_write(conn,lambda:invoice_workflow(conn,profile["id"],profile["email"],
        body.p_company_id,body.p_invoice_id,body.p_version,body.p_action,synthetic=False))

def admin_summary(conn,profile):
    if not profile["is_platform_admin"]:
        raise HTTPException(403,"Platform administrator required")
    row=conn.execute("""SELECT count(*),
        count(*) FILTER (WHERE status='active'),
        count(*) FILTER (WHERE status='suspended'),
        coalesce(sum(CASE WHEN jsonb_typeof(data->'invoices')='array' THEN jsonb_array_length(data->'invoices') ELSE 0 END),0),
        coalesce(sum(CASE WHEN jsonb_typeof(data->'customers')='array' THEN jsonb_array_length(data->'customers') ELSE 0 END),0)
        FROM myr_native.companies WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'""").fetchone()
    return dict(zip(("companies","active_companies","suspended_companies","invoices","customers"),row))

@api.get("/admin/summary")
def admin_overview(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return admin_summary(conn,identity(conn,request))

def admin_identity(conn,request):
    profile=identity(conn,request)
    if not profile["is_platform_admin"]:
        raise HTTPException(403,"Platform administrator required")
    return profile

@api.get("/admin/dashboard")
def admin_dashboard(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return dashboard(conn,admin_identity(conn,request))

@api.get("/admin/companies")
def admin_companies(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    return admin_company_rows(conn,admin_identity(conn,request))

@api.get("/admin/link-inventory")
def admin_links(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    admin_identity(conn,request)
    return link_inventory(conn)

class AdminCompanyBody(BaseModel):
    p_company_id:UUID
    p_version:int
    p_status:str|None=None
    p_plan:str|None=None

@api.post("/admin/company")
def admin_change(body:AdminCompanyBody,request:Request,conn=Depends(db)):
    profile=admin_identity(conn,request)
    require_cutover()
    return run_write(conn,lambda:set_company(conn,profile,body.p_company_id,body.p_version,body.p_status,body.p_plan))

class LinkManageBody(BaseModel):
    p_company_id:UUID
    p_version:int
    p_action:str=Field(max_length=32)
    p_payload:dict

@api.post("/links/manage")
def manage_link(body:LinkManageBody,request:Request,conn=Depends(db)):
    return checked_write(conn,request,body.p_company_id,lambda uid,email:link_operation(
        conn,uid,email,body.p_company_id,body.p_version,body.p_action,body.p_payload),
        roles=("Owner","Admin","Accountant","Invoice Staff"))

class LinkReadBody(BaseModel):
    p_token:str=Field(min_length=20,max_length=128)

class LinkSubmitBody(LinkReadBody):
    p_payload:dict

@api.post("/links/read")
def public_link_read(body:LinkReadBody,conn=Depends(db)):
    # This anonymous capability endpoint is not released to the public.
    require_cutover()
    conn.execute("SET TRANSACTION READ ONLY")
    try:
        return read_link(conn,body.p_token)
    except WriteRejected:
        raise HTTPException(404,"Link unavailable") from None

@api.post("/links/submit")
def public_link_submit(body:LinkSubmitBody,conn=Depends(db)):
    require_cutover()
    return run_write(conn,lambda:submit_link(conn,body.p_token,body.p_payload))

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
        assert workspace(conn,{"id":uuid4(),"email":"onboarding@example.invalid","name":None,"is_platform_admin":False,"onboarding_only":True})["companies"]==[]
        result=workspace(conn,profile)
        assert [x["id"] for x in result["companies"]]==[cid]
        assert result["writes_enabled"] is False
        owner_company(conn,profile,cid)
        for blocked in (other,synthetic):
            try: owner_company(conn,profile,blocked)
            except HTTPException as exc: assert exc.status_code==404
            else: raise AssertionError("Cross-tenant or synthetic access")
        conn.execute("UPDATE myr_native.company_members SET role='Read-Only' WHERE company_id=%s AND email=%s",(cid,email))
        assert [x["id"] for x in workspace(conn,profile)["companies"]]==[cid]
        try: owner_company(conn,profile,cid,roles=("Owner","Admin","Accountant","Invoice Staff"))
        except HTTPException as exc: assert exc.status_code==404
        else: raise AssertionError("Read-only user authorized for writes")
        conn.execute("UPDATE myr_native.company_members SET role='Accountant' WHERE company_id=%s AND email=%s",(cid,email))
        owner_company(conn,profile,cid,roles=("Owner","Admin","Accountant","Invoice Staff"))
        try: owner_company(conn,profile,cid)
        except HTTPException as exc: assert exc.status_code==404
        else: raise AssertionError("Accountant authorized for owner-only operation")
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.companies WHERE id=ANY(%s)",([cid,other,synthetic],)).fetchone()[0]==0
    print("MYR_PRODUCTION_CANDIDATE_ISOLATION_OK")
# Keep the candidate on the private loopback service only.
from fastapi.staticfiles import StaticFiles
import os
candidate=Path(os.environ.get("MYR_CANDIDATE_DIR",str(Path.home()/"myr-staging"/"business-candidate")))
if candidate.is_dir():
    api.mount("/candidate",StaticFiles(directory=candidate,html=True),name="business-candidate")

if __name__=="__main__":
    test()
    native.test()
