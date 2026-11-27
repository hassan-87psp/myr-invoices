"""Pinned LHDN connection-only release; preserve live native login and database.
No Supabase changes, provider gate activation or invoice submission.
Default mode is read-only preflight. Explicit --activate changes production.
"""
import os, re, sys, shutil, tempfile, fcntl, json, time, stat
from pathlib import Path
import activate_public_auth as P
import business_lhdn as L

OLD="a422923e0b95068b3eb6ee535da3fa38d026310e"
TARGET="4942c9562c5012c75ab75c10f116fefae039d48a"
SERVICE="myr-production-core.service"
def guard(ok,msg): P.check(ok,msg)
def marker(path,expected):
    st=path.lstat()
    guard(stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid() and not st.st_mode&0o077 and path.read_text().strip()==expected,"Release marker mismatch: "+path.name)

def routing(original):
    guard("/api/myr/lhdn/connection" not in original,"LHDN route already present")
    blocks=re.findall(r"(?m)^location = /api/myr/admin/dashboard \{[^}]+\}",original)
    guard(len(blocks)==1,"Expected one exact admin routing block")
    b=blocks[0]
    guard(b.count("http://127.0.0.1:8767/admin/dashboard;")==1 and "proxy_set_header Cookie $http_cookie;" in b and "proxy_set_header Authorization $http_authorization;" in b,"Unexpected native-compatible routing")
    guard(b.count("location = /api/myr/admin/dashboard")==1,"Unexpected route")
    new=b.replace("location = /api/myr/admin/dashboard","location = /api/myr/lhdn/connection").replace("http://127.0.0.1:8767/admin/dashboard;","http://127.0.0.1:8767/lhdn/connection;")
    new=re.sub(r"proxy_read_timeout [^;]+;","proxy_read_timeout 40s;",new)
    new=re.sub(r"client_max_body_size [^;]+;","client_max_body_size 8k;",new)
    return original.replace(b,new+"\n\n"+b,1)

def anonymous(expected):
    for i in range(20):
        status=P.https("/api/myr/lhdn/connection",{"p_company_id":"00000000-0000-0000-0000-000000000001"},"https://myrinvoice.com")
        if status==expected: return
        time.sleep(1)
    raise RuntimeError("Unexpected anonymous LHDN HTTP "+status)

def bridge_closed():
    code,data=L.bridge({"action":"configuration_status","environment":"production"})
    guard(code==200 and data.get("ok") is True and data.get("configured") is True and data.get("connection_check_enabled") is False and data.get("submission_enabled") is False,"Central bridge not configured or provider gates not closed")
    print("MYR_CENTRAL_BRIDGE_GATES_CLOSED",flush=True)

