"""Explicit read-only billing publication. No changes to core service, auth flags,
existing company records, payment credentials, or live checkout. Additive empty
ledger tables only; on failure restore nginx/frontend and stop the sidecar.
"""
import os,re,sys,shutil,subprocess,fcntl,tempfile,time,json
from pathlib import Path
from build_chip_billing_candidate import transform

HOME=Path.home()
ROOT=Path(__file__).resolve().parents[2]
PIN="4942c9562c5012c75ab75c10f116fefae039d48a"
BASE=Path("/var/www/myrinvoice.com/auto")
CONF=Path("/etc/nginx/sites-available/myrinvoice.com")
CONFIG=HOME/".config/myrinvoice"
UNIT=HOME/".config/systemd/user/myr-billing-readonly.service"
SERVICE=UNIT.name
CORE=HOME/"myr-backend-releases/production"/PIN/"vps/backend"
SIDE=HOME/"myr-backend-releases/billing-readonly"
RECOVERY=CONFIG/"billing-readonly-deploy-recovery"
PY=HOME/"myr-venv/bin/python"
TABLES=("billing_periods","billing_receipts","chip_test_intents","chip_test_receipts")
FILES=("billing_readonly_app.py","billing_ledger_candidate.py","chip_test_lifecycle_candidate.py","chip_billing_view_candidate.py")
def run(*args,**kw):
    return subprocess.run([str(a) for a in args],check=True,**kw)
def out(*args):
    return run(*args,stdout=subprocess.PIPE,text=True).stdout.strip()
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def active(unit):
    return subprocess.run(["systemctl","--user","is-active","--quiet",unit]).returncode==0
def probe(path):
    return out("curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","10","-sS","-o","/dev/null","-w","%{http_code}","https://myrinvoice.com"+path)
def core_health():
    d=json.loads(out("curl","--noproxy","*","-fsS","--max-time","5","http://127.0.0.1:8767/health"))
    check(d.get("database")=="vps" and d.get("writes_enabled") is True,"Core health failed")
    check(probe("/api/myr/workspace")=="401" and probe("/api/myr/native/auth/me")=="401","Existing authentication guard failed")
def link(path):
    temp=BASE/(".billing-link-"+str(os.getpid()))
    temp.unlink(missing_ok=True)
    temp.symlink_to(path)
    os.replace(temp,BASE/"current")
def db_exists():
    query="SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='myr_native' AND c.relkind='r' AND c.relname IN ("+",".join("'"+x+"'" for x in TABLES)+")"
    return int(out("sudo","-u","postgres","psql","-X","-At","-d","myrinvoice","-c",query))
