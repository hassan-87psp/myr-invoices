"""Read-only private VPS health audit. No credentials, customer data or raw logs printed.
Run as myradmin on the VPS. No automatic repair or network transfer.
"""
import hashlib,json,os,re,stat,subprocess,time
from pathlib import Path
H=Path.home(); C=H/".config/myrinvoice"; B=H/"myr-private-backups/native"
MAX_AGE=36*3600
def read_private(path,maxbytes):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        st=os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError("unsafe file")
        data=f.read(maxbytes+1)
        if len(data)>maxbytes:raise ValueError("oversized file")
        return data
def inspect_backups(folder,now):
    if folder.is_symlink() or not folder.is_dir() or folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:
        return {"status":"unsafe_directory"}
    names=sorted(p for p in folder.iterdir() if re.fullmatch(r"native-\d{8}T\d{12}Z\.dump\.gpg",p.name))
    if not names:return {"status":"missing"}
    path=names[-1]
    try:
        expected=read_private(path.with_name(path.name+".sha256"),512).decode("ascii").split()
        if len(expected)!=2 or expected[1]!=path.name or not re.fullmatch("[0-9a-f]{64}",expected[0]):raise ValueError("checksum format")
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,"rb") as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size<=0:raise ValueError("unsafe archive")
            actual=hashlib.file_digest(f,"sha256").hexdigest()
            after=os.fstat(f.fileno())
            if (st.st_size,st.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError("archive changed")
        if actual!=expected[0]:return {"status":"checksum_mismatch"}
        age=now-st.st_mtime
        return {"status":"verified_checksum" if 0<=age<=MAX_AGE else "stale_or_future","age_hours":round(age/3600,1)}
    except (OSError,ValueError,UnicodeError):return {"status":"unverified"}
def unit(name):
    try:return subprocess.run(["systemctl","--user","is-active","--quiet",name],timeout=5,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False
def marker():
    try:
        a=read_private(C/"production-writes-enabled",128).strip()
        b=read_private(C/"native-auth-pilot-enabled",128).strip()
        return bool(re.fullmatch(b"[0-9a-f]{40}",a) and a==b)
    except (OSError,ValueError):return False
def main():
    result={"core_active":unit("myr-production-core.service"),"billing_active":unit("myr-billing-readonly.service"),
            "frontend_auto_active":unit("myr-frontend-autodeploy.timer"),"backup_timer_active":unit("myr-native-backup.timer"),
            "release_markers_match":marker(),"backup":inspect_backups(B,time.time()),
            "offsite_verified":False,"restore_verified_by_this_check":False}
    print(json.dumps(result,indent=2))
    good=all(result[k] for k in ("core_active","billing_active","backup_timer_active","release_markers_match")) and result["backup"]["status"]=="verified_checksum"
    return 0 if good else 1
if __name__=="__main__":raise SystemExit(main())
