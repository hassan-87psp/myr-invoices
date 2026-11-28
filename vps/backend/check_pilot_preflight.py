"""Operator-only read-only preflight. No tax identity, credentials, customer records,
provider login, submissions, deployment or DB writes. Run on VPS as myradmin.
This checks connection-test prerequisites, not invoice-dispatch release readiness."""
import hashlib,json,os,sys
from pathlib import Path
from unittest.mock import patch
import business_lhdn as lhdn
import frontend_autodeploy as deploy
import check_private_reliability as reliability

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/"vps/approved-frontend-releases.json"
MARKERS=("myrStComboPick","myrSideSetup","myrObSubmit","myr-mobile-reveal")

def release_status(manifest,applied,html,live):
    releases=manifest["releases"]
    expected={r["id"]:hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest() for r in releases}
    missing=[k for k in expected if k not in applied]
    changed=[k for k,v in applied.items() if expected.get(k)!=v]
    return {"expected_releases":len(expected),"applied_releases":len(applied),
            "missing_release_ids":missing,"changed_release_ids":changed,
            "live_matches_webroot":html==live,
            "latest_ui_markers":all(x.encode() in live for x in MARKERS),
            "status":"verified" if not missing and not changed and html==live and all(x.encode() in live for x in MARKERS) else "review_required"}

def frontend_status():
    try:
        manifest=json.loads(MANIFEST.read_text())
        applied=json.loads(reliability.read_private(deploy.S/"applied.json",500000))
        if not isinstance(applied,dict):raise ValueError("state type")
        previous=(deploy.B/"current").resolve(strict=True)
        if previous.parent!=deploy.B/"releases":raise ValueError("webroot")
        html=(previous/"index.html").read_bytes()
        live=deploy.curl("/","-fsS")
        result=release_status(manifest,applied,html,live)
        result["timer_active"]=reliability.unit("myr-frontend-autodeploy.timer")
        result["failed_current_manifest"]=False
        failed=deploy.S/"failed-manifest"
        if failed.exists():
            result["failed_current_manifest"]=reliability.read_private(failed,128).strip()==hashlib.sha256(MANIFEST.read_bytes()).hexdigest().encode()
        if not result["timer_active"] or result["failed_current_manifest"]:result["status"]="review_required"
        return result
    except Exception:
        return {"status":"unavailable","timer_active":reliability.unit("myr-frontend-autodeploy.timer")}

def guarded_health():
    try:
        deploy.health()
        return True
    except Exception:return False

def config_status():
    # configuration_status only. Does NOT authenticate as a taxpayer or call submit.
    safe={}
    for environment in ("sandbox","production"):
        code,d=lhdn.bridge({"action":"configuration_status","environment":environment})
        ok=code==200 and d.get("ok") is True
        safe[environment]={"bridge_reachable":ok,"credentials_configured":ok and d.get("configured") is True,
                           "connection_check_enabled":ok and d.get("connection_check_enabled") is True,
                           "submission_explicitly_disabled":ok and d.get("submission_enabled") is False}
    return safe

def count_approved_pilots():
    d=lhdn.local_config().get("approved_pilots")
    if not isinstance(d,dict):return 0
    return sum(1 for k,v in d.items() if isinstance(v,dict) and v.get("environment")=="sandbox" and
               lhdn.approved_target(k,v.get("tin"),v.get("brn"),"sandbox"))

def evaluate(front,health,configs,backup,pilots):
    sandbox=configs["sandbox"];prod=configs["production"]
    checks={"frontend_release_verified":front.get("status")=="verified",
            "core_and_auth_guards_verified":health is True,
            "encrypted_backup_checksum_verified":backup.get("status")=="verified_checksum",
            "sandbox_bridge_configured":all(sandbox.get(x) is True for x in ("bridge_reachable","credentials_configured","connection_check_enabled","submission_explicitly_disabled")),
            "production_connection_and_submission_disabled":prod.get("bridge_reachable") is True and prod.get("connection_check_enabled") is False and prod.get("submission_explicitly_disabled") is True}
    return {"checks":checks,"connection_test_prerequisites_met":all(checks.values()),"approved_sandbox_pilots":pilots,
            "operator_approval_still_required":pilots==0,"actual_provider_login_verified":False,
            "actual_tin_verified":False,"sandbox_dispatch_ready":False,"production_submission_ready":False,
            "offsite_restore_verified_by_this_check":False}

def selftest():
    manifest={"releases":[{"id":"test","replacements":[{"old":"a","new":"b"}]}]}
    expected=hashlib.sha256(json.dumps(manifest["releases"][0],sort_keys=True).encode()).hexdigest()
    live=" ".join(MARKERS).encode()
    assert release_status(manifest,{"test":expected},live,live)["status"]=="verified"
    assert release_status(manifest,{},live,live)["status"]=="review_required"
    assert release_status(manifest,{"test":"wrong"},live,live)["status"]=="review_required"
    assert release_status(manifest,{"test":expected},live,b"old")["status"]=="review_required"
    assert release_status(manifest,{"test":expected},b"old",b"old")["status"]=="review_required"
    with patch.object(lhdn,"bridge",side_effect=[(200,{"ok":True,"configured":True,"connection_check_enabled":True,"submission_enabled":False}),(200,{"ok":True,"configured":True,"connection_check_enabled":False,"submission_enabled":False})]) as call:
        cfg=config_status()
        assert [x.args[0] for x in call.call_args_list]==[{"action":"configuration_status","environment":"sandbox"},{"action":"configuration_status","environment":"production"}]
    ready=evaluate({"status":"verified"},True,cfg,{"status":"verified_checksum"},0)
    assert ready["connection_test_prerequisites_met"] and ready["operator_approval_still_required"]
    assert not ready["actual_provider_login_verified"] and not ready["sandbox_dispatch_ready"] and not ready["production_submission_ready"]
    cfg["production"]["connection_check_enabled"]=True
    assert not evaluate({"status":"verified"},True,cfg,{"status":"verified_checksum"},1)["connection_test_prerequisites_met"]
    with patch.object(lhdn,"local_config",return_value={"approved_pilots":{"fake":{"environment":"sandbox","tin":"C123","brn":"123","identity_type":"TIN"},"bad":{"environment":"production","tin":"C123","brn":"123","identity_type":"TIN"}}}):
        assert count_approved_pilots()==1
    print("MYR_PILOT_PREFLIGHT_OFFLINE_OK",flush=True)

def main():
    if os.getuid()==0:raise SystemExit("Run as the unprivileged MYR VPS operator.")
    front=frontend_status()
    health=guarded_health()
    configs=config_status()
    backup=reliability.inspect_backups(reliability.B,reliability.time.time())
    pilots=count_approved_pilots()
    result=evaluate(front,health,configs,backup,pilots)
    print(json.dumps({"frontend":front,"configuration":configs,"backup":backup,"readiness":result},indent=2))
    return 0 if result["connection_test_prerequisites_met"] else 1

if __name__=="__main__":
    if sys.argv[1:]==["--selftest"]:selftest()
    elif not sys.argv[1:]:raise SystemExit(main())
    else:raise SystemExit("Usage: check_pilot_preflight.py [--selftest]")
