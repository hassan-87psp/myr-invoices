"""Private native auth candidate. No public proxy or production activation.
The VPS owns passwords, account tokens and sessions. Email is delegated
to a separately configured Supabase Edge Function; fail closed if absent.
"""
from pathlib import Path
from uuid import UUID,uuid4
from threading import Lock
from time import monotonic
from collections import OrderedDict
from urllib.request import Request as URLRequest,build_opener,HTTPRedirectHandler
import json
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import BaseModel,Field
from fastapi.responses import HTMLResponse
from app import connect
from native_auth import authenticate,issue_session,session_user,revoke_session,digest,hash_password
from account_lifecycle import normalize_email,begin_signup,begin_reset,finish_password,new_token

router=APIRouter(prefix="/native/auth")
COOKIE="myr_native_session"
CONFIG=Path.home()/".config/myrinvoice"
ORIGIN="https://nynghaleoaqilewmhbdi.supabase.co"
APPROVED=CONFIG/"native-activation-users"
LOCK=Lock()
BUCKETS=OrderedDict()

def db():
    with connect() as conn:
        yield conn

def throttle(key,limit,period):
    now=monotonic()
    with LOCK:
        # Bounded single-worker candidate guard, not the final edge rate limiter.
        for k in list(BUCKETS):
            if BUCKETS[k][0]<=now:
                del BUCKETS[k]
        expiry,count=BUCKETS.get(key,(now+period,0))
        if count>=limit or (key not in BUCKETS and len(BUCKETS)>=10000):
            raise HTTPException(429,"Too many requests; try again later")
        BUCKETS[key]=(expiry,count+1)

def guard(request,action,email=""):
    # No trust in arbitrary forwarded headers; public proxy requires its own limiter.
    host=request.client.host if request.client else "unknown"
    throttle(("host",action,host),30,60)
    if email:
        throttle(("email",action,email),5,900)

def check_origin(request):
    origin=request.headers.get("origin")
    if origin not in ("https://myrinvoice.com","http://localhost:8766","http://127.0.0.1:8766"):
        raise HTTPException(403,"Origin rejected")
    if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
        raise HTTPException(415,"JSON request required")

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def sender():
    # Never accept endpoint URLs, secrets, templates or recipient addresses
    # from an untrusted browser. The function must independently authenticate.
    path=CONFIG/"supabase-mail-api-secret"
    try:
        if not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError()
        key=path.read_text().strip()
        if not 32<=len(key)<=512:
            raise ValueError()
    except (OSError,ValueError):
        raise HTTPException(503,"Account email service not configured") from None
    def send(email,token,purpose):
        body=json.dumps({"event":purpose,"recipient":email,"token":token}).encode()
        req=URLRequest(ORIGIN+"/functions/v1/myr-transactional-mail",data=body,
            headers={"X-MYR-Mail-Secret":key,"Content-Type":"application/json"},method="POST")
        try:
            with build_opener(NoRedirect()).open(req,timeout=10) as res:
                result=json.loads(res.read(8192))
                if res.status!=200 or result.get("accepted") is not True:
                    raise ValueError()
        except (OSError,ValueError):
            raise HTTPException(503,"Account email delivery unavailable") from None
    return send

def allowed_activation(uid):
    try:
        if not APPROVED.is_file() or APPROVED.stat().st_mode & 0o077:
            return False
        return uid in {UUID(v.strip()) for v in APPROVED.read_text().splitlines() if v.strip()}
    except (OSError,ValueError):
        return False

def begin_activation(conn,email,allowed=allowed_activation):
    row=conn.execute("""SELECT id FROM myr_native.users WHERE email=%s
       AND disabled AND email_verified_at IS NOT NULL AND password_hash IS NULL
       AND NOT is_platform_admin FOR UPDATE""",(email,)).fetchone()
    return new_token(conn,row[0],"verify_email") if row and allowed(row[0]) else None

def finish_activation(conn,token,password,allowed=allowed_activation):
    try:
        key=digest(token)
    except (ValueError,UnicodeError):
        return False
    row=conn.execute("""SELECT user_id FROM myr_native.auth_tokens
        WHERE token_digest=%s AND purpose='verify_email' AND used_at IS NULL AND expires_at>now()""",(key,)).fetchone()
    if not row or not allowed(row[0]):
        return False
    uid=row[0]
    user=conn.execute("""SELECT 1 FROM myr_native.users WHERE id=%s AND disabled
        AND email_verified_at IS NOT NULL AND password_hash IS NULL AND NOT is_platform_admin FOR UPDATE""",(uid,)).fetchone()
    if not user:
        return False
    ph=hash_password(password)
    consumed=conn.execute("""UPDATE myr_native.auth_tokens SET used_at=now()
        WHERE token_digest=%s AND user_id=%s AND purpose='verify_email'
        AND used_at IS NULL AND expires_at>now() RETURNING user_id""",(key,uid)).fetchone()
    if not consumed:
        return False
    conn.execute("UPDATE myr_native.users SET password_hash=%s,disabled=false WHERE id=%s",(ph,uid))
    conn.execute("UPDATE myr_native.auth_tokens SET used_at=now() WHERE user_id=%s AND used_at IS NULL",(uid,))
    conn.execute("UPDATE myr_native.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",(uid,))
    return True

class EmailBody(BaseModel):
    email:str=Field(min_length=1,max_length=254)
class LoginBody(EmailBody):
    password:str=Field(min_length=1,max_length=128)
