"""Explicit core-only cutover, with source freeze and rollback before writes.
Run as myradmin on VPS. No background deploy is allowed to overwrite production.
This is NOT full feature parity. Read the on-screen limitations first.
"""
import getpass,json,os,re,shutil,subprocess,sys,tempfile,time
from collections import Counter
from pathlib import Path
import psycopg
from psycopg import sql
from app import connect
from migration_rehearsal import PROJECT,BASE,ARCHIVE
from stage_copy import snapshot

HOME=Path.home()
REPO=Path(__file__).resolve().parents[2]
BASE_DIR=Path("/var/www/myrinvoice.com/auto")
CONF="/etc/nginx/sites-available/myrinvoice.com"
MARKER=HOME/".config/myrinvoice/production-writes-enabled"
UNIT=HOME/".config/systemd/user/myr-production-core.service"
PY=HOME/"myr-venv/bin/python"
HOST="aws-1-ap-southeast-1.pooler.supabase.com"
CA=REPO/"vps/certs/prod-ca-2021.crt"
ASSETS="index.html config.js concurrency.js klcc-skyline.webp myr-auth-night.svg manifest.webmanifest pwa-icon-192.png pwa-icon-512.png robots.txt seo.css sitemap.xml sw.js e-invoice-malaysia/index.html invoice-app-malaysia/index.html invoice-generator-malaysia/index.html invoice-software-malaysia/index.html invoicing-software-for-small-business-malaysia/index.html myinvois-checklist/index.html".split()
LIMITS="Core only: existing verified login, customer/product records, draft/ready invoices, eligible manual payments, invoice links, buyer QR, team and admin. Native signup/reset/email, LHDN, gateway, quotations, expenses, recurring, bulk imports, additional settings, demo and integrity dashboard not released. Auto-publishing is pinned until production deployment pipeline is accepted."

def run(*args,**kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)
def out(*args):
    return run(*args,stdout=subprocess.PIPE,text=True).stdout.strip()
def check(condition,message):
    if not condition: raise RuntimeError(message)
def bag(rows):
    return Counter(json.dumps(row,sort_keys=True,default=str,ensure_ascii=False) for row in rows)
def query_rows(c,query,params=None):
    return c.execute(query,params).fetchall()
def compare(source,dest):
    check(dest.execute("SELECT current_database(),current_user").fetchone()==("myrinvoice","myrinvoice_app"),"Wrong VPS database")
    ids=[r[0] for r in source.execute("SELECT id FROM public.companies ORDER BY id").fetchall()]
    actual=[r[0] for r in dest.execute("SELECT id FROM myr_native.companies WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' ORDER BY id").fetchall()]
    check(ids==actual,"Company ID set differs; fresh migration required")
    for table,fields in BASE.items():
        cols=sql.SQL(",").join(map(sql.Identifier,fields.split()))
        src=source.execute(sql.SQL("SELECT {} FROM public.{}").format(cols,sql.Identifier(table))).fetchall()
        target=sql.SQL("SELECT {} FROM myr_native.{}").format(cols,sql.Identifier(table))
        if table=="companies":
            dst=dest.execute(target+sql.SQL(" WHERE id=ANY(%s)"),(ids,)).fetchall()
        elif table=="audit_logs":
            dst=dest.execute(target+sql.SQL(" WHERE company_id=ANY(%s) OR (company_id IS NULL AND action NOT IN ('staging.admin.create','staging.admin.role_transfer'))"),(ids,)).fetchall()
        else:
            dst=dest.execute(target+sql.SQL(" WHERE company_id=ANY(%s)"),(ids,)).fetchall()
        check(bag(src)==bag(dst),"Exact row reconciliation failed: "+table)
        print("EXACT_ROWS_OK",table,len(src),flush=True)
    for schema,table in ARCHIVE:
        src=source.execute(sql.SQL("SELECT to_jsonb(t) FROM {}.{} t").format(sql.Identifier(schema),sql.Identifier(table))).fetchall()
        dst=dest.execute("SELECT record FROM myr_native.migration_source_archive WHERE source_table=%s",(schema+"."+table,)).fetchall()
        check(bag(src)==bag(dst),"Archived source changed: "+schema+"."+table)
    users=source.execute("SELECT id,lower(email),email_confirmed_at FROM auth.users").fetchall()
    for uid,email,verified in users:
        row=dest.execute("SELECT email,email_verified_at FROM myr_native.users WHERE id=%s",(uid,)).fetchone()
        check(row==(email,verified),"Imported identity changed; reconcile before switching")
    check(source.execute("SELECT count(*) FROM storage.objects").fetchone()[0]==0,"Storage migration required")
    check(source.execute("SELECT count(*) FROM public.lhdn_tenant_approvals").fetchone()[0]==0,"Active or historic LHDN authorization requires separate connector cutover")
    check(source.execute("SELECT count(*) FROM public.lhdn_documents WHERE status='Submitted'").fetchone()[0]==0,"LHDN submissions in progress")
    if source.execute("SELECT to_regclass('cron.job')").fetchone()[0]:
        check(source.execute("SELECT count(*) FROM cron.job WHERE active").fetchone()[0]==0,"Active source cron jobs; review before cutover")
    print("MYR_EXACT_SOURCE_RECONCILIATION_OK",flush=True)

