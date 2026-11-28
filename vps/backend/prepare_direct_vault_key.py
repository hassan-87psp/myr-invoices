"""Provision empty Sandbox credential vault with separately encrypted key recovery.
No credentials, grants, provider calls, service restarts or production DB writes.
Run once as myradmin; never prints key or passphrase. Operator must separately
copy the encrypted recovery file offsite and verify that copy before pilot approval.
"""
import datetime as dt
import getpass
import os
import secrets
import stat
import sys
import tempfile
import warnings
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from lhdn_direct_vault_candidate import Vault, Scope

H=Path.home()
CONFIG=H/".config/myrinvoice"
ROOT=H/".local/share/myrinvoice/direct-erp-vault"
RECOVERY=H/"myr-private-backups/direct-erp-recovery"
KEY=CONFIG/"direct-erp-vault.key"
WRAPPED=RECOVERY/"sandbox-key-v1.enc"
GRANT=CONFIG/"direct-erp-pilot.json"
MAGIC=b"MYR-DIRECT-ERP-SANDBOX-KEY-v1\0"

def check(ok,message):
    if not ok:raise RuntimeError(message)
def absent(p):return not p.exists() and not p.is_symlink()
def directory(p,create=False):
    if create:p.mkdir(mode=0o700,parents=True,exist_ok=True)
    s=p.lstat()
    check(stat.S_ISDIR(s.st_mode) and s.st_uid==os.getuid() and not(s.st_mode&0o077),"Unsafe private directory")
def read(p,size):
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        s=os.fstat(f.fileno())
        check(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_nlink==1 and not(s.st_mode&0o077),"Unsafe private file")
        raw=f.read(size+1)
        check(len(raw)==size,"Invalid private file length")
        return raw
def new_file(p,data):
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def derive(password,salt):
    return Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password)
def wrap(key,password):
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    return MAGIC+salt+nonce+AESGCM(derive(password,salt)).encrypt(nonce,key,MAGIC)
def unwrap(data,password):
    check(len(data)==len(MAGIC)+76 and data.startswith(MAGIC),"Invalid recovery format")
    raw=data[len(MAGIC):]
    return AESGCM(derive(password,raw[:16])).decrypt(raw[16:28],raw[28:],MAGIC)
def prompt(confirm=False):
    warnings.simplefilter("error",getpass.GetPassWarning)
    p=getpass.getpass("Independent recovery passphrase (hidden): ")
    check(len(p)>=20 and len(p.encode())<=1024,"Use a strong unique passphrase of at least 20 characters")
    if confirm:check(p==getpass.getpass("Repeat recovery passphrase (hidden): "),"Passphrases differ")
    return p.encode()
def rehearse(key):
    with tempfile.TemporaryDirectory(prefix="myr-direct-key-test-") as t:
        root=Path(t)
        scope=Scope("00000000-0000-4000-8000-000000000001","C1234567890","202001234567")
        now=dt.datetime.now(dt.timezone.utc)
        v=Vault(root,key)
        result=v.stage(scope,"synthetic-id","synthetic-secret",(now.date()+dt.timedelta(days=180)).isoformat(),0,now)
        check(result["revision"]==1,"Synthetic vault write failed")
        check(Vault(root,key).status(scope,now)==result,"Synthetic vault recovery failed")
        check(b"synthetic-secret" not in (root/(scope.tenant+".bin")).read_bytes(),"Plaintext leak")
def main():
    os.umask(0o077)
    check(os.getuid()!=0 and os.environ.get("USER")=="myradmin","Run as myradmin")
    check(absent(GRANT),"Existing pilot approval; refuse")
    directory(CONFIG)
    if sys.argv[1:]==["--provision-empty"]:
        check(all(absent(p) for p in (KEY,ROOT,WRAPPED)),"Existing or partial vault setup; refuse overwrite")
        p=prompt(True)
        directory(RECOVERY,True)
        key=secrets.token_bytes(32)
        encrypted=wrap(key,p)
        check(unwrap(encrypted,p)==key,"Recovery verification failed")
        rehearse(key)
        # Recovery artifact exists before activating the local key. Partial
        # failures retain artifacts; never silently replace a vault key.
        new_file(WRAPPED,encrypted)
        check(unwrap(read(WRAPPED,len(encrypted)),p)==key,"Stored recovery verification failed")
        new_file(KEY,key)
        directory(ROOT,True)
        check(Vault.from_private_key(ROOT,CONFIG).root==ROOT and read(KEY,32)==key,"Local key loading failed")
        print("MYR_DIRECT_EMPTY_VAULT_KEY_READY")
    elif sys.argv[1:]==["--verify-recovery"]:
        directory(ROOT);directory(RECOVERY)
        p=prompt()
        key=unwrap(read(WRAPPED,len(MAGIC)+76),p)
        check(key==read(KEY,32),"Recovery does not match current key")
        rehearse(key)
        print("MYR_DIRECT_LOCAL_RECOVERY_VERIFIED")
    else:raise RuntimeError("Use --provision-empty or --verify-recovery")
    print("Encrypted recovery file:",WRAPPED)
    print("Local verification only. Independent offsite copy and restore, ongoing vault backup and pilot approval remain required. Credential entry stays disabled.")
if __name__=="__main__":main()
