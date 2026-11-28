"""Local encrypted-record snapshots for the one-company Direct ERP Sandbox pilot.
No key, passphrase, plaintext credential, database or provider access.
Only local backup; offsite retention and restore are separate requirements.
"""
import base64, datetime as dt, fcntl, hashlib, json, os, re, stat, sys, tempfile
from pathlib import Path
from uuid import UUID

HOME=Path.home()
ROOT=HOME/".local/share/myrinvoice/direct-erp-vault"
DEST=HOME/"myr-private-backups/direct-erp-vault"
LIMIT=16384
NAME=re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.bin")
def check(ok,msg):
    if not ok:raise RuntimeError(msg)
def private(st,dir=False):
    check((stat.S_ISDIR(st.st_mode) if dir else stat.S_ISREG(st.st_mode)) and st.st_uid==os.getuid() and not(st.st_mode&0o077),"Unsafe backup path")
    if not dir:check(st.st_nlink==1,"Unexpected hardlink")
def read(fd,name,limit):
    f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    with os.fdopen(f,"rb") as stream:
        private(os.fstat(stream.fileno()))
        data=stream.read(limit+1)
        check(len(data)<=limit,"Oversized record")
        return data
def snapshot(root,dest):
    rootfd=os.open(root,os.O_DIRECTORY|os.O_NOFOLLOW|os.O_RDONLY)
    destfd=None
    lock=None
    try:
        private(os.fstat(rootfd),True)
        dest.mkdir(mode=0o700,parents=True,exist_ok=True)
        destfd=os.open(dest,os.O_DIRECTORY|os.O_NOFOLLOW|os.O_RDONLY)
        private(os.fstat(destfd),True)
        lock=os.open(".backup.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=destfd)
        private(os.fstat(lock))
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def names():return sorted(n for n in os.listdir(rootfd) if n.endswith(".bin"))
        initial=names()
        check(len(initial)<=1 and all(NAME.fullmatch(n) for n in initial),"Single-company pilot scope changed")
        records=[]
        for name in initial:
            lk=os.open(name[:-4]+".lock",os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=rootfd)
            try:
                private(os.fstat(lk))
                fcntl.flock(lk,fcntl.LOCK_SH)
                raw=read(rootfd,name,LIMIT)
                check(len(raw)>=29 and raw[0]==1,"Invalid encrypted record format")
                records.append({"name":name,"sha256":hashlib.sha256(raw).hexdigest(),"ciphertext":base64.b64encode(raw).decode("ascii")})
            finally:os.close(lk)
        check(names()==initial,"Vault record set changed; retry snapshot")
        payload=json.dumps({"format":1,"environment":"sandbox","records":records},sort_keys=True,separators=(",",":")).encode()
        stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        final="vault-"+stamp+".json"
        # Private atomic publish; never overwrite old snapshots.
        with tempfile.NamedTemporaryFile(dir=dest,delete=False) as f:
            tmp=Path(f.name)
            try:
                f.write(payload);f.flush();os.fsync(f.fileno())
                os.link(tmp,dest/final)
            finally:tmp.unlink(missing_ok=True)
        os.fsync(destfd)
        check(read(destfd,final,65536)==payload,"Snapshot readback failed")
        return dest/final,len(records)
    finally:
        if lock is not None:os.close(lock)
        if destfd is not None:os.close(destfd)
        os.close(rootfd)
def rehearsal():
    from lhdn_direct_vault_candidate import Vault,Scope
    with tempfile.TemporaryDirectory() as d:
        base=Path(d);root=base/"vault";root.mkdir(mode=0o700)
        key=os.urandom(32)
        scope=Scope(str(UUID(int=1)),"C1234567890","202001234567")
        now=dt.datetime.now(dt.timezone.utc)
        v=Vault(root,key)
        expected=v.stage(scope,"synthetic-id","synthetic-secret",(now.date()+dt.timedelta(days=180)).isoformat(),0,now)
        backup,count=snapshot(root,base/"backups")
        obj=json.loads(backup.read_bytes())
        check(count==1 and b"synthetic-secret" not in backup.read_bytes(),"Snapshot confidentiality test failed")
        record=obj["records"][0]
        raw=base64.b64decode(record["ciphertext"],validate=True)
        check(hashlib.sha256(raw).hexdigest()==record["sha256"],"Record checksum failed")
        restored=base/"restored";restored.mkdir(mode=0o700)
        p=restored/record["name"];p.write_bytes(raw);p.chmod(0o600)
        check(Vault(restored,key).status(scope,now)==expected,"Synthetic restore failed")
        print("MYR_DIRECT_VAULT_BACKUP_REHEARSAL_OK")
def main():
    os.umask(0o077)
    check(os.getuid()!=0,"Never run as root")
    if sys.argv[1:]==["--rehearse"]:rehearsal()
    elif sys.argv[1:]==["--backup"]:
        path,count=snapshot(ROOT,DEST)
        print("MYR_DIRECT_LOCAL_VAULT_BACKUP_OK", "records="+str(count))
        print("Ciphertext snapshot only; offsite restore and retention remain separate.")
    else:raise RuntimeError("Use --rehearse or --backup")
if __name__=="__main__":main()
