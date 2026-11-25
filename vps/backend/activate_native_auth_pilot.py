"""Operator-approved limited real email pilot; existing business DB and accounts unchanged."""
import os, re, sys, subprocess, shutil, tempfile, fcntl, time, json, stat
from pathlib import Path
from app import connect
from build_native_auth_candidate import transform

HOME=Path.home()
REPO=Path(__file__).resolve().parents[2]
BASE=Path("/var/www/myrinvoice.com/auto")
CONF="/etc/nginx/sites-available/myrinvoice.com"
CONFIG=HOME/".config/myrinvoice"
MARKER=CONFIG/"production-writes-enabled"
FLAG=CONFIG/"native-auth-pilot-enabled"
STATE=CONFIG/"core-backend-deploy-in-progress"
DROP=HOME/".config/systemd/user/myr-production-core.service.d/30-approved-release.conf"
PY=HOME/"myr-venv/bin/python"
TIMERS=("myr-core-backend-deploy.timer","myr-core-frontend-deploy.timer")
ASSETS="index.html config.js concurrency.js klcc-skyline.webp myr-auth-night.svg manifest.webmanifest pwa-icon-192.png pwa-icon-512.png robots.txt seo.css sitemap.xml sw.js e-invoice-malaysia/index.html invoice-app-malaysia/index.html invoice-generator-malaysia/index.html invoice-software-malaysia/index.html invoicing-software-for-small-business-malaysia/index.html myinvois-checklist/index.html".split()
def run(*args,**kw): return subprocess.run([str(a) for a in args],check=True,**kw)
def out(*args): return run(*args,stdout=subprocess.PIPE,text=True).stdout.strip()
def check(ok,msg):
    if not ok: raise RuntimeError(msg)
def active(unit): return subprocess.run(["systemctl","--user","is-active","--quiet",unit]).returncode==0
def https(path,body=None,origin=None):
    args=["curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","15","-sS","-o","/dev/null","-w","%{http_code}"]
    if body is not None: args+=["-H","Content-Type: application/json","--data",json.dumps(body)]
    if origin: args+=["-H","Origin: "+origin]
    return out(*args,"https://myrinvoice.com"+path)
def health(expected):
    for _ in range(20):
        try:
            data=json.loads(out("curl","--noproxy","*","-fsS","--max-time","2","http://127.0.0.1:8767/health"))
            if data.get("database")=="vps" and data.get("writes_enabled") is expected: break
        except (subprocess.CalledProcessError,ValueError): pass
        time.sleep(1)
    else: raise RuntimeError("Production health mismatch")
    check(https("/api/myr/workspace")=="401","Workspace authentication mismatch")
    check(https("/api/myr/links/read",{"p_token":"0"*32})==("404" if expected else "503"),"Public link guard mismatch")
    check(https("/api/myr/native/auth/preview")=="404","Private preview must remain unavailable")
def atomic(path,value):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".pilot-")
    with os.fdopen(fd,"w") as w: w.write(value)
    os.chmod(tmp,0o600)
    os.replace(tmp,path)
def link(target):
    tmp=BASE/(".pilot-link-"+str(os.getpid()))
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target)
    os.replace(tmp,BASE/"current")
def config_for_pilot(original):
    reviewed=(REPO/"vps/nginx-business-routing.review.conf").read_text().replace("127.0.0.1:8766","127.0.0.1:8767").strip()
    check(original.count(reviewed)==1,"Live Nginx does not exactly match reviewed core routing; no change")
    check("/api/myr/native/auth/" not in original,"Native routing already exists")
    def block(m):
        s=m.group(0)
        if "/api/myr/links/read " in s or "/api/myr/links/submit " in s: return s
        return s.replace('proxy_set_header Cookie "";','proxy_set_header Cookie $http_cookie;')
    new=re.sub(r"location = /api/myr/[^ ]+ \{[^}]+\}",block,reviewed)
    auth=[]
    for route in ("me","login","logout","signup","verify-email","reset-request","reset-password"):
        auth.append(f"""location = /api/myr/native/auth/{route} {{
    proxy_pass http://127.0.0.1:8767/native/auth/{route};
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Authorization "";
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto https;
    proxy_connect_timeout 5s;
    proxy_read_timeout 55s;
    client_max_body_size 8k;
    add_header Cache-Control "no-store" always;
}}""")
    new="\n\n".join(auth)+"\n\n"+new
    return original.replace(reviewed,new,1)
