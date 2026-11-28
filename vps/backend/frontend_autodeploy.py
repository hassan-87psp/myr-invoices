"""Installed local frontend publisher. Remote manifest is data, never shell/Python.
No sudo, database, API routing, backend deployment or credential changes."""
import fcntl,hashlib,json,os,re,shutil,subprocess,tempfile,time
from pathlib import Path

H=Path.home()
R=H/"myr-invoices"
C=H/".config/myrinvoice"
B=Path("/var/www/myrinvoice.com/auto")
S=C/"frontend-autodeploy"
PIN="4942c9562c5012c75ab75c10f116fefae039d48a"
REF="refs/remotes/origin/myr-ui-release-source"

def call(*args,**kw):
    return subprocess.run([str(x) for x in args],check=True,timeout=60,**kw)
def output(*args):
    return call(*args,stdout=subprocess.PIPE).stdout
def require(ok,message):
    if not ok:raise RuntimeError(message)
def sha(value):
    return hashlib.sha256(value).hexdigest()
def curl(path,*args):
    return output("curl","--noproxy","*","--resolve","myrinvoice.com:443:127.0.0.1","--max-time","10",*args,"https://myrinvoice.com"+path)
def active(name):
    return subprocess.run(["systemctl","--user","is-active","--quiet",name],timeout=10).returncode==0
def guards():
    for marker in ("production-writes-enabled","native-auth-pilot-enabled"):
        require((C/marker).read_text().strip()==PIN,"Production pin changed; review required")
    for stem in ("myr-static-deploy","myr-core-backend-deploy","myr-core-frontend-deploy"):
        require(not active(stem+".timer") and not active(stem+".service"),"Conflicting deployment active")
def health():
    guards()
    data=json.loads(output("curl","--noproxy","*","--max-time","5","-fsS","http://127.0.0.1:8767/health"))
    require(data.get("database")=="vps" and data.get("writes_enabled") is True,"Core health failed")
    for p in ("/api/myr/workspace","/api/myr/native/auth/me"):
        require(curl(p,"-sS","-o","/dev/null","-w","%{http_code}")==b"401","Auth guard failed")
    if active("myr-billing-readonly.service"):
        for p in ("/api/myr/billing/customer?company_id=00000000-0000-0000-0000-000000000000","/api/myr/billing/admin/sandbox"):
            require(curl(p,"-sS","-o","/dev/null","-w","%{http_code}")==b"401","Billing auth guard failed")
def publish(path):
    tmp=B/(".frontend-auto-link-"+str(os.getpid()))
    try:
        tmp.symlink_to(path)
        os.replace(tmp,B/"current")
    finally:tmp.unlink(missing_ok=True)
def write_state(path,obj):
    fd,name=tempfile.mkstemp(dir=S)
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(obj,f,sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)
def apply_release(html,release):
    require(set(release)=={"id","replacements"},"Invalid release")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}",release["id"]) is not None,"Invalid ID")
    pairs=release["replacements"]
    require(isinstance(pairs,list) and 0<len(pairs)<=50,"Invalid replacements")
    for pair in pairs:
        require(set(pair)=={"old","new"},"Invalid replacement")
        old,new=pair["old"],pair["new"]
        require(isinstance(old,str) and isinstance(new,str) and old and new and old!=new,"Invalid patch")
        require(len(old)<=100000 and len(new)<=150000,"Oversize patch")
        if html.count(new)==1:continue
        require(html.count(old)==1,"Patch anchor missing or ambiguous: "+release["id"])
        html=html.replace(old,new,1)
    return html
