"""Read-only operator diagnostic. No session, credential, identity or provider calls.
Only requests deliberately rejected before the candidate reads a body or DB.
"""
import json,subprocess
import frontend_autodeploy as frontend

def classify(status):
    return {401:"native_auth_guard_present",404:"backend_route_missing",405:"route_method_unavailable",403:"origin_or_proxy_rejected",503:"service_unavailable"}.get(status,"review_required")

def probe(public):
    args=["-sS","-o","/dev/null","-w","%{http_code}","-X","POST","-H","Origin: https://myrinvoice.com","-H","Content-Type: application/json","--data","{}"]
    try:
        raw=frontend.curl("/api/myr/lhdn/direct-pilot",*args) if public else frontend.output("curl","--noproxy","*","--max-time","5",*args,"http://127.0.0.1:8769/lhdn/direct-pilot")
        code=int(raw)
        return {"http_status":code,"status":classify(code)}
    except (OSError,ValueError,subprocess.SubprocessError):return {"http_status":None,"status":"unreachable"}

def main():
    loop=probe(False);public=probe(True)
    service=frontend.active("myr-direct-erp-guard.service")
    print(json.dumps({"backend":loop,"public_proxy":public,"guard_service_active":service,
        "route_guard_verified":service and loop["http_status"]==401 and public["http_status"]==401,
        "credential_entry_approved":False,"issuer_identity_verified":False,
        "submission_verified":False,
        "note":"Separate guard-only sidecar on loopback 8769. Does not establish vault, owner approval or provider readiness."},indent=2))
if __name__=="__main__":main()