def main():
    os.umask(0o077)
    check(sys.argv[1:]==["--activate-pilot"],"Use --activate-pilot")
    check(out("id","-un")=="myradmin","Run as myradmin")
    check(not FLAG.exists() and not STATE.exists(),"Another deployment or pilot already exists; review")
    check(stat.S_ISREG(MARKER.lstat().st_mode) and MARKER.stat().st_uid==os.getuid() and not(MARKER.stat().st_mode&0o077),"Invalid production marker")
    pinned=MARKER.read_text().strip()
    commit=out("git","-C",REPO,"rev-parse","HEAD")
    check(re.fullmatch("[0-9a-f]{40}",pinned) and re.fullmatch("[0-9a-f]{40}",commit) and pinned!=commit,"Invalid release")
    check(out("git","-C",REPO,"rev-parse","origin/main")==commit,"Pull current main")
    check(out("git","-C",REPO,"status","--porcelain","--untracked-files=no")=="","Tracked changes present")
    run("git","-C",REPO,"merge-base","--is-ancestor",pinned,commit)
    check(not active("myr-static-deploy.timer"),"Old static timer active")
    print("Limited live pilot: invoicesmyr@gmail.com only. Existing accounts keep legacy sign-in. No LHDN or business emails. Automatic publishing will be paused until the pilot is accepted.",flush=True)
    run("sudo","-v")
    with open(BASE/"deploy.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(MARKER.read_text().strip()==pinned and not STATE.exists(),"Concurrent release detected")
        check(not any(active(t.replace(".timer",".service")) for t in TIMERS),"Deploy worker active; retry")
        previous=(BASE/"current").resolve(strict=True)
        check(previous.parent==BASE/"releases","Unexpected live root")
        previous_commit=previous.name.rsplit("-",1)[-1]
        check(re.fullmatch("[0-9a-f]{40}",previous_commit),"Unknown previous website revision")
        run("git","-C",REPO,"merge-base","--is-ancestor",previous_commit,commit)
        original=run("sudo","cat",CONF,stdout=subprocess.PIPE,text=True).stdout
        config=config_for_pilot(original)
        health(True)
        with connect() as conn:
            check(conn.execute("SELECT count(*) FROM myr_native.users WHERE email='invoicesmyr@gmail.com'").fetchone()[0]==0,"Pilot email already has a native account; review first")
        prod=HOME/"myr-backend-releases/production"/commit
        web=BASE/"releases"/("vps-frontend-"+commit)
        check(not prod.exists() and not web.exists(),"Release path exists; review before retry")
        timers=[t for t in TIMERS if active(t)]
        switched=False
        changed=False
        opened=False
        timers_paused=False
        old_drop=DROP.read_bytes() if DROP.exists() else None
        with tempfile.TemporaryDirectory(dir=HOME,prefix=".myr-pilot-") as d:
            stage=Path(d)
            src=stage/"src";src.mkdir()
            archive=run("git","-C",REPO,"archive",commit,"vps/backend",*ASSETS,stdout=subprocess.PIPE).stdout
            run("tar","-xf","-","-C",src,input=archive)
            env={k:v for k,v in os.environ.items() if k!="MYR_PRODUCTION_RELEASE"}
            for name in ("check_business_asgi.py","business_admin.py","business_links.py","business_link_ops.py","business_api.py","check_native_business_asgi.py","check_account_mail_asgi.py","check_email_logo.py"):
                run(PY,"-B",src/"vps/backend"/name,env=env)
            run(PY,"-B",src/"vps/backend/native_backup.py",env=env)
            candidate=stage/"candidate"
            run(PY,"-B",src/"vps/backend/build_cutover_check.py",env={**env,"MYR_CANDIDATE_DIR":str(candidate),"MYR_BUSINESS_API_PREFIX":"/api/myr"})
            html=transform((candidate/"index.html").read_text())
            old="PRIVATE VPS DATABASE CANDIDATE — Real imported data read-only. Production saves and external integrations disabled."
            check(html.count(old)==1,"Unexpected release banner")
            html=html.replace(old,"MYR INVOICE — Limited account email pilot. Existing invoice workflows remain available.")
            html=html.replace("persistSession:false","persistSession:true")
            html=html.replace("Not available in read-only VPS staging","Not available in this core release")
            html=html.replace("Unsupported rehearsal mutation","Advanced action unavailable in core release")
            html=html.replace("This action is not connected in this rehearsal. Reload to discard local changes.","This advanced action is not available in this release. Reload to discard unsaved changes.")
            html=html.replace("if(false&&'serviceWorker' in navigator","if('serviceWorker' in navigator")
            check("persistSession:true" in html and "myrNativeAuth(client)" in html,"Wrong frontend")
            for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
                if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                    run("node","--check","-",input=code,text=True)
            prod.mkdir(mode=0o700,parents=True)
            shutil.copytree(src/"vps/backend",prod/"vps/backend")
            shutil.copy2(src/"config.js",prod/"config.js")
            web.mkdir(mode=0o755)
            for asset in ASSETS:
                dest=web/asset
                dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                shutil.copy2(src/asset,dest)
            (web/"index.html").write_text(html)
            shutil.copy2(candidate/"config.js",web/"config.js")
            for p in [web,*web.rglob("*")]: p.chmod(0o755 if p.is_dir() else 0o644)
            orig=stage/"original";orig.write_text(original)
            new=stage/"new";new.write_text(config)
            try:
                STATE.mkdir(mode=0o700)
                (STATE/"previous-marker").write_text(pinned+"\n")
                (STATE/"previous-web").write_text(str(previous)+"\n")
                (STATE/"target").write_text(commit+"\n")
                (STATE/"old-nginx").write_text(original)
                if old_drop is not None: (STATE/"old-dropin").write_bytes(old_drop)
                timers_paused=True
                run("systemctl","--user","disable","--now",*TIMERS)
                check(not any(active(t.replace(".timer",".service")) for t in TIMERS),"Deploy worker active")
                run("sudo","cp","-a",CONF,CONF+".pre-native-pilot-"+commit[:12])
                switched=True
                run("systemctl","--user","stop","myr-production-core.service")
                DROP.parent.mkdir(parents=True,exist_ok=True)
                atomic(DROP,"[Service]\nWorkingDirectory="+str(prod/"vps/backend")+"\nEnvironment=MYR_PRODUCTION_RELEASE="+commit+"\n")
                run("systemctl","--user","daemon-reload")
                run("systemctl","--user","start","myr-production-core.service")
                health(False)
                changed=True
                run("sudo","install","-m","0644",new,CONF)
                run("sudo","nginx","-t")
                run("sudo","systemctl","reload","nginx")
                check(https("/api/myr/native/auth/me")=="503","Native auth not safely gated")
                link(web)
                page=run("curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","15","-fsS","https://myrinvoice.com/",stdout=subprocess.PIPE).stdout
                check(page==(web/"index.html").read_bytes(),"Wrong public website")
                atomic(MARKER,commit+"\n")
                opened=True
                health(True)
                atomic(FLAG,commit+"\n")
                check(https("/api/myr/native/auth/me")=="401","Native me must require cookie")
                check(https("/api/myr/native/auth/signup",{"email":"blocked@example.invalid"},"https://myrinvoice.com")=="403","Pilot restriction failed")
                check(https("/api/myr/native/auth/signup",{"email":"invoicesmyr@gmail.com"},"https://example.invalid")=="403","Origin guard failed")
                check(https("/api/myr/native/auth/activate-request",{},"https://myrinvoice.com")=="404","Imported activation must remain private")
                health(True)
                shutil.rmtree(STATE)
                print("MYR_LIVE_NATIVE_AUTH_PILOT_OK",flush=True)
                print("Only invoicesmyr@gmail.com can register. Open https://myrinvoice.com/#/signup in a private browser window; actual mailbox delivery still must be verified.",flush=True)
                print("Core auto-deploy paused for pilot review. Existing business data preserved.",flush=True)
            except BaseException:
                FLAG.unlink(missing_ok=True)
                if opened or MARKER.read_text().strip()==commit:
                    print("MYR_PILOT_CLOSED_POST_ACTIVATION_REVIEW_REQUIRED; do not roll back business data or marker",flush=True)
                    raise
                if switched:
                    run("systemctl","--user","stop","myr-production-core.service")
                    if old_drop is None: DROP.unlink(missing_ok=True)
                    else:
                        DROP.write_bytes(old_drop);DROP.chmod(0o600)
                    link(previous)
                    if changed:
                        run("sudo","install","-m","0644",orig,CONF)
                        run("sudo","nginx","-t")
                        run("sudo","systemctl","reload","nginx")
                    run("systemctl","--user","daemon-reload")
                    run("systemctl","--user","start","myr-production-core.service")
                    health(True)
                if timers_paused and timers: run("systemctl","--user","enable","--now",*timers)
                if STATE.exists(): shutil.rmtree(STATE)
                shutil.rmtree(prod,ignore_errors=True)
                shutil.rmtree(web,ignore_errors=True)
                print("MYR_PILOT_STOPPED_BEFORE_RELEASE; previous production retained",flush=True)
                raise

if __name__=="__main__": main()
