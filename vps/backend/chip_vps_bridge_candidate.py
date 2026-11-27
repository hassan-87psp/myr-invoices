"""Server-to-server CHIP bridge for the isolated billing release.
No browser credentials and no live payment operations. Never retries requests.
The operator token is read from a private VPS config file, not from requests.
"""
import json,re,ssl
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
from business_lhdn import private_text,NoRedirect

URL="https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-chip-sandbox-checkout"
def bridge(payload):
    secret=private_text("chip-operator-secret").strip()
    if not re.fullmatch(r"[a-f0-9]{64}",secret):raise ValueError("CHIP operator configuration unavailable")
    if not isinstance(payload,dict) or payload.get("action") not in ("create_reserved_test","verify_reserved_test"):
        raise ValueError("Invalid sandbox operation")
    req=Request(URL,data=json.dumps(payload).encode(),method="POST",headers={
        "X-Chip-Operator-Secret":secret,"Content-Type":"application/json","Accept":"application/json"})
    opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(req,timeout=25) as r:
            status=r.status;raw=r.read(8193)
    except HTTPError as e:
        status=e.code;raw=e.read(8193)
    if len(raw)>8192:raise ValueError("Unexpected bridge response")
    result=json.loads(raw)
    if status!=200 or not isinstance(result,dict) or result.get("ok") is not True:
        raise ValueError("Sandbox bridge request not verified")
    return result

def require_sandbox():
    # No runtime flag alone is sufficient to release this candidate.
    # Production migration and a reviewed provider-backed release are still required.
    from fastapi import HTTPException
    raise HTTPException(503,"Sandbox checkout not released")
