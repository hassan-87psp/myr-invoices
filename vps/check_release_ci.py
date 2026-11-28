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

def sandbox_admin_check():
    # Extract the real route body without importing the production DB/auth stack.
    from types import SimpleNamespace
    from unittest.mock import Mock
    tree=ast.parse((ROOT/"vps/backend/business_api.py").read_text())
    route=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="admin_dashboard")
    route.decorator_list=[]
    route.args.defaults=[]
    for arg in route.args.args:
        arg.annotation=None
    conn=Mock()
    auth=Mock(side_effect=PermissionError("admin required"))
    dashboard=Mock(return_value={})
    production=Mock(return_value={"environment":"production","submission_enabled":False})
    sandbox=Mock(return_value={"environment":"sandbox","credentials_configured":True,
                               "connection_check_enabled":True,"submission_enabled":False})
    scope=dict(admin_identity=auth,dashboard=dashboard,
               central_lhdn=SimpleNamespace(configuration_status=production,
                                             sandbox_configuration_status=sandbox))
    exec(compile(ast.Module(body=[route],type_ignores=[]),"<isolated-route>","exec"),scope)
    try:
        scope["admin_dashboard"](object(),conn)
    except PermissionError:
        pass
    else:
        raise AssertionError("Non-admin route should fail")
    production.assert_not_called()
    sandbox.assert_not_called()
    dashboard.assert_not_called()
    auth.side_effect=None
    auth.return_value={"is_platform_admin":True}
    result=scope["admin_dashboard"](object(),conn)["central_lhdn"]
    assert result["environment"]=="production" and result["submission_enabled"] is False
    assert result["sandbox"]["environment"]=="sandbox" and result["sandbox"]["submission_enabled"] is False
    production.assert_called_once_with()
    sandbox.assert_called_once_with()
    # Execute the actual private frontend JS in Node with safe presentation stubs.
    t=ast.parse((ROOT/"vps/backend/build_lhdn_candidate.py").read_text())
    js=next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign)
            and any(isinstance(x,ast.Name) and x.id=="JS" for x in n.targets))
    run("node","--check","-",input=js,text=True)
    run("node","-",input="const ic=()=>''; const esc=String;\n"+js+r"""
const absent=myrCentralAdmin({});
const ready=myrCentralAdmin({central_lhdn:{bridge_reachable:true,connection_check_enabled:false,
 sandbox:{bridge_reachable:true,credentials_configured:true,connection_check_enabled:true}}});
if(!absent.includes('Sandbox testing readiness') || !absent.includes('Unknown')) throw Error('Missing safe fallback');
if(!ready.includes('Not verified by configuration check') || !ready.includes('Invoice submission') ||
 !ready.includes('No documents will be submitted.') || !ready.includes('<dd>Configured</dd>') ||
 !ready.includes('<dd>Enabled</dd>') || !ready.includes('<dd>Disabled</dd>')) throw Error('Readiness rendering incorrect');
""",text=True)
    print("MYR_SANDBOX_ADMIN_READINESS_OK",flush=True)

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
    sandbox_admin_check()
    run(sys.executable,"-B",ROOT/"vps/check_legacy_deployment_guard.py")
    run(sys.executable,"-B",ROOT/"vps/check_validation_redaction.py")
    run(sys.executable,"-B",ROOT/"vps/check_security_regression.py")
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
