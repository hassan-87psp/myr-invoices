"""Private staging API. Do not expose through Nginx or public interfaces."""
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app import connect
from native_auth import authenticate, issue_session, session_user, revoke_session

api = FastAPI(title="Native staging API", docs_url=None, redoc_url=None, openapi_url=None)

def db():
    with connect() as conn:
        yield conn

@api.middleware("http")
async def private_only(request: Request, call_next):
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        return Response(status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

class Login(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)

def bearer(request):
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Authentication required")
    return token

def identity(conn, request):
    user = session_user(conn, bearer(request))
    if not user:
        raise HTTPException(401, "Authentication required")
    return user

@api.post("/auth/login")
def login(body: Login, conn=Depends(db)):
    uid = authenticate(conn, body.email, body.password)
    if uid is None:
        raise HTTPException(401, "Invalid credentials or account unavailable")
    try:
        return {"access_token": issue_session(conn, uid), "token_type": "bearer",
                "expires_in": 43200}
    except PermissionError:
        raise HTTPException(401, "Invalid credentials or account unavailable")

@api.get("/auth/me")
def me(request: Request, conn=Depends(db)):
    uid, email, name, admin = identity(conn, request)
    return {"id": str(uid), "email": email, "name": name, "is_platform_admin": admin}

@api.post("/auth/logout", status_code=204)
def logout(request: Request, conn=Depends(db)):
    revoke_session(conn, bearer(request))
    return Response(status_code=204)

@api.get("/companies")
def companies(request: Request, conn=Depends(db)):
    uid, _, _, _ = identity(conn, request)
    rows = conn.execute(
        """SELECT c.id,c.name,c.plan,m.role
           FROM myr_native.users u
           JOIN myr_native.company_members m ON m.email=u.email
           JOIN myr_native.companies c ON c.id=m.company_id
           WHERE u.id=%s AND NOT u.disabled AND u.email_verified_at IS NOT NULL
             AND m.status='active' AND c.status='active'
           ORDER BY c.name,c.id""", (uid,)
    ).fetchall()
    return [{"id":str(r[0]),"name":r[1],"plan":r[2],"role":r[3]} for r in rows]

# Local-only account lifecycle integration. Default mail dependency fails closed.
from uuid import UUID
from account_lifecycle import begin_signup, begin_reset, finish_password, normalize_email
from account_mail import staging_mailer

class EmailRequest(BaseModel):
    email: str = Field(min_length=1,max_length=254)

class FinishRequest(BaseModel):
    token: str = Field(min_length=32,max_length=128)
    password: str = Field(min_length=12,max_length=128)
    name: str = Field(default="",max_length=120)

def request_account_email(conn, body, sender, purpose):
    try:
        email=normalize_email(body.email)
    except ValueError:
        raise HTTPException(422,"Invalid email")
    token=(begin_signup if purpose=="verify_email" else begin_reset)(conn,email)
    if token:
        sender(email,token,purpose)
    return {"status":"accepted"}

@api.post("/auth/signup",status_code=202)
def signup(body: EmailRequest, conn=Depends(db), sender=Depends(staging_mailer)):
    return request_account_email(conn,body,sender,"verify_email")

@api.post("/auth/reset-request",status_code=202)
def reset_request(body: EmailRequest, conn=Depends(db), sender=Depends(staging_mailer)):
    return request_account_email(conn,body,sender,"reset_password")

def complete_account(conn,body,purpose):
    try:
        ok=finish_password(conn,body.token,body.password,purpose,body.name)
    except ValueError:
        ok=False
    if not ok:
        raise HTTPException(400,"Invalid or expired account link")
    return {"status":"ok"}

@api.post("/auth/verify-email")
def verify_email(body: FinishRequest, conn=Depends(db)):
    return complete_account(conn,body,"verify_email")

@api.post("/auth/reset-password")
def reset_password(body: FinishRequest, conn=Depends(db)):
    return complete_account(conn,body,"reset_password")

@api.get("/companies/{company_id}/summary")
def company_summary(company_id: UUID, request: Request, conn=Depends(db)):
    uid,_,_,_=identity(conn,request)
    row=conn.execute("""SELECT c.id,c.name,c.plan,c.version,m.role
        FROM myr_native.users u JOIN myr_native.company_members m ON m.email=u.email
        JOIN myr_native.companies c ON c.id=m.company_id
        WHERE u.id=%s AND c.id=%s AND NOT u.disabled AND u.email_verified_at IS NOT NULL
        AND m.status='active' AND c.status='active'""",(uid,company_id)).fetchone()
    if not row:
        raise HTTPException(404,"Company unavailable")
    return dict(zip(("id","name","plan","version","role"),(str(row[0]),*row[1:])))

# Only trusted company administrators may retrieve the legacy full JSON snapshot.
# Other roles get the summary endpoint until field-level data filtering exists.
@api.get("/companies/{company_id}/snapshot")
def company_snapshot(company_id: UUID, request: Request, conn=Depends(db)):
    uid,_,_,_=identity(conn,request)
    row=conn.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.version,c.data,c.created_at
        FROM myr_native.users u JOIN myr_native.company_members m ON m.email=u.email
        JOIN myr_native.companies c ON c.id=m.company_id
        WHERE u.id=%s AND c.id=%s AND NOT u.disabled AND u.email_verified_at IS NOT NULL
        AND m.status='active' AND c.status='active' AND m.role IN ('Owner','Admin')""",
        (uid,company_id)).fetchone()
    if not row:
        raise HTTPException(404,"Company unavailable")
    return dict(zip(("id","name","tin","plan","status","version","data","created_at"),
                    (str(row[0]),*row[1:])))