def route(path):
    return """location = /api/myr/"""+path+""" {
    limit_except GET { deny all; }
    proxy_pass http://127.0.0.1:8768/"""+path+""";
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_hide_header Set-Cookie;
    proxy_connect_timeout 5s;
    proxy_read_timeout 15s;
    add_header Cache-Control "no-store" always;
}
"""
def main():
    os.umask(0o077)
    check(sys.argv[1:]==["--publish-readonly-billing"],"Explicit --publish-readonly-billing required")
    check(out("id","-un")=="myradmin","Run as myradmin")
    for marker in ("production-writes-enabled","native-auth-pilot-enabled"):
        check((CONFIG/marker).read_text().strip()==PIN,"Unexpected production marker")
    check(CORE.is_dir() and not UNIT.exists() and not SIDE.exists() and not RECOVERY.exists(),"Existing or interrupted billing release; review first")
    check(not active("myr-billing-readonly.service"),"Billing service already active")
    for timer in ("myr-static-deploy.timer","myr-core-backend-deploy.timer","myr-core-frontend-deploy.timer"):
        check(not active(timer) and not active(timer.replace(".timer",".service")),"Auto-deploy active: refuse to overwrite")
    run("sudo","-v")
    with (BASE/"deploy.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        core_health()
        previous=(BASE/"current").resolve(strict=True)
        check(previous.parent==BASE/"releases","Unexpected frontend root")
        check(not any(p.is_symlink() for p in previous.rglob("*")),"Unexpected symlink in web root")
        old=(previous/"index.html").read_text()
        check("myrNativeAuth" in old and "myrAuthHeaders" in old,"Existing auth adapter missing")
        html=transform(old)
        html=html.replace("myrBillingRequest('customer/'+encodeURIComponent(co.id))","myrBillingRequest('customer?company_id='+encodeURIComponent(co.id))")
        html=html.replace('onclick="myrChipAdminCreate(this)">Create sandbox checkout','disabled>Create sandbox checkout (not released)')
        check("customer?company_id=" in html and "Create sandbox checkout (not released)" in html,"Read-only UI guard missing")
        for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
            if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                run("node","--check","-",input=code,text=True)
        original=run("sudo","cat",CONF,stdout=subprocess.PIPE,text=True).stdout
        anchor="location ^~ /api/myr/ {"
        check(original.count(anchor)==1 and "/api/myr/billing/" not in original,"Unexpected nginx routing")
        nginx=original.replace(anchor,route("billing/customer")+"\n"+route("billing/admin/sandbox")+"\n"+anchor,1)
        check(db_exists()==0,"Billing tables already exist; review permissions and schema before retry")
        run(PY,"-B",ROOT/"vps/backend/native_backup.py")
        commit=out("git","-C",ROOT,"rev-parse","--short=12","HEAD")
        release=BASE/"releases"/("vps-frontend-billing-"+commit+"-"+str(int(time.time())))
        check(not release.exists(),"Release already exists")
        RECOVERY.mkdir(mode=0o700)
        (RECOVERY/"previous-web").write_text(str(previous)+"\n")
        (RECOVERY/"nginx.conf").write_text(original)
        changed_nginx=False
        changed_link=False
        service_created=False
        try:
            # Additive schema only; existing rows and core roles are not altered.
            sql="\n".join((ROOT/"vps"/f).read_text() for f in ("billing-ledger.review.sql","chip-test-ledger.review.sql"))
            names=", ".join("myr_native."+t for t in TABLES)
            sql+="\nREVOKE ALL ON "+names+" FROM myrinvoice_app;\nGRANT SELECT ON "+names+" TO myrinvoice_app;\n"
            run("sudo","-u","postgres","psql","-X","-v","ON_ERROR_STOP=1","-1","-d","myrinvoice",input=sql,text=True)
            check(db_exists()==4,"Ledger schema not complete")
            SIDE.mkdir(mode=0o700,parents=True)
            for name in FILES:shutil.copy2(ROOT/"vps/backend"/name,SIDE/name)
            unit="[Unit]\nDescription=MYR read-only billing sidecar\nAfter=network.target\n[Service]\nType=simple\nWorkingDirectory="+str(SIDE)+"\nEnvironment=MYR_PRODUCTION_RELEASE="+PIN+"\nEnvironment=PYTHONPATH="+str(CORE)+"\nExecStart="+str(PY)+" -B -m uvicorn billing_readonly_app:api --host 127.0.0.1 --port 8768\nRestart=on-failure\nNoNewPrivileges=true\n[Install]\nWantedBy=default.target\n"
            UNIT.parent.mkdir(parents=True,exist_ok=True)
            service_created=True
            UNIT.write_text(unit)
            run("systemctl","--user","daemon-reload")
            run("systemctl","--user","start",SERVICE)
            for _ in range(15):
                try:
                    d=json.loads(out("curl","--noproxy","*","-fsS","--max-time","2","http://127.0.0.1:8768/health"))
                    if d=={"status":"ok","mode":"read_only"}:break
                except (ValueError,subprocess.CalledProcessError):pass
                time.sleep(1)
            else:raise RuntimeError("Billing sidecar health failed")
            shutil.copytree(previous,release)
            (release/"index.html").write_text(html)
            (release/"index.html").chmod(0o644)
            with tempfile.NamedTemporaryFile(mode="w",dir=HOME,delete=False) as f:
                f.write(nginx);tmp=f.name
            try:
                changed_nginx=True
                run("sudo","install","-m","0644",tmp,CONF)
            finally:Path(tmp).unlink(missing_ok=True)
            run("sudo","nginx","-t")
            run("sudo","systemctl","reload","nginx")
            check(probe("/api/myr/billing/customer?company_id=00000000-0000-0000-0000-000000000000")=="401","Billing owner auth failed")
            check(probe("/api/myr/billing/admin/sandbox")=="401","Billing admin auth failed")
            check(probe("/api/myr/billing/admin/sandbox/checkout")=="404","Checkout unexpectedly exposed")
            core_health()
            changed_link=True
            link(release)
            page=run("curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","10","-fsS","https://myrinvoice.com/",stdout=subprocess.PIPE).stdout
            check(page==(release/"index.html").read_bytes(),"Frontend verification failed")
            core_health()
            run("systemctl","--user","enable",SERVICE)
            print("MYR_READONLY_BILLING_LIVE_OK")
            print("Customer billing history and admin status only. Actual payments and LHDN remain gated; core service and authentication unchanged.")
            print("Recovery configuration saved privately in",RECOVERY)
        except BaseException:
            if changed_link:link(previous)
            if changed_nginx:
                run("sudo","install","-m","0644",RECOVERY/"nginx.conf",CONF)
                run("sudo","nginx","-t")
                run("sudo","systemctl","reload","nginx")
            if service_created:
                subprocess.run(["systemctl","--user","disable","--now",SERVICE],check=False)
                UNIT.unlink(missing_ok=True)
                run("systemctl","--user","daemon-reload")
            print("MYR_READONLY_BILLING_ROLLED_BACK; additive empty billing schema and recovery files retained for review")
            raise
if __name__=="__main__":main()