def main():
    os.umask(0o077)
    require(os.getuid()!=0,"Never run as root")
    guards()
    # Recovery uses the old web root. Never invalidate it while billing is interrupted.
    if (C/"billing-readonly-deploy-recovery").exists() and not active("myr-billing-readonly.service"):
        print("MYR_AUTO_WAIT_BILLING_RECOVERY",flush=True);return
    with (B/"deploy.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        guards()
        if (C/"billing-readonly-deploy-recovery").exists() and not active("myr-billing-readonly.service"):return
        env=dict(os.environ,GIT_TERMINAL_PROMPT="0",GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10")
        url=output("git","-C",R,"remote","get-url","origin").decode().strip()
        require(url in ("git@github.com:hassan-87psp/myr-invoices.git","git@github.com:hassan-87psp/myr-invoices","https://github.com/hassan-87psp/myr-invoices.git","https://github.com/hassan-87psp/myr-invoices","ssh://git@github.com/hassan-87psp/myr-invoices.git"),"Unexpected Git origin; review required")
        call("git","-C",R,"fetch","--quiet","--no-tags","--no-write-fetch-head","origin","refs/heads/main:"+REF,env=env)
        raw=output("git","-C",R,"show",REF+":vps/approved-frontend-releases.json")
        require(len(raw)<=500000,"Manifest too large")
        manifest=json.loads(raw)
        require(set(manifest)=={"version","releases"} and manifest["version"]==1 and isinstance(manifest["releases"],list) and len(manifest["releases"])<=100,"Invalid manifest")
        state=S/"applied.json"
        applied=json.loads(state.read_text()) if state.exists() else {}
        require(isinstance(applied,dict),"Invalid local state")
        revision=sha(raw)
        failed=S/"failed-manifest"
        if failed.exists() and failed.read_text().strip()==revision:return
        ids=[x["id"] for x in manifest["releases"]]
        require(len(ids)==len(set(ids)) and set(applied).issubset(ids),"Release history changed")
        previous=(B/"current").resolve(strict=True)
        require(previous.parent==B/"releases" and previous.is_dir(),"Unexpected web root")
        old=(previous/"index.html").read_text()
        html=old
        for rel in manifest["releases"]:
            digest=sha(json.dumps(rel,sort_keys=True).encode())
            rid=rel["id"]
            if rid in applied:
                require(applied[rid]==digest,"Previously approved release was modified")
            else:
                html=apply_release(html,rel)
                applied[rid]=digest
        if html==old:
            if not state.exists() or json.loads(state.read_text())!=applied:
                write_state(state,applied)
                print("MYR_AUTO_ALREADY_APPLIED",flush=True)
            return
        stage=None
        switched=False
        try:
            health()
            require(not any(p.is_symlink() for p in previous.rglob("*")),"Symlink in web root")
            require(curl("/","-fsS")== (previous/"index.html").read_bytes(),"Live root mismatch")
            for anchor in ("myrNativeAuth","myrAuthHeaders","myr-seo-fallback"):
                require(anchor in old and anchor in html,"Required existing adapter missing")
            require(len(html)<=3000000,"Oversize frontend")
            for attrs,code in re.findall(r"<script([^>]*)>(.*?)</script>",html,re.S|re.I):
                if code.strip() and "application/ld+json" not in attrs and "application/json" not in attrs:
                    call("node","--check","-",input=code,text=True)
            policy={p:curl("/"+p,"-fsSL") for p in ("refund-policy","privacy-policy","shipping-policy")}
            for p,v in policy.items():
                require(('name="myr-policy-page" content="'+p+'"').encode() in v,"Policy page unavailable")
            stage=B/"releases"/("vps-frontend-auto-"+revision[:12]+"-"+str(time.time_ns()))
            mask=os.umask(0o022)
            try:
                shutil.copytree(previous,stage)
                stage.chmod(0o755)
                (stage/"index.html").write_text(html)
                (stage/"index.html").chmod(0o644)
            finally:os.umask(mask)
            require((stage/"config.js").read_bytes()==(previous/"config.js").read_bytes(),"Config changed")
            publish(stage)
            switched=True
            health()
            require(curl("/","-fsS")== (stage/"index.html").read_bytes(),"Published HTML mismatch")
            for p,v in policy.items():require(curl("/"+p,"-fsSL")==v,"Policy page changed")
            write_state(state,applied)
            failed.unlink(missing_ok=True)
            print("MYR_AUTO_FRONTEND_LIVE_OK "+revision[:12],flush=True)
        except BaseException:
            if switched:publish(previous)
            if stage is not None and stage.exists() and (B/"current").resolve()!=stage:
                shutil.rmtree(stage)
            failed.write_text(revision+"\n")
            print("MYR_AUTO_FRONTEND_ROLLED_BACK; new manifest required to retry",flush=True)
            raise
if __name__=="__main__":main()
