"""Explicit guard-only sidecar publication; no credentials or provider calls.
No schema, production core, frontend, billing, auth marker or secret changes.
Rollback restores the exact nginx file and removes only the newly created service.
An interrupted release leaves a private recovery record and refuses another run.
"""
import fcntl, hashlib, json, os, shutil, socket, subprocess, sys, time
from pathlib import Path

H=Path.home()
R=H/"myr-invoices"
PIN="4942c9562c5012c75ab75c10f116fefae039d48a"
SOURCE="df90fe9fbb91ecab55a78c1bcb2793eff84c131b"
CORE=H/"myr-backend-releases/production"/PIN/"vps/backend"
SIDE=H/"myr-backend-releases/direct-erp-guard"/SOURCE
CONFIG=H/".config/myrinvoice"
STATE=CONFIG/"direct-erp-guard-recovery"
BASE=Path("/var/www/myrinvoice.com/auto")
CONF=Path("/etc/nginx/sites-available/myrinvoice.com")
SERVICE="myr-direct-erp-guard.service"
UNIT=H/".config/systemd/user"/SERVICE
PY=H/"myr-venv/bin/python"
PORT=8769
FILES=("lhdn_direct_sidecar_candidate.py","lhdn_direct_pilot_candidate.py",
       "lhdn_direct_vault_candidate.py","lhdn_direct_candidate.py","lhdn_protocol_candidate.py")
PATH="/api/myr/lhdn/direct-pilot"
ANCHOR="location ^~ /api/myr/ {"
ROUTE="""location = /api/myr/lhdn/direct-pilot {
    limit_except POST { deny all; }
    proxy_pass http://127.0.0.1:8769/lhdn/direct-pilot;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Origin $http_origin;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_hide_header Set-Cookie;
    proxy_connect_timeout 3s;
    proxy_read_timeout 15s;
    client_max_body_size 4k;
    access_log off;
    add_header Cache-Control "no-store" always;
}
"""
def run(*a,**kw):
    return subprocess.run([str(x) for x in a],check=True,timeout=90,**kw)
def out(*a):
    return run(*a,stdout=subprocess.PIPE).stdout
def check(ok,msg):
    if not ok: raise RuntimeError(msg)
def active(unit):
    return subprocess.run(["systemctl","--user","is-active","--quiet",unit],timeout=10).returncode==0
def code(path,*,local=False,post=False,origin="https://myrinvoice.com"):
    url=("http://127.0.0.1:"+str(PORT)+path if local else "https://myrinvoice.com"+path)
    a=["curl","--noproxy","*","--max-time","5","-sS","-o","/dev/null","-w","%{http_code}"]
    if not local:a+=["--resolve","myrinvoice.com:443:127.0.0.1"]
    if post:a+=["-X","POST","-H","Content-Type: application/json","-H","Origin: "+origin,"--data","{}"]
    return out(*a,url).decode()
def core_health():
    d=json.loads(out("curl","--noproxy","*","--max-time","5","-fsS","http://127.0.0.1:8767/health"))
    check(d.get("database")=="vps" and d.get("writes_enabled") is True,"Core health mismatch")
    for p in ("/api/myr/workspace","/api/myr/native/auth/me",
              "/api/myr/billing/customer?company_id=00000000-0000-0000-0000-000000000000",
              "/api/myr/billing/admin/sandbox"):
        check(code(p)=="401","Existing auth guard mismatch: "+p)
    check(code("/api/myr/billing/admin/sandbox/checkout")=="404","Billing checkout guard changed")
def snapshot():
    root=(BASE/"current").resolve(strict=True)
    check(root.parent==BASE/"releases","Unexpected frontend root")
    return (root,hashlib.sha256((root/"index.html").read_bytes()).hexdigest())
def retry(fn):
    for i in range(15):
        try:
            if fn():return
        except (OSError,subprocess.SubprocessError):pass
        time.sleep(1)
    raise RuntimeError("Service or proxy guard check timed out")
