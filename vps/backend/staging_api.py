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
