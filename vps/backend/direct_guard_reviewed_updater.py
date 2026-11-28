"""Reviewed-release updater candidate for the guard-only Direct ERP service.

Local approval is an exact immutable Git commit, NOT a mutable remote branch.
No root access, core restart, frontend, Nginx, schema, vault or grant changes.
Install/run only after operator review. --rehearse makes no live changes.
"""
import fcntl, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

HOME=Path.home()
REPO=HOME/"myr-invoices"
CONFIG=HOME/".config/myrinvoice"
PIN="4942c9562c5012c75ab75c10f116fefae039d48a"
INITIAL="df90fe9fbb91ecab55a78c1bcb2793eff84c131b"
CORE=HOME/"myr-backend-releases/production"/PIN/"vps/backend"
RELEASES=HOME/"myr-backend-releases/direct-erp-guard"
SERVICE="myr-direct-erp-guard.service"
DROP=HOME/".config/systemd/user"/(SERVICE+".d")/"40-reviewed-release.conf"
STATE=CONFIG/"direct-erp-update-in-progress"
APPROVAL=CONFIG/"direct-erp-guard-approved-commit"
PY=HOME/"myr-venv/bin/python"
WEB=Path("/var/www/myrinvoice.com/auto")
FILES=("lhdn_direct_sidecar_candidate.py","lhdn_direct_pilot_candidate.py",
       "lhdn_direct_vault_candidate.py","lhdn_direct_candidate.py","lhdn_protocol_candidate.py")
ROUTE="/api/myr/lhdn/direct-pilot"

def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def run(*args,**kw):
    return subprocess.run([str(a) for a in args],check=True,timeout=90,**kw)
def out(*args):
    return run(*args,stdout=subprocess.PIPE).stdout
def system(*args):
    return run("systemctl","--user",*args)
def active(unit):
    return subprocess.run(["systemctl","--user","is-active","--quiet",unit],timeout=10).returncode==0
def private(path):
    st=path.lstat()
    require(path.is_file() and not path.is_symlink() and st.st_uid==os.getuid() and not(st.st_mode&0o077),"Unsafe private file")
    return path.read_text().strip()
def atomic(path,content):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        tmp=Path(f.name)
        try:
            f.write(content);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
def http(path,local=False,post=False,origin="https://myrinvoice.com"):
    a=["curl","--noproxy","*","--max-time","5","-sS","-o","/dev/null","-w","%{http_code}"]
    if not local:a+=["--resolve","myrinvoice.com:443:127.0.0.1"]
    if post:a+=["-X","POST","-H","Content-Type: application/json","-H","Origin: "+origin,"--data","{}"]
    return out(*a,("http://127.0.0.1:8769" if local else "https://myrinvoice.com")+path).decode()
def baseline():
    require(os.getuid()!=0 and out("id","-un").strip()==b"myradmin","Run as myradmin")
    for name in ("production-writes-enabled","native-auth-pilot-enabled"):
        require(private(CONFIG/name)==PIN,"Core release pin changed")
    require(not (CONFIG/"direct-erp-pilot.json").exists() and not (CONFIG/"direct-erp-pilot.json").is_symlink(),"Active grant requires separate release review")
    require(not STATE.exists() and not STATE.is_symlink(),"Previous update incomplete; recovery review required")
    for unit in (SERVICE,"myr-production-core.service","myr-billing-readonly.service"):
        require(active(unit),"Required service inactive: "+unit)
    health()
def health():
    d=json.loads(out("curl","--noproxy","*","--max-time","5","-fsS","http://127.0.0.1:8767/health"))
    require(d.get("database")=="vps" and d.get("writes_enabled") is True,"Core health failed")
    for p in ("/api/myr/workspace","/api/myr/native/auth/me",
              "/api/myr/billing/customer?company_id=00000000-0000-0000-0000-000000000000",
              "/api/myr/billing/admin/sandbox"):
        require(http(p)=="401","Existing auth guard changed")
    require(http("/api/myr/billing/admin/sandbox/checkout")=="404","Billing checkout gate changed")
    require(http("/lhdn/direct-pilot",local=True,post=True)=="401","Local Direct guard failed")
    require(http(ROUTE,post=True)=="401","Public Direct guard failed")
    require(http(ROUTE,post=True,origin="https://invalid.example")=="403","Public origin guard failed")
    require(http("/workspace",local=True)=="404","Unexpected sidecar route")
def current():
    p=Path(out("systemctl","--user","show",SERVICE,"-p","WorkingDirectory","--value").decode().strip())
    require(p.parent==RELEASES and not p.is_symlink() and p.is_dir() and re.fullmatch("[a-f0-9]{40}",p.name),"Unexpected active release path")
    return p