def main():
    os.umask(0o077)
    check(sys.argv[1:]==["--publish-guard-only"],"Explicit --publish-guard-only required")
    check(out("id","-un").strip()==b"myradmin","Run as myradmin")
    check(CORE.is_dir() and PY.is_file(),"Pinned runtime missing")
    for m in ("production-writes-enabled","native-auth-pilot-enabled"):
        p=CONFIG/m
        check(p.is_file() and not p.is_symlink() and p.read_text().strip()==PIN,"Production pin changed")
    for stem in ("myr-static-deploy","myr-core-backend-deploy","myr-core-frontend-deploy"):
        check(not active(stem+".timer") and not active(stem+".service"),"Conflicting deployment")
    check(active("myr-production-core.service") and active("myr-billing-readonly.service"),"Existing services inactive")
    check(not any(p.exists() or p.is_symlink() for p in (STATE,SIDE,UNIT)) and not active(SERVICE),"Existing release/recovery; stop for review")
    check(not (CONFIG/"direct-erp-pilot.json").exists(),"A pilot grant exists; review separately")
    with socket.socket() as s:s.bind(("127.0.0.1",PORT))
    run("sudo","-v")
    with (BASE/"deploy.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        core_health()
        before=snapshot()
        check(code(PATH,post=True)=="404","Direct route already exists")
        original=out("sudo","cat",CONF)
        text=original.decode()
        check(text.count(ANCHOR)==1 and PATH not in text,"Unexpected nginx configuration")
        changed=text.replace(ANCHOR,ROUTE+"\n"+ANCHOR,1).encode()
        STATE.mkdir(mode=0o700)
        (STATE/"nginx.original").write_bytes(original)
        (STATE/"nginx.candidate").write_bytes(changed)
        (STATE/"source").write_text(SOURCE+"\n")
        changed_nginx=False
        unit_created=False
        try:
            SIDE.mkdir(parents=True,mode=0o700)
            for name in FILES:
                raw=out("git","-C",R,"show",SOURCE+":vps/backend/"+name)
                (SIDE/name).write_bytes(raw)
            source=(SIDE/FILES[0]).read_text()
            check("return pilot.unavailable()  # Hard-disabled:" in source and "return pilot.handle(" not in source,"Credential entry guard missing")
            env={**os.environ,"PYTHONPATH":str(SIDE)+":"+str(CORE),"MYR_PRODUCTION_RELEASE":PIN}
            run(PY,"-B",SIDE/FILES[0],env=env)
            unit=("[Unit]\nDescription=MYR Direct ERP guard-only sidecar\nAfter=network.target\n"
                  "[Service]\nType=simple\nWorkingDirectory="+str(SIDE)+"\n"
                  "Environment=MYR_PRODUCTION_RELEASE="+PIN+"\nEnvironment=PYTHONPATH="+str(CORE)+"\n"
                  "ExecStart="+str(PY)+" -B -m uvicorn lhdn_direct_sidecar_candidate:api --host 127.0.0.1 --port "+str(PORT)+" --no-access-log\n"
                  "Restart=on-failure\nNoNewPrivileges=true\nUMask=0077\n[Install]\nWantedBy=default.target\n")
            UNIT.parent.mkdir(parents=True,exist_ok=True)
            UNIT.write_text(unit)
            unit_created=True
            run("systemctl","--user","daemon-reload")
            run("systemctl","--user","start",SERVICE)
            retry(lambda:code("/lhdn/direct-pilot",local=True,post=True)=="401")
            check(code("/lhdn/direct-pilot",local=True,post=True,origin="https://invalid.example")=="403","Origin guard failed")
            check(code("/workspace",local=True)=="404","Unexpected sidecar route")
            check(out("sudo","cat",CONF)==original,"Concurrent nginx change")
            changed_nginx=True
            run("sudo","install","-m","0644",STATE/"nginx.candidate",CONF)
            run("sudo","nginx","-t")
            run("sudo","systemctl","reload","nginx")
            retry(lambda:code(PATH,post=True)=="401")
            check(code(PATH,post=True,origin="https://invalid.example")=="403","Public origin guard failed")
            core_health()
            check(snapshot()==before,"Frontend changed during publication")
            run("systemctl","--user","enable",SERVICE)
            (STATE/"status").write_text("guard-only-published\n")
            print("MYR_DIRECT_GUARD_ROUTE_LIVE_OK",flush=True)
            print("Guard only: credential entry, provider calls and submission remain disabled.",flush=True)
        except BaseException:
            if changed_nginx:
                check(out("sudo","cat",CONF)==changed,"Nginx changed concurrently; manual recovery required")
                run("sudo","install","-m","0644",STATE/"nginx.original",CONF)
                run("sudo","nginx","-t")
                run("sudo","systemctl","reload","nginx")
            if unit_created:
                run("systemctl","--user","stop",SERVICE)
                subprocess.run(["systemctl","--user","disable",SERVICE],check=False,timeout=30)
                UNIT.unlink()
                run("systemctl","--user","daemon-reload")
            core_health()
            (STATE/"status").write_text("rolled-back-review-required\n")
            print("MYR_DIRECT_GUARD_ROLLBACK_OK; private recovery retained",flush=True)
            raise
if __name__=="__main__":main()
