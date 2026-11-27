"""Assemble an isolated billing release from the active production frontend and pinned backend.
This is an executable build rehearsal, not a production installer. No database DDL,
systemd changes, nginx changes, external requests, or deployment marker updates.
"""
import os,re,subprocess,tempfile,shutil,sys
from pathlib import Path
from build_chip_billing_candidate import transform

PIN="4942c9562c5012c75ab75c10f116fefae039d48a"
ROOT=Path(__file__).resolve().parents[2]
HOME=Path.home()
CANDIDATES=("billing_ledger_candidate.py","billing_api_candidate.py",
 "chip_billing_view_candidate.py","chip_test_lifecycle_candidate.py",
 "chip_checkout_orchestration_candidate.py","chip_billing_integration_candidate.py",
 "chip_vps_bridge_candidate.py","chip_subscription_policy_candidate.py")
MOUNT="""
from chip_billing_integration_candidate import build_router as chip_billing_router
from chip_vps_bridge_candidate import bridge as chip_bridge, require_sandbox
api.include_router(chip_billing_router(db,identity,owner_company,admin_identity,require_sandbox,chip_bridge))
"""
def main():
    os.umask(0o077)
    for marker in ("production-writes-enabled","native-auth-pilot-enabled"):
        assert (HOME/".config/myrinvoice"/marker).read_text().strip()==PIN,"Unexpected production release"
    current=Path("/var/www/myrinvoice.com/auto/current").resolve(strict=True)
    assert current.parent==Path("/var/www/myrinvoice.com/auto/releases"),"Unexpected public root"
    raw=(current/"index.html").read_text()
    assert "function myrAuthHeaders(" in raw,"Native frontend auth helper missing"
    html=transform(raw)
    for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
        if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
            subprocess.run(["node","--check","-"],input=code,text=True,check=True)
    folder=HOME/"myr-staging"
    folder.mkdir(mode=0o700,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="billing-release-",dir=folder) as d:
        stage=Path(d)
        with subprocess.Popen(["git","-C",str(ROOT),"archive",PIN,"vps/backend"],stdout=subprocess.PIPE) as p:
            subprocess.run(["tar","-xf","-","-C",str(stage)],stdin=p.stdout,check=True)
            p.stdout.close()
            assert p.wait()==0
        backend=stage/"vps/backend"
        for name in CANDIDATES:shutil.copy2(ROOT/"vps/backend"/name,backend/name)
        api=backend/"business_api.py"
        text=api.read_text()
        anchor="# Keep the candidate on the private loopback service only."
        assert text.count(anchor)==1
        api.write_text(text.replace(anchor,MOUNT+"\n"+anchor,1))
        (stage/"index.html").write_text(html)
        expected={"GET /billing/customer/{company_id}","GET /billing/admin/sandbox",
          "POST /billing/admin/sandbox/checkout","POST /billing/admin/sandbox/verify"}
        code="""from business_api import api
from chip_vps_bridge_candidate import require_sandbox
from fastapi import HTTPException
actual={m+' '+r.path for r in api.routes if r.path.startswith('/billing/') for m in r.methods}
assert actual=="""+repr(expected)+"""
try:require_sandbox()
except HTTPException as e:assert e.status_code==503
else:raise AssertionError('Sandbox unexpectedly enabled')
print('MYR_BILLING_ROUTER_MOUNT_OK')
"""
        env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1","MYR_CANDIDATE_DIR":str(stage/"unused")}
        env.pop("MYR_PRODUCTION_RELEASE",None)
        env.pop("PYTHONPATH",None)
        subprocess.run([sys.executable,"-B","-c",code],cwd=backend,env=env,check=True)
        print("MYR_PINNED_BILLING_RELEASE_BUILD_OK")
        print("Existing native authentication preserved; sandbox gate closed. No public assets or production services modified.")
if __name__=="__main__":main()