def main():
    os.umask(0o077)
    guard(sys.argv[1:] in ([],["--activate"]),"Use no arguments for preflight or --activate for release")
    activate=bool(sys.argv[1:])
    guard(P.out("id","-un")=="myradmin","Run as myradmin")
    guard(not P.STATE.exists(),"Unfinished deployment: operator review required")
    for name in (*P.TIMERS,"myr-static-deploy.timer"):
        guard(not P.active(name) and not P.active(name.replace(".timer",".service")),"Unexpected active production auto-deployer")
    marker(P.MARKER,OLD);marker(P.FLAG,OLD)
    guard(P.out("git","-C",P.REPO,"status","--porcelain","--untracked-files=no")=="","Tracked changes present")
    P.run("git","-C",P.REPO,"merge-base","--is-ancestor",OLD,TARGET)
    previous=(P.BASE/"current").resolve(strict=True)
    guard(previous==P.BASE/"releases"/("vps-frontend-"+OLD),"Unexpected live frontend")
    old_prod=P.HOME/"myr-backend-releases/production"/OLD
    guard(P.out("systemctl","--user","show",SERVICE,"-p","WorkingDirectory","--value")==str(old_prod/"vps/backend"),"Unexpected production backend")
    guard(P.DROP.is_file() and not P.DROP.is_symlink(),"Missing approved service drop-in")
    old_drop=P.DROP.read_bytes()
    P.run("sudo","-v")
    with open(P.BASE/"deploy.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker(P.MARKER,OLD);marker(P.FLAG,OLD)
        guard(not P.STATE.exists() and (P.BASE/"current").resolve()==previous,"Concurrent deployment")
        original=P.out("sudo","cat",P.CONF)+"\n"
        new=routing(original)
        P.health(True);P.wait_native_status("401");anonymous("404");bridge_closed()
        P.run("sudo","nginx","-t")
        prod=P.HOME/"myr-backend-releases/production"/TARGET
        web=P.BASE/"releases"/("vps-frontend-"+TARGET)
        guard(not prod.exists() and not web.exists(),"Target already exists; review before retry")
        with tempfile.TemporaryDirectory(dir=P.HOME,prefix=".myr-lhdn-") as tmp:
            stage=Path(tmp);src=stage/"src";src.mkdir()
            archive=P.run("git","-C",P.REPO,"archive",TARGET,"vps/backend",*P.ASSETS,stdout=P.subprocess.PIPE).stdout
            P.run("tar","-xf","-","-C",src,input=archive)
            env={k:v for k,v in os.environ.items() if k!="MYR_PRODUCTION_RELEASE"}
            for name in ("check_lhdn_candidate.py","check_business_asgi.py","check_native_business_asgi.py","check_account_mail_asgi.py"):
                P.run(P.PY,"-B",src/"vps/backend"/name,env=env)
            candidate=stage/"candidate"
            P.run(P.PY,"-B",src/"vps/backend/build_cutover_check.py",env={**env,"MYR_CANDIDATE_DIR":str(candidate),"MYR_BUSINESS_API_PREFIX":"/api/myr"})
            # Use exactly the native-auth transform from the pinned target.
            P.run(P.PY,"-B","-c","from pathlib import Path;import sys;from build_native_auth_candidate import transform;p=Path(sys.argv[1]);p.write_text(transform(p.read_text()))",candidate/"index.html",cwd=src/"vps/backend",env=env)
            html=(candidate/"index.html").read_text()
            banner="PRIVATE VPS DATABASE CANDIDATE — Real imported data read-only. Production saves and external integrations disabled."
            guard(html.count(banner)==1,"Unexpected release banner")
            html=html.replace(banner,"MYR INVOICE — Central MyInvois connection setup. Invoice submission not released.")
            html=html.replace("persistSession:false","persistSession:true")
            html=html.replace("Not available in read-only VPS staging","Not available in this core release")
            html=html.replace("Unsupported rehearsal mutation","Advanced action unavailable in core release")
            html=html.replace("This action is not connected in this rehearsal. Reload to discard local changes.","This advanced action is not available in this release. Reload to discard unsaved changes.")
            html=html.replace("if(false&&'serviceWorker' in navigator","if('serviceWorker' in navigator")
            guard(all(s in html for s in ("persistSession:true","myrNativeAuth(client)","myrCentralCustomer","myrCentralAdmin","/api/myr/lhdn/connection")),"Wrong frontend")
            for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
                if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                    P.run("node","--check","-",input=code,text=True)
            print("MYR_LHDN_RELEASE_PREFLIGHT_OK",flush=True)
            if not activate: return
            P.run(P.PY,"-B",src/"vps/backend/native_backup.py",env=env)
            P.run("sudo","-v")
            marker(P.MARKER,OLD);marker(P.FLAG,OLD);bridge_closed()
            guard(P.out("sudo","cat",P.CONF)+"\n"==original,"Nginx changed during preflight")
            guard((P.BASE/"current").resolve()==previous and not P.STATE.exists(),"Concurrent release")
            orig=stage/"original";orig.write_text(original)
            conf=stage/"new";conf.write_text(new)
            backup=P.CONF+".pre-lhdn-"+TARGET[:12]
            guard(P.subprocess.run(["sudo","test","-e",backup]).returncode==1,"Nginx backup already exists")
            P.run("sudo","cp","-a",P.CONF,backup)
            prod.mkdir(mode=0o700,parents=True)
            shutil.copytree(src/"vps/backend",prod/"vps/backend")
            shutil.copy2(src/"config.js",prod/"config.js")
            web.mkdir(mode=0o755)
            for asset in P.ASSETS:
                dest=web/asset;dest.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
                shutil.copy2(src/asset,dest)
            (web/"index.html").write_text(html)
            shutil.copy2(candidate/"config.js",web/"config.js")
            for p in [web,*web.rglob("*")]: p.chmod(0o755 if p.is_dir() else 0o644)
            P.STATE.mkdir(mode=0o700)
            for name,value in (("previous-marker",OLD),("previous-native-flag",OLD),("previous-web",str(previous)),("target",TARGET),("old-nginx",original)):
                (P.STATE/name).write_text(value+"\n")
            (P.STATE/"old-dropin").write_bytes(old_drop)
            try:
                P.run("systemctl","--user","stop",SERVICE)
                P.atomic(P.DROP,"[Service]\nWorkingDirectory="+str(prod/"vps/backend")+"\nEnvironment=MYR_PRODUCTION_RELEASE="+TARGET+"\n")
                P.run("systemctl","--user","daemon-reload")
                P.run("systemctl","--user","start",SERVICE)
                P.health(False);P.wait_native_status("503")
                P.run("sudo","install","-m","0644",conf,P.CONF)
                P.run("sudo","nginx","-t")
                P.run("sudo","systemctl","reload","nginx")
                anonymous("401")
                P.link(web)
                page=P.run("curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","15","-fsS","https://myrinvoice.com/",stdout=P.subprocess.PIPE).stdout
                guard(page==(web/"index.html").read_bytes(),"Unexpected live frontend")
                # Same schema and account data. Both markers must follow the pinned release.
                P.atomic(P.FLAG,TARGET+"\n")
                P.atomic(P.MARKER,TARGET+"\n")
                P.health(True);P.wait_native_status("401");anonymous("401")
                guard(P.https("/api/myr/admin/dashboard")=="401","Admin access guard failed")
                bridge_closed()
                shutil.rmtree(P.STATE)
                print("MYR_LHDN_CONNECTION_UI_LIVE_OK",flush=True)
                print("Existing native authentication retained; provider login and invoice submission remain disabled.",flush=True)
            except BaseException:
                # Same DB schema: restore code, routing and both flags, never restore an older database.
                print("MYR_LHDN_RELEASE_ROLLBACK_START",flush=True)
                P.run("systemctl","--user","stop",SERVICE)
                P.atomic(P.DROP,old_drop.decode())
                P.link(previous)
                P.run("sudo","cp","-a",backup,P.CONF)
                P.run("sudo","nginx","-t")
                P.run("sudo","systemctl","reload","nginx")
                P.atomic(P.FLAG,OLD+"\n");P.atomic(P.MARKER,OLD+"\n")
                P.run("systemctl","--user","daemon-reload")
                P.run("systemctl","--user","start",SERVICE)
                P.health(True);P.wait_native_status("401");anonymous("404")
                shutil.rmtree(P.STATE)
                print("MYR_LHDN_RELEASE_ROLLED_BACK",flush=True)
                raise

if __name__=="__main__":main()