def validate_commit(commit):
    require(re.fullmatch("[a-f0-9]{40}",commit) is not None,"Exact commit SHA required")
    require(out("git","-C",REPO,"rev-parse",commit+"^{commit}").decode().strip()==commit,"Commit unavailable")
    run("git","-C",REPO,"merge-base","--is-ancestor",INITIAL,commit)
def assemble(commit,folder):
    validate_commit(commit)
    for name in FILES:
        raw=out("git","-C",REPO,"show",commit+":vps/backend/"+name)
        require(len(raw)<256000,"Oversized source")
        (folder/name).write_bytes(raw)
    text=(folder/FILES[0]).read_text()
    require("return pilot.unavailable()  # Hard-disabled:" in text and "return pilot.handle(" not in text,"Guard-only scope changed")
    env={**os.environ,"PYTHONPATH":str(folder)+":"+str(CORE),"MYR_PRODUCTION_RELEASE":PIN}
    run(PY,"-B",folder/FILES[0],env=env)
def verify_folder(folder,commit):
    require(not folder.is_symlink() and folder.is_dir(),"Unsafe release directory")
    for name in FILES:
        p=folder/name
        require(p.is_file() and not p.is_symlink() and p.read_bytes()==out("git","-C",REPO,"show",commit+":vps/backend/"+name),"Release content mismatch")
def wait_health():
    for _ in range(15):
        try:
            health();return
        except (RuntimeError,OSError,subprocess.SubprocessError):time.sleep(1)
    raise RuntimeError("Post-restart health failed")
def deploy(commit):
    old=current()
    validate_commit(commit)
    if old.name==commit:
        verify_folder(old,commit)
        print("MYR_DIRECT_APPROVED_RELEASE_CURRENT",flush=True);return
    run("git","-C",REPO,"merge-base","--is-ancestor",old.name,commit)
    target=RELEASES/commit
    if target.exists() or target.is_symlink():
        verify_folder(target,commit)
    else:
        with tempfile.TemporaryDirectory(dir=RELEASES,prefix=".reviewed-") as d:
            stage=Path(d)/"release";stage.mkdir(mode=0o700)
            assemble(commit,stage)
            os.rename(stage,target)
    # Re-run guard tests even if a previously staged target exists.
    with tempfile.TemporaryDirectory(dir=RELEASES,prefix=".verify-") as d:
        assemble(commit,Path(d))
    require(not DROP.is_symlink(),"Unsafe service override")
    previous=DROP.read_bytes() if DROP.exists() else None
    STATE.mkdir(mode=0o700)
    (STATE/"previous-release").write_text(str(old)+"\n")
    (STATE/"target-release").write_text(str(target)+"\n")
    if previous is not None:(STATE/"previous-dropin").write_bytes(previous)
    try:
        DROP.parent.mkdir(parents=True,exist_ok=True)
        atomic(DROP,("[Service]\nWorkingDirectory="+str(target)+"\n").encode())
        system("daemon-reload")
        system("restart",SERVICE)
        require(current()==target,"Service did not select reviewed release")
        wait_health()
        for p in STATE.iterdir():p.unlink()
        STATE.rmdir()
        print("MYR_DIRECT_APPROVED_RELEASE_DEPLOYED",flush=True)
    except BaseException:
        if previous is None:DROP.unlink(missing_ok=True)
        else:atomic(DROP,previous)
        system("daemon-reload")
        system("restart",SERVICE)
        require(current()==old,"Manual service recovery required")
        wait_health()
        (STATE/"status").write_text("rolled-back-review-required\n")
        print("MYR_DIRECT_APPROVED_RELEASE_ROLLED_BACK",flush=True)
        raise
def main():
    os.umask(0o077)
    args=sys.argv[1:]
    require(args==["--rehearse"] or args==["--run"],"Use --rehearse or --run")
    with (WEB/"deploy.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        baseline()
        if args==["--rehearse"]:
            old=current();verify_folder(old,old.name)
            with tempfile.TemporaryDirectory(dir=RELEASES,prefix=".dry-run-") as d:
                assemble(old.name,Path(d))
            print("MYR_DIRECT_AUTO_RELEASE_REHEARSAL_OK")
            return
        if not APPROVAL.exists() and not APPROVAL.is_symlink():
            print("MYR_DIRECT_NO_APPROVED_UPDATE");return
        deploy(private(APPROVAL))
if __name__=="__main__":main()
