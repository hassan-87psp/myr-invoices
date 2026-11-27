"""Read-only consolidated VPS launch preflight.
No provider login, invoice submission, email delivery, DB write, secret output,
or service restart. Configuration presence is not provider authorization.
"""
import hashlib,json,os,re,stat,subprocess
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
import ssl
import business_lhdn as lhdn

LIVE="4942c9562c5012c75ab75c10f116fefae039d48a"
def safe_flag(name):
    try:return lhdn.private_text(name).strip()==LIVE
    except Exception:return False
def config(environment):
    code,d=lhdn.bridge({"action":"configuration_status","environment":environment},timeout=12)
    ok=code==200 and d.get("ok") is True
    return {"reachable":ok,"configured":d.get("configured") is True if ok else None,
            "connection_check_enabled":d.get("connection_check_enabled") is True if ok else None,
            "submission_disabled":d.get("submission_enabled") is False if ok else None}
def mail_secret():
    try:return bool(lhdn.private_text("supabase-mail-api-secret").strip())
    except Exception:return False
def pilot_counts():
    d=lhdn.local_config().get("approved_pilots")
    if not isinstance(d,dict):return {"sandbox":0,"production":0}
    return {e:sum(isinstance(x,dict) and x.get("environment")==e for x in d.values()) for e in ("sandbox","production")}
def local_http(path,body=None):
    try:
        url="https://myrinvoice.com"+path
        req=Request(url,data=json.dumps(body).encode() if body is not None else None,
                    headers={"Origin":"https://myrinvoice.com","Content-Type":"application/json"})
        opener=build_opener(ProxyHandler({}),lhdn.NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        with opener.open(req,timeout=12) as r:
            r.read(8192)
            return r.status
    except HTTPError as e:return e.code
    except Exception:return None
def backup():
    try:
        folder=Path.home()/"myr-private-backups/native"
        archives=sorted((p for p in folder.glob("native-*.dump.gpg") if not p.is_symlink() and p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)
        if not archives:return {"present":False}
        p=archives[0];s=p.with_name(p.name+".sha256")
        if s.is_symlink() or not s.is_file() or p.stat().st_mode&0o077 or s.stat().st_mode&0o077:
            return {"present":True,"private_permissions":False}
        expected=s.read_text().strip().split("  ")
        with p.open("rb") as f:actual=hashlib.file_digest(f,"sha256").hexdigest()
        return {"present":True,"private_permissions":True,"checksum_ok":expected==[actual,p.name],
                "age_hours":round((datetime.now(timezone.utc).timestamp()-p.stat().st_mtime)/3600,2),
                "offsite_verified":False,"restore_verified":False}
    except Exception:return {"present":None,"check_failed":True}
def db_audit():
    # Only catalog metadata and role permissions; no business data is read.
    try:
        from app import connect
        with connect() as c:
            c.execute("SET TRANSACTION READ ONLY")
            name,user=c.execute("SELECT current_database(),current_user").fetchone()
            if (name,user)!=("myrinvoice","myrinvoice_app"):
                return {"identity_ok":False}
            r=c.execute("""SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls
                           FROM pg_roles WHERE rolname=current_user""").fetchone()
            tables=c.execute("""SELECT count(*) FROM pg_tables WHERE schemaname='myr_native'""").fetchone()[0]
            intent=c.execute("SELECT to_regclass('myr_native.lhdn_submission_intents') IS NOT NULL").fetchone()[0]
            return {"identity_ok":True,"native_table_count":tables,"superuser":r[0],
                    "create_database":r[1],"create_role":r[2],"bypass_rls":r[3],
                    "production_intent_table_present":intent}
    except Exception:return {"identity_ok":None,"check_failed":True}
def main():
    print(json.dumps({
       "checked_at":datetime.now(timezone.utc).isoformat(),
       "live_release_markers":{"writes":safe_flag("production-writes-enabled"),
                               "native_auth":safe_flag("native-auth-pilot-enabled")},
       "lhdn":{"sandbox":config("sandbox"),"production":config("production"),
               "configured_pilot_counts":pilot_counts(),
               "provider_login_verified":False,"provider_document_acceptance_verified":False},
       "email":{"private_bridge_secret_present":mail_secret(),"delivery_verified":False},
       "anonymous_http":{"homepage":local_http("/"),"admin":local_http("/api/myr/admin/dashboard"),
          "lhdn_connection":local_http("/api/myr/lhdn/connection",{"p_company_id":"00000000-0000-0000-0000-000000000001"})},
       "database":db_audit(),"backup":backup()
    },indent=2))
    print("MYR_LAUNCH_PREFLIGHT_READ_ONLY_DONE")
if __name__=="__main__":main()