class FinishBody(BaseModel):
    token:str=Field(min_length=32,max_length=128)
    password:str=Field(min_length=12,max_length=128)
    name:str=Field(default="",max_length=120)

def checked_email(value):
    try:
        return normalize_email(value)
    except ValueError:
        raise HTTPException(422,"Invalid email") from None

def current(conn,request):
    row=session_user(conn,request.cookies.get(COOKIE,""))
    if not row:
        raise HTTPException(401,"Native sign-in required")
    return dict(zip(("id","email","name","is_platform_admin"),row))

@router.post("/login")
def login(body:LoginBody,request:Request,response:Response,conn=Depends(db)):
    check_origin(request)
    email=checked_email(body.email)
    guard(request,"login",email)
    uid=authenticate(conn,email,body.password)
    if uid is None:
        raise HTTPException(401,"Invalid credentials or account unavailable")
    token=issue_session(conn,uid)
    response.set_cookie(COOKIE,token,max_age=43200,httponly=True,secure=True,samesite="strict",path="/")
    return {"status":"ok"}

@router.get("/me")
def me(request:Request,conn=Depends(db)):
    return current(conn,request)

@router.post("/logout")
def logout(request:Request,response:Response,conn=Depends(db)):
    check_origin(request)
    revoke_session(conn,request.cookies.get(COOKIE,""))
    response.delete_cookie(COOKIE,path="/",secure=True,httponly=True,samesite="strict")
    return {"status":"ok"}

def request_email(body,request,conn,send,action):
    check_origin(request)
    email=checked_email(body.email)
    guard(request,action,email)
    token={"verify_email":begin_signup,"reset_password":begin_reset,"activate_import":begin_activation}[action](conn,email)
    if token:
        send(email,token,action)
    return {"status":"accepted"}

@router.post("/signup",status_code=202)
def signup(body:EmailBody,request:Request,conn=Depends(db),send=Depends(sender)):
    return request_email(body,request,conn,send,"verify_email")

@router.post("/reset-request",status_code=202)
def reset_request(body:EmailBody,request:Request,conn=Depends(db),send=Depends(sender)):
    return request_email(body,request,conn,send,"reset_password")

@router.post("/activate-request",status_code=202)
def activate_request(body:EmailBody,request:Request,conn=Depends(db),send=Depends(sender)):
    return request_email(body,request,conn,send,"activate_import")

def complete(body,request,conn,action):
    check_origin(request)
    guard(request,"complete")
    try:
        ok=finish_activation(conn,body.token,body.password) if action=="activate_import" else finish_password(conn,body.token,body.password,action,body.name)
    except ValueError:
        ok=False
    if not ok:
        raise HTTPException(400,"Invalid or expired account link")
    return {"status":"ok"}

@router.post("/verify-email")
def verify_email(body:FinishBody,request:Request,conn=Depends(db)):
    return complete(body,request,conn,"verify_email")

@router.post("/reset-password")
def reset_password(body:FinishBody,request:Request,conn=Depends(db)):
    return complete(body,request,conn,"reset_password")

@router.post("/activate")
def activate(body:FinishBody,request:Request,conn=Depends(db)):
    return complete(body,request,conn,"activate_import")

@router.get("/preview",response_class=HTMLResponse)
def preview():
    return HTMLResponse(Path(__file__).with_name("native_auth_preview.html").read_text(),
        headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer",
                 "X-Frame-Options":"DENY","Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})

def test():
    uid,admin=uuid4(),uuid4()
    email="native-"+uid.hex+"@example.invalid"
    ae="admin-"+admin.hex+"@example.invalid"
    pw="Synthetic-only-native-2026!"
    with connect() as conn:
        try:
            for i,e,isadmin in ((uid,email,False),(admin,ae,True)):
                conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled,is_platform_admin) VALUES(%s,%s,now(),true,%s)",(i,e,isadmin))
            assert begin_activation(conn,email,lambda _:False) is None
            assert begin_activation(conn,ae,lambda _:True) is None
            token=begin_activation(conn,email,lambda i:i==uid)
            assert token and authenticate(conn,email,pw) is None
            assert not finish_activation(conn,token,pw,lambda _:False)
            assert finish_activation(conn,token,pw,lambda i:i==uid)
            assert not finish_activation(conn,token,pw,lambda _:True)
            assert authenticate(conn,email,pw)==uid
            session=issue_session(conn,uid)
            assert session_user(conn,session)[0]==uid
            reset=begin_reset(conn,email)
            assert finish_password(conn,reset,pw+"2","reset_password")
            assert session_user(conn,session) is None
            assert authenticate(conn,email,pw+"2")==uid
            fresh="signup-"+uid.hex+"@example.invalid"
            first=begin_signup(conn,fresh)
            second=begin_signup(conn,fresh)
            assert first and second and first!=second
            assert not finish_password(conn,first,pw,"verify_email")
            assert authenticate(conn,fresh,pw) is None
            assert finish_password(conn,second,pw,"verify_email","Synthetic user")
            assert authenticate(conn,fresh,pw) is not None
            assert not finish_password(conn,second,pw,"verify_email")
            assert begin_signup(conn,fresh) is None
            assert begin_activation(conn,fresh,lambda _:True) is None
        finally:
            conn.rollback()
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM myr_native.users WHERE id=ANY(%s)",([uid,admin],)).fetchone()[0]==0
    print("MYR_NATIVE_AUTH_ACTIVATION_ROLLBACK_OK")

if __name__=="__main__":
    test()
