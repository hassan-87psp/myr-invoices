"""Secret-free GitHub release gate. Does not connect to VPS, database or providers."""
import ast, json, re, subprocess, sys, hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def run(*args,**kwargs):
    subprocess.run([str(a) for a in args],cwd=ROOT,check=True,timeout=120,**kwargs)

def manifest_check():
    path=ROOT/"vps/approved-frontend-releases.json"
    m=json.loads(path.read_text())
    assert set(m)=={"version","releases"} and m["version"]==1
    assert isinstance(m["releases"],list) and len(m["releases"])<=100
    seen=set()
    for r in m["releases"]:
        assert set(r)=={"id","replacements"} and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}",r["id"])
        assert r["id"] not in seen
        seen.add(r["id"])
        assert 0<len(r["replacements"])<=50
        for p in r["replacements"]:
            assert set(p)=={"old","new"} and all(isinstance(v,str) and v for v in p.values())
            assert p["old"]!=p["new"] and len(p["old"])<=100000 and len(p["new"])<=150000
    print("MYR_APPROVED_MANIFEST_VALID",flush=True)

def main():
    for p in sorted((ROOT/"vps/backend").rglob("*.py")):
        ast.parse(p.read_text(),filename=str(p))
    print("MYR_BACKEND_SYNTAX_OK",flush=True)
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",(ROOT/"index.html").read_text(),re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            run("node","--check","-",input=code,text=True)
    for p in sorted((ROOT/"vps").glob("*.sh")):
        run("bash","-n",p)
    manifest_check()
    run(sys.executable,"-B",ROOT/"vps/check_legacy_deployment_guard.py")
    run(sys.executable,"-B",ROOT/"vps/check_validation_redaction.py")
    run(sys.executable,"-B",ROOT/"vps/check_public_seo.py")
    run(sys.executable,"-B",ROOT/"vps/backend/check_private_reliability.py","--selftest")
    run("node",ROOT/"vps/check_account_link_scope.mjs")
    run("node",ROOT/"vps/check_invoice_rounding.mjs")
    run("node",ROOT/"vps/check_mobile_suggestions.mjs")
    # Explicit offline-only tests. No dynamic discovery or database-dependent test execution.
    for name in ("chip_subscription_policy_candidate.py","chip_billing_view_candidate.py","chip_revenue_report_candidate.py",
                 "lhdn_protocol_candidate.py","lhdn_ubl_candidate.py","lhdn_saved_invoice_candidate.py",
                 "lhdn_lifecycle_candidate.py","lhdn_readiness_candidate.py"):
        run(sys.executable,"-B",ROOT/"vps/backend"/name)
    print("MYR_OFFLINE_RELEASE_GATE_OK",flush=True)
if __name__=="__main__":main()