def switch_link(target):
    tmp=BASE_DIR/(".core-current-"+str(os.getpid()))
    tmp.unlink(missing_ok=True)
    tmp.symlink_to(target)
    os.replace(tmp,BASE_DIR/"current")

def local_http(path="/health",payload=None):
    from urllib.request import urlopen,Request
    from urllib.error import HTTPError
    url="http://127.0.0.1:8767"+path
    try:
        with urlopen(Request(url,data=None if payload is None else json.dumps(payload).encode(),headers={"Content-Type":"application/json"}),timeout=5) as r:
            return r.status,json.load(r)
    except HTTPError as e:
        return e.code,None

def smoke(expected):
    for _ in range(20):
        try:
            status,h=local_http()
            if status==200 and h.get("database")=="vps" and h.get("writes_enabled") is expected: return
        except OSError: pass
        time.sleep(0.5)
    raise RuntimeError("Production service health mismatch")

def main():
    os.umask(0o077)
    check(out("id","-un")=="myradmin","Run as myradmin")
    check(not MARKER.exists() and not UNIT.exists(),"Existing production activation; do not rerun")
    check(sys.argv[1:]==["--activate-core"],"Use explicit --activate-core only after accepting temporary limits")
    print(LIMITS,flush=True)
    print("Source business tables become read-only. A verified backup and exact row comparison are required. No auto-thaw once VPS writes open.",flush=True)
    if input("Type SWITCH CORE to accept these temporary limitations and activate: ").strip()!="SWITCH CORE":
        raise SystemExit("No changes made.")
    run("sudo","-v")
    commit=out("git","-C",REPO,"rev-parse","HEAD")
    check(re.fullmatch(r"[0-9a-f]{40}",commit),"Invalid commit")
    check(out("git","-C",REPO,"status","--porcelain","--untracked-files=no")=="","Tracked repository modifications; refuse")
    check(out("git","-C",REPO,"rev-parse","origin/main")==commit,"Pull current main first")
    previous=(BASE_DIR/"current").resolve(strict=True)
    check(previous.parent==BASE_DIR/"releases","Unexpected current site")
    prod=HOME/"myr-backend-releases"/"production"/commit
    web=BASE_DIR/"releases"/("vps-core-"+commit)
    check(not prod.exists() and not web.exists(),"Release path already exists; inspect previous attempt")
    original=out("sudo","cat",CONF)+"\n"
    anchor="root /var/www/myrinvoice.com/auto/current;"
    check(original.count(anchor)==1 and "/api/myr/" not in original,"Nginx configuration changed; manual review required")
    routing=(REPO/"vps/nginx-business-routing.review.conf").read_text().replace("127.0.0.1:8766","127.0.0.1:8767")
    config=original.replace(anchor,anchor+"\n"+routing,1)
    # Fresh UI build and rollback tests before connecting to source.
    with tempfile.TemporaryDirectory(dir=HOME,prefix=".myr-core-") as tmp:
        tmp=Path(tmp)
        env={**os.environ,"MYR_BUSINESS_API_PREFIX":"/api/myr","MYR_CANDIDATE_DIR":str(tmp/"candidate")}
        run(PY,"-B",REPO/"vps/backend/build_cutover_check.py",env=env)
        for name in ("check_business_asgi.py","business_admin.py","business_links.py","business_link_ops.py","business_api.py"):
            run(PY,"-B",REPO/"vps/backend"/name)
        run(PY,"-B",REPO/"vps/backend/native_backup.py")
        stage=tmp/"web"
        stage.mkdir()
        archive=subprocess.Popen(["git","-C",str(REPO),"archive",commit,*ASSETS],stdout=subprocess.PIPE)
        try: run("tar","-xf","-","-C",stage,stdin=archive.stdout)
        finally: archive.stdout.close()
        check(archive.wait()==0,"Git archive failed")
        for name in ("index.html","config.js"):
            shutil.copy2(tmp/"candidate"/name,stage/name)
        index=stage/"index.html"
        html=index.read_text()
        html=html.replace("PRIVATE VPS DATABASE CANDIDATE — Real imported data read-only. Production saves and external integrations disabled.","VPS CORE RELEASE — Advanced operations temporarily unavailable. LHDN and email are not connected.")
        html=html.replace("persistSession:false","persistSession:true")
        html=html.replace("Not available in read-only VPS staging","Not available in this core release")
        html=html.replace("Unsupported rehearsal mutation","Advanced action unavailable in core release")
        html=html.replace("This action is not connected in this rehearsal. Reload to discard local changes.","This advanced action is not available in this release. Reload to discard unsaved changes.")
        # Preserve original SEO assets and network-only service worker.
        html=html.replace("if(false&&'serviceWorker' in navigator", "if('serviceWorker' in navigator")
        for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
            if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                run("node","--check","-",input=code,text=True)
        index.write_text(html)
        check("from:()=>{throw new Error(" in html and "/api/myr/workspace" in html,"Unexpected frontend")
        prod.mkdir(mode=0o700,parents=True)
        shutil.copytree(REPO/"vps/backend",prod/"vps/backend")
        shutil.copy2(REPO/"config.js",prod/"config.js")
        shutil.copytree(stage,web)
        for p in [web,*web.rglob("*")]:
            p.chmod(0o755 if p.is_dir() else 0o644)
        UNIT.parent.mkdir(parents=True,exist_ok=True)
        UNIT.write_text("[Unit]\nDescription=MYR pinned core production API\n[Service]\nType=simple\nWorkingDirectory="+str(prod/"vps/backend")+"\nEnvironment=MYR_PRODUCTION_RELEASE="+commit+"\nExecStart="+str(PY)+" -B -m uvicorn business_api:api --host 127.0.0.1 --port 8767 --no-proxy-headers\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=yes\nUMask=0077\n[Install]\nWantedBy=default.target\n")
        backup_conf=tmp/"original-nginx"
        backup_conf.write_text(original)
        new_conf=tmp/"new-nginx"
        new_conf.write_text(config)
        # Source credentials entered only in VPS terminal; never logged or stored.
        pw=getpass.getpass("Existing Supabase database password: ")
        key=(HOME/".config/myrinvoice/native-backup-key").read_text().strip()
        check(bool(pw) and len(key)>=32,"Source password and existing backup key required")
        frozen=False
        changed_config=False
        changed_root=False
        stopped_timer=False
        opened=False
        source=None
        try:
            run("systemctl","--user","daemon-reload")
            run("systemctl","--user","start","myr-production-core.service")
            smoke(False)
            check(local_http("/workspace")[0]==401,"Unauthenticated workspace not rejected")
            check(local_http("/links/read",{"p_token":"0"*32})[0]==503,"Public gate not closed")
            source=psycopg.connect(host=HOST,port=5432,dbname="postgres",user="postgres."+PROJECT,
                password=pw,sslmode="verify-full",sslrootcert=str(CA),connect_timeout=10,
                options="-c statement_timeout=60000")
            pw=None
            # Freeze and compare in the SAME source transaction; a mismatch rolls everything back.
            statements=(REPO/"vps/source-freeze-review.sql").read_text()
            statements=statements.replace("BEGIN;","",1).replace("COMMIT;","",1)
            source.execute(statements,prepare=False)
            with connect() as dest:
                dest.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                compare(source,dest)
            snapshot(source,key)
            source.commit()
            frozen=True
            print("MYR_SOURCE_BUSINESS_FROZEN",flush=True)
            stopped_timer=True
            run("systemctl","--user","disable","--now","myr-static-deploy.timer")
            run("systemctl","--user","stop","myr-static-deploy.service")
            # Preserve an independent permanent copy of the prior Nginx configuration.
            run("sudo","cp","-a",CONF,CONF+".pre-vps-core-"+commit[:12])
            changed_config=True
            run("sudo","install","-m","0644",new_conf,CONF)
            run("sudo","nginx","-t")
            switch_link(web)
            changed_root=True
            run("sudo","systemctl","reload","nginx")
            https=["curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","15"]
            page=run(*https,"-fsS","https://myrinvoice.com/",stdout=subprocess.PIPE).stdout
            check(page==(web/"index.html").read_bytes(),"Wrong public website release")
            status=out(*https,"-sS","-o","/dev/null","-w","%{http_code}","https://myrinvoice.com/api/myr/workspace")
            check(status=="401","Public API route did not enforce authentication")
            status=out(*https,"-sS","-o","/dev/null","-w","%{http_code}","https://myrinvoice.com/api/myr/native/auth/preview")
            check(status=="404","Private route exposed")
            run("systemctl","--user","enable","myr-production-core.service")
            # Single irreversible boundary: after this, NEVER auto-thaw source.
            fd=os.open(MARKER,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"w") as m: m.write(commit+"\n")
            opened=True
            smoke(True)
            check(local_http("/links/read",{"p_token":"0"*32})[0]==404,"Invalid public token handling")
            print("MYR_LIVE_CORE_DATABASE_SWITCH_OK",flush=True)
            print("Existing Supabase Auth still verifies login. VPS business writes active. Legacy source frozen. Production auto-publish pinned.",flush=True)
        except BaseException as exc:
            if opened or MARKER.exists():
                print("CUTOVER_NEEDS_OPERATOR_REVIEW: writes may have been accepted; DO NOT thaw source or restore old frontend blindly.",flush=True)
                raise
            # Only before writes can we safely restore the old site/source.
            if changed_root: switch_link(previous)
            if changed_config:
                run("sudo","install","-m","0644",backup_conf,CONF)
                run("sudo","nginx","-t")
                run("sudo","systemctl","reload","nginx")
            if source is not None:
                source.rollback()
                if frozen:
                    source.execute((REPO/"vps/source-thaw-review.sql").read_text(),prepare=False)
                    source.commit()
            if stopped_timer: run("systemctl","--user","enable","--now","myr-static-deploy.timer")
            subprocess.run(["systemctl","--user","disable","--now","myr-production-core.service"],check=False)
            UNIT.unlink(missing_ok=True)
            subprocess.run(["systemctl","--user","daemon-reload"],check=False)
            print("MYR_CORE_CUTOVER_STOPPED_BEFORE_WRITES; previous source retained. Reason:",type(exc).__name__,flush=True)
            if isinstance(exc,RuntimeError): print(str(exc),flush=True)
            raise SystemExit(1) from None
        finally:
            if source is not None: source.close()
if __name__=="__main__": main()
