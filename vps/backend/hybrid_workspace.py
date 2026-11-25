"""Private hybrid read-only workspace. Supabase verifies identity, VPS authorizes records.
No live Supabase data writes, no automatic account linking, no LHDN calls.
"""
import base64
import json
import re
from pathlib import Path
from urllib.request import Request as URLRequest, urlopen, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError
from uuid import UUID
from fastapi import Depends, HTTPException, Request
from psycopg.rows import dict_row
from staging_api import api, db, bearer

PROJECT="nynghaleoaqilewmhbdi"
ORIGIN="https://"+PROJECT+".supabase.co"
APP_ROOT=Path(__file__).resolve().parents[2]
GRANT=Path.home()/".config/myrinvoice/hybrid-read-user"

def config():
    source=(APP_ROOT/"config.js").read_text()
    found=re.search(r"supabaseAnonKey\s*:\s*['\"]([^'\"]+)['\"]",source)
    if not found:
        raise RuntimeError("Publishable configuration missing")
    key=found[1]
    if not key.startswith("sb_publishable_"):
        try:
            p=key.split(".")[1]
            claims=json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4)))
            if claims.get("role")!="anon" or claims.get("ref") not in (None,PROJECT):
                raise ValueError()
        except Exception:
            raise RuntimeError("Expected public anon key") from None
    return key

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def verify_user(token):
    if not 40<=len(token)<=8192 or not re.fullmatch(r"[A-Za-z0-9_.-]+",token):
        raise HTTPException(401,"Invalid access token")
    req=URLRequest(ORIGIN+"/auth/v1/user",
        headers={"apikey":config(),"Authorization":"Bearer "+token,"Accept":"application/json"})
    try:
        with build_opener(NoRedirect()).open(req,timeout=10) as response:
            info=json.loads(response.read(65536))
    except HTTPError as e:
        raise HTTPException(401 if e.code in (400,401,403) else 503,"Auth verification unavailable or rejected") from None
    except (URLError,TimeoutError,ValueError,OSError):
        raise HTTPException(503,"Supabase Auth verification unavailable") from None
    try:
        uid=UUID(info["id"])
        email=info["email"].strip().lower()
        if not info.get("email_confirmed_at") or info.get("is_anonymous") or not email:
            raise ValueError()
        return uid,email
    except (KeyError,TypeError,ValueError,AttributeError):
        raise HTTPException(403,"Verified email account required") from None

def workspace(conn,uid,email):
    # Separate explicit operator grant; imported native password login remains disabled.
    # The disabled column governs native password auth, not verified Supabase access.
    # Remove the grant file to revoke hybrid preview access.
    if not GRANT.is_file():
        raise HTTPException(403,"Hybrid staging access has not been authorized")
    try:
        allowed=UUID(GRANT.read_text().strip())
    except (OSError,ValueError):
        raise HTTPException(403,"Invalid staging access grant") from None
    if uid!=allowed:
        raise HTTPException(403,"Account is not approved for this private preview")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""SELECT id,email,name FROM myr_native.users
            WHERE id=%s AND email=%s AND email_verified_at IS NOT NULL AND NOT is_platform_admin""",(uid,email))
        profile=cur.fetchone()
        if not profile:
            raise HTTPException(403,"Imported identity does not match")
        cur.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.version,c.data,c.created_at
            FROM myr_native.companies c JOIN myr_native.company_members m ON m.company_id=c.id
            WHERE m.email=%s AND m.status='active' AND m.role='Owner' AND c.status='active' AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' ORDER BY c.created_at""",(email,))
        companies=cur.fetchall()
        ids=[c["id"] for c in companies]
        if not ids:
            raise HTTPException(403,"No imported owner workspace")
        cur.execute("""SELECT company_id,email,name,'Read-Only' AS role,status,created_at
            FROM myr_native.company_members WHERE email=%s AND company_id=ANY(%s) AND status='active'""",(email,ids))
        members=cur.fetchall()
        cur.execute("""SELECT company_id,invoice_id,environment,code_number,submission_uid,uuid,long_id,status,validated_at,errors,accepted_at,updated_at
            FROM myr_native.lhdn_documents WHERE company_id=ANY(%s)""",(ids,))
        docs=cur.fetchall()
    return {"profile":{**profile,"is_platform_admin":False},"companies":companies,
            "members":members,"documents":docs,"links":[],"mode":"read_only"}

@api.get("/hybrid/workspace")
def read_workspace(request:Request,conn=Depends(db)):
    uid,email=verify_user(bearer(request))
    conn.execute("SET TRANSACTION READ ONLY")
    return workspace(conn,uid,email)
