"""Connection-only central LHDN pilot. Never submits documents."""
import json, os, re, ssl, stat, time, fcntl
from pathlib import Path
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
CONFIG=Path.home()/".config/myrinvoice"
URL="https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-lhdn-intermediary"
TIN=re.compile(r"[A-Z]{1,3}[0-9]{1,20}")
BRN=re.compile(r"[A-Z0-9-]{1,40}")
def private_text(name):
    fd=os.open(CONFIG/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"r") as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError("Unsafe configuration")
        text=f.read(65537)
        if len(text)>65536:raise ValueError("Configuration too large")
        return text
def local_config():
    try:
        d=json.loads(private_text("lhdn-intermediary-profile.json"))
        return d if isinstance(d,dict) else {}
    except (OSError,ValueError,TypeError):return {}
def public_identity():
    d=local_config()
    if d.get("publish_identity") is not True:return None
    name,tin,brn=(d.get(k) for k in ("name","tin","brn"))
    if not all(isinstance(v,str) for v in (name,tin,brn)) or not name.strip() or len(name)>200 or not TIN.fullmatch(tin) or not BRN.fullmatch(brn):return None
    return {"name":name,"tin":tin,"brn":brn}
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def bridge(payload,timeout=6):
    try:
        key=private_text("lhdn-bridge-secret").strip()
        if not re.fullmatch(r"[a-f0-9]{64}",key):raise ValueError("Invalid key")
        req=Request(URL,data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"},method="POST")
        opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(req,timeout=timeout) as res:code=res.status;d=json.loads(res.read(8192))
        except HTTPError as exc:code=exc.code;d=json.loads(exc.read(8192))
        if not isinstance(d,dict):raise ValueError("Invalid response")
        return code,d
    except (OSError,URLError,ValueError,TypeError):return 503,{"ok":False,"code":"bridge_unavailable"}
def configuration_status():
    code,d=bridge({"action":"configuration_status","environment":"production"})
    ok=code==200 and d.get("ok") is True
    return {"mode":"central_intermediary","environment":"production","bridge_reachable":ok,"credentials_configured":d.get("configured") is True if ok else None,"connection_check_enabled":d.get("connection_check_enabled") is True if ok else False,"intermediary_registration":"owner_confirmed","provider_login_verified":False,"submission_enabled":False}
def customer_context():
    return {"mode":"central_intermediary","environment":"production","intermediary":public_identity(),"submission_enabled":False,"pilot_only":True}
def approved_target(cid,tin,brn,environment):
    bindings=local_config().get("approved_pilots")
    if not isinstance(bindings,dict):return None
    b=bindings.get(str(cid))
    if not isinstance(b,dict) or b.get("environment")!=environment or b.get("tin")!=tin or b.get("brn")!=brn:return None
    if not isinstance(tin,str) or not TIN.fullmatch(tin) or not isinstance(brn,str) or not BRN.fullmatch(brn):return None
    if b.get("identity_type") not in ("TIN","ROB"):return None
    return tin+":"+brn if b["identity_type"]=="ROB" else tin
def claim_slot():
    try:
        fd=os.open(CONFIG/"lhdn-pilot-throttle",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        with os.fdopen(fd,"r+") as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:return False
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            old=f.read(100).strip()
            now=time.time()
            if old and now-float(old)<20:return False
            f.seek(0);f.truncate();f.write(str(now));f.flush();os.fsync(f.fileno())
            return True
    except (OSError,ValueError):return False
def check_connection(cid,tin,brn,environment="production"):
    if environment not in ("production","sandbox"):return {"status":"invalid_environment"}
    target=approved_target(cid,tin,brn,environment)
    if not target:return {"status":"review_required","submission_enabled":False}
    if not claim_slot():return {"status":"retry_later","submission_enabled":False}
    code,d=bridge({"action":"check_connection","environment":environment,"tenant_id":str(cid),"taxpayer":target},timeout=25)
    if code==200 and d.get("ok") is True and d.get("verification") in ("provider_login","cached"):
        ttl=d.get("expires_in")
        return {"status":"login_verified" if d["verification"]=="provider_login" else "cached_login","expires_in":ttl if type(ttl) is int and 0<ttl<=86400 else None,"submission_enabled":False}
    safe={"connection_check_disabled","authorization_or_credentials_rejected","rate_limited","bridge_unavailable","provider_unavailable","invalid_provider_response"}
    reason=d.get("code")
    return {"status":reason if isinstance(reason,str) and reason in safe else "connection_unavailable","submission_enabled":False}
def sandbox_configuration_status():
    """Private, read-only readiness probe. No taxpayer information is sent."""
    code,d=bridge({"action":"configuration_status","environment":"sandbox"})
    ok=code==200 and d.get("ok") is True
    return {"environment":"sandbox","bridge_reachable":ok,
        "credentials_configured":d.get("configured") is True if ok else None,
        "connection_check_enabled":d.get("connection_check_enabled") is True if ok else False,
        "submission_enabled":False}

def validate_sandbox_identity(cid,tin,brn):
    """Private operator helper, not exposed as an HTTP route.
    Caller must obtain current owner authorization and identity from server DB.
    Only the matching operator-approved sandbox pilot can be tested.
    """
    target=approved_target(cid,tin,brn,"sandbox")
    if not target:
        return {"status":"review_required","submission_enabled":False}
    if not claim_slot():
        return {"status":"retry_later","submission_enabled":False}
    code,d=bridge({"action":"validate_self_tin","environment":"sandbox","tenant_id":str(cid),
        "taxpayer":target,"brn":brn},timeout=40)
    if code==200 and d.get("ok") is True and d.get("verification") in ("provider_tin","cached_tin"):
        return {"status":"tin_verified" if d["verification"]=="provider_tin" else "cached_tin",
                "submission_enabled":False}
    allowed={"tin_validation_disabled","connection_check_disabled","authorization_or_credentials_rejected",
        "rate_limited","bridge_unavailable","provider_unavailable","invalid_provider_response",
        "invalid_input","permission_denied","identity_not_matched","authentication_required"}
    reason=d.get("code")
    return {"status":reason if isinstance(reason,str) and reason in allowed else "connection_unavailable",
            "submission_enabled":False}

if __name__=="__main__":print(json.dumps(configuration_status(),indent=2))
