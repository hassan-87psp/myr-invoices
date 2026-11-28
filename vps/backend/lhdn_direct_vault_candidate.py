"""Private encrypted Direct ERP storage candidate. Sandbox only.
No customer route, production secret, or submission capability is installed.
The owner authorization check belongs to the future server route, not the
vault. A successful OAuth login / public TIN lookup is not issuer binding.
"""
import base64, contextlib, datetime as dt, fcntl, json, os, re, stat, tempfile, unittest
from pathlib import Path
from uuid import UUID
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from lhdn_direct_candidate import credentials
from lhdn_protocol_candidate import require, _unique_object

MAX_FILE=16384
UTC=dt.timezone.utc
def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode("ascii")
def utc(value):
    require(isinstance(value,dt.datetime) and value.tzinfo is not None,"UTC clock required")
    return value.astimezone(UTC)
def date_value(value):
    require(isinstance(value,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",value),"Invalid expiry date")
    return dt.date.fromisoformat(value)

class Scope:
    def __init__(self,tenant,tin,brn,environment="sandbox"):
        require(environment=="sandbox","Sandbox only")
        require(str(UUID(str(tenant)))==str(tenant),"Invalid tenant")
        require(isinstance(tin,str) and re.fullmatch(r"[A-Z]{1,3}[0-9]{1,20}",tin),"Invalid TIN")
        require(isinstance(brn,str) and re.fullmatch(r"[A-Z0-9-]{1,40}",brn),"Invalid BRN")
        self.tenant=str(tenant);self.tin=tin;self.brn=brn
    def aad(self):
        return canonical({"format":1,"purpose":"myr-direct-erp","environment":"sandbox","tenant":self.tenant,"tin":self.tin,"brn":self.brn})

def check_private(st,directory=False):
    require((stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode)) and st.st_uid==os.getuid() and not(st.st_mode&0o077),"Unsafe private storage")
    if not directory:require(st.st_nlink==1,"Unsafe linked file")

def read_private(fd,name,limit):
    f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    with os.fdopen(f,"rb") as stream:
        check_private(os.fstat(stream.fileno()))
        data=stream.read(limit+1)
        require(len(data)<=limit,"Private data too large")
        return data

class Vault:
    """AES-256-GCM with unique random nonces and authenticated tenant identity.
    Dedicated 0700 root, 0600 key/lock/record files, atomic replacement and
    flock serialization. No plaintext credential files or token persistence.
    Keys remain in separate owner-managed private configuration; the backup
    and rotation policy must be approved before live deployment.
    """
    def __init__(self,root,key):
        require(type(key) is bytes and len(key)==32,"AES-256 key required")
        self.root=Path(root)
        self._cipher=AESGCM(key)
    @classmethod
    def from_private_key(cls,root,key_directory,key_name="direct-erp-vault.key"):
        require(key_name=="direct-erp-vault.key","Unexpected key name")
        fd=os.open(key_directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            check_private(os.fstat(fd),True)
            key=read_private(fd,key_name,32)
        finally:os.close(fd)
        return cls(root,key)
    @contextlib.contextmanager
    def _locked(self,scope):
        require(isinstance(scope,Scope),"Validated scope required")
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        lock=None
        try:
            check_private(os.fstat(fd),True)
            lock=os.open(scope.tenant+".lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
            check_private(os.fstat(lock))
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield fd,scope.tenant+".bin"
        finally:
            if lock is not None:os.close(lock)
            os.close(fd)
    def _read(self,fd,name,scope):
        try:raw=read_private(fd,name,MAX_FILE)
        except FileNotFoundError:return None
        require(len(raw)>=29 and raw[0]==1,"Invalid credential record")
        try:
            data=json.loads(self._cipher.decrypt(raw[1:13],raw[13:],scope.aad()),object_pairs_hook=_unique_object)
        except (InvalidTag,ValueError,TypeError):raise ValueError("Credential record unavailable or identity changed") from None
        require(isinstance(data,dict) and type(data.get("revision")) is int and data["revision"]>=1,"Invalid credential record")
        return data
    def _write(self,fd,name,scope,data):
        nonce=os.urandom(12)
        raw=b"\x01"+nonce+self._cipher.encrypt(nonce,canonical(data),scope.aad())
        require(len(raw)<=MAX_FILE,"Credential record too large")
        tmp=".tmp-"+os.urandom(16).hex()
        try:
            f=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            with os.fdopen(f,"wb") as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
        finally:
            try:os.unlink(tmp,dir_fd=fd)
            except FileNotFoundError:pass
    def _revision(self,data,expected):
        require(type(expected) is int and expected>=0 and expected==(data["revision"] if data else 0),"Credential revision changed")
    def stage(self,scope,client_id,client_secret,expiry,expected,now):
        """Store only unverified, disabled pilot credentials, never select a mode.
        Future caller MUST authenticate active company Owner, confirm explicit
        consent, read current TIN/BRN server-side and enforce pilot approval.
        """
        now=utc(now);client_id,client_secret=credentials(client_id,client_secret)
        end=date_value(expiry)
        local=now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
        require(local<end<=local+dt.timedelta(days=1097),"Expiry must be in the future, within three years")
        with self._locked(scope) as (fd,name):
            old=self._read(fd,name,scope);self._revision(old,expected)
            require(not (old and old.get("probe_claim")),"Previous verification needs review before replacement")
            record={"revision":expected+1,"client_id":client_id,"client_secret":client_secret,"expiry":end.isoformat(),"state":"pending_identity_review","updated":now.isoformat(),
                    "probe_after":old.get("probe_after",0) if old else 0,"probe_blocked":bool(old and old.get("probe_blocked"))}
            self._write(fd,name,scope,record)
            return self._status(record,now)
    def disconnect(self,scope,expected,now):
        """Replace record with encrypted tombstone; old revision cannot replay.
        Does not revoke credentials at LHDN or erase historic backups."""
        now=utc(now)
        with self._locked(scope) as (fd,name):
            old=self._read(fd,name,scope);self._revision(old,expected)
            require(old is not None,"No credential record")
            record={"revision":expected+1,"state":"disconnected","updated":now.isoformat(),
                    "probe_after":old.get("probe_after",0),"probe_blocked":bool(old.get("probe_claim") or old.get("probe_blocked"))}
            self._write(fd,name,scope,record)
            return self._status(record,now)
    def probe_staged(self,scope,expected,now,approve,probe):
        """Staged operator orchestration, not a public route.
        A caller supplies an authorization check and a bounded provider adapter.
        A persisted claim precedes any network attempt. An interrupted check
        requires operator review, never an automatic retry. No tokens returned.
        """
        now=utc(now)
        require(callable(approve) and callable(probe),"Explicit operator approval and adapter required")
        require(approve(scope) is True,"Pilot approval required")
        with self._locked(scope) as (fd,name):
            old=self._read(fd,name,scope);self._revision(old,expected)
            require(old is not None and old["state"]=="pending_identity_review","Pending credential record required")
            require(self._status(old,now)["status"]!="expired","Credentials expired")
            require(not old.get("probe_claim"),"Previous check needs operator review")
            require(not old.get("probe_blocked"),"Previous check needs operator review")
            require(now.timestamp()>=old.get("probe_after",0),"Provider backoff active")
            if not approve(scope):raise ValueError("Pilot approval required")
            # Store a durable claim before releasing the lock or calling the provider.
            claimed={**old,"revision":expected+1,"probe_claim":True,"updated":now.isoformat()}
            self._write(fd,name,scope,claimed)
        try:
            result=probe(scope,claimed["client_id"],claimed["client_secret"])
            require(isinstance(result,dict) and set(result).issuperset({"environment","mode","login_status","tin_brn_lookup_verified","issuer_binding_verified","submission_enabled"}),"Invalid verification")
            require(result["environment"]=="sandbox" and result["mode"]=="direct_erp" and result["issuer_binding_verified"] is False and result["submission_enabled"] is False,"Unexpected verification capability")
            login=result["login_status"]
            require(login in ("login_verified","cached_login","credentials_rejected","rate_limited","provider_unavailable","invalid_provider_response"),"Unexpected verification result")
            matched=result["tin_brn_lookup_verified"] is True and login in ("login_verified","cached_login")
            # The adapter must provide a durable retry deadline for throttled calls.
            # If it cannot, require operator review rather than retry prematurely.
            limited=login=="rate_limited" or result.get("lookup_status")=="rate_limited"
        except Exception:
            login="provider_unavailable";matched=False;limited=True
        with self._locked(scope) as (fd,name):
            current=self._read(fd,name,scope)
            self._revision(current,expected+1)
            require(current.get("probe_claim") is True,"Verification claim changed")
            require(approve(scope) is True,"Pilot approval changed")
            # A successful login and public lookup do NOT establish issuer ownership.
            record={**current,"revision":expected+2,"probe_claim":False,"probe_blocked":limited,
                    "probe_after":now.timestamp()+120,"last_login_status":login,
                    "tin_brn_lookup_verified":matched,"updated":now.isoformat()}
            self._write(fd,name,scope,record)
            return self._status(record,now)
    def _status(self,record,now):
        out={"environment":"sandbox","mode":"direct_erp","revision":0,"status":"not_configured","expiry":None,"days_remaining":None,"reminder_stage":None,"issuer_binding_verified":False,"submission_enabled":False}
        if record is None:return out
        out.update(revision=record["revision"],status=record["state"],last_login_status=record.get("last_login_status"),tin_brn_lookup_verified=record.get("tin_brn_lookup_verified") is True,verification_review_required=bool(record.get("probe_claim") or record.get("probe_blocked")))
        if record["state"]=="disconnected":return out
        expiry=date_value(record["expiry"])
        local=utc(now).astimezone(dt.timezone(dt.timedelta(hours=8))).date()
        days=(expiry-local).days
        stage="expired" if days<=0 else "1_day" if days<=1 else "7_days" if days<=7 else "30_days" if days<=30 else None
        out.update(expiry=expiry.isoformat(),days_remaining=max(0,days),reminder_stage=stage)
        if days<=0:out["status"]="expired"
        return out
    def status(self,scope,now):
        now=utc(now)
        with self._locked(scope) as (fd,name):return self._status(self._read(fd,name,scope),now)

class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.key=os.urandom(32)
        self.v=Vault(self.root,self.key)
        self.s=Scope("00000000-0000-4000-8000-000000000001","C1234567890","202001234567")
        self.now=dt.datetime(2026,11,28,4,tzinfo=UTC)
        self.expiry="2027-11-28"
        self.path=self.root/(self.s.tenant+".bin")
    def store(self,expected=0,secret="synthetic-secret"):
        return self.v.stage(self.s,"synthetic-id",secret,self.expiry,expected,self.now)
    def test_encryption_redaction(self):
        status=self.store()
        self.assertEqual(status["status"],"pending_identity_review")
        self.assertFalse(status["submission_enabled"]);self.assertFalse(status["issuer_binding_verified"])
        self.assertNotIn(b"synthetic-secret",self.path.read_bytes())
        self.assertNotIn(b"synthetic-id",self.path.read_bytes())
        self.assertNotIn("synthetic",str(status))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
        self.assertEqual(Vault(self.root,self.key).status(self.s,self.now),status)
    def test_scope_and_wrong_key(self):
        self.store()
        wrong=Scope(self.s.tenant,"C9876543210",self.s.brn)
        with self.assertRaises(ValueError):self.v.status(wrong,self.now)
        with self.assertRaises(ValueError):Vault(self.root,os.urandom(32)).status(self.s,self.now)
        other=Scope("00000000-0000-4000-8000-000000000002",self.s.tin,self.s.brn)
        self.assertEqual(self.v.status(other,self.now)["status"],"not_configured")
        (self.root/(other.tenant+".bin")).write_bytes(self.path.read_bytes())
        (self.root/(other.tenant+".bin")).chmod(0o600)
        with self.assertRaises(ValueError):self.v.status(other,self.now)
    def test_tamper(self):
        self.store()
        data=bytearray(self.path.read_bytes());data[-1]^=1;self.path.write_bytes(data)
        with self.assertRaises(ValueError):self.v.status(self.s,self.now)
    def test_revision_rotation_disconnect(self):
        self.store();old=self.path.read_bytes()
        self.assertEqual(self.store(1,"new-synthetic-secret")["revision"],2)
        self.assertNotEqual(old,self.path.read_bytes())
        with self.assertRaises(ValueError):self.store(1)
        status=self.v.disconnect(self.s,2,self.now)
        self.assertEqual(status["status"],"disconnected")
        self.assertEqual(status["revision"],3)
        self.assertIsNone(status["expiry"])
        with self.assertRaises(ValueError):self.store(2)
        self.assertEqual(self.store(3)["revision"],4)
    def test_expiry(self):
        self.store()
        for days,stage in [(31,None),(30,"30_days"),(7,"7_days"),(1,"1_day"),(0,"expired")]:
            now=dt.datetime(2027,11,28,4,tzinfo=UTC)-dt.timedelta(days=days)
            self.assertEqual(self.v.status(self.s,now)["reminder_stage"],stage)
        self.assertEqual(self.v.status(self.s,dt.datetime(2027,11,28,4,tzinfo=UTC))["status"],"expired")
        with self.assertRaises(ValueError):self.v.stage(self.s,"id","secret","2020-01-01",1,self.now)
    def test_permissions_and_symlink(self):
        self.store();self.path.chmod(0o644)
        with self.assertRaises(ValueError):self.v.status(self.s,self.now)
        self.path.unlink();self.path.symlink_to("/dev/null")
        with self.assertRaises(OSError):self.v.status(self.s,self.now)
    def test_private_key_loading(self):
        k=self.root/"direct-erp-vault.key";k.write_bytes(self.key);k.chmod(0o600)
        self.store()
        self.assertEqual(Vault.from_private_key(self.root,self.root).status(self.s,self.now)["revision"],1)
        k.chmod(0o644)
        with self.assertRaises(ValueError):Vault.from_private_key(self.root,self.root)
    def test_probe_is_pending_only(self):
        self.store()
        calls=[]
        def check(scope,i,s):
            calls.append((scope.tenant,i,s))
            self.assertTrue(self.v.status(scope,self.now)["verification_review_required"])
            return {"environment":"sandbox","mode":"direct_erp","login_status":"login_verified","tin_brn_lookup_verified":True,"issuer_binding_verified":False,"submission_enabled":False}
        with self.assertRaises(ValueError):self.v.probe_staged(self.s,1,self.now,lambda s:False,check)
        self.assertEqual(calls,[])
        result=self.v.probe_staged(self.s,1,self.now,lambda s:True,check)
        self.assertEqual(len(calls),1)
        self.assertEqual(result["revision"],3)
        self.assertTrue(result["tin_brn_lookup_verified"])
        self.assertFalse(result["issuer_binding_verified"])
        self.assertFalse(result["submission_enabled"])
        self.assertEqual(result["status"],"pending_identity_review")
        self.assertNotIn("synthetic-secret",str(result))
        with self.assertRaises(ValueError):self.v.probe_staged(self.s,3,self.now,lambda s:True,check)
    def test_probe_failure_blocks(self):
        self.store()
        def fail(*args):raise RuntimeError("synthetic private value")
        result=self.v.probe_staged(self.s,1,self.now,lambda s:True,fail)
        self.assertTrue(result["verification_review_required"])
        self.assertNotIn("synthetic private value",str(result))
        with self.assertRaises(ValueError):self.v.probe_staged(self.s,3,self.now+dt.timedelta(days=1),lambda s:True,fail)
        self.v.disconnect(self.s,3,self.now)
        self.store(4,"replacement")
        with self.assertRaises(ValueError):self.v.probe_staged(self.s,5,self.now+dt.timedelta(days=1),lambda s:True,fail)
    def test_revocation_during_probe(self):
        self.store()
        active=[True]
        def check(*args):
            active[0]=False
            return {"environment":"sandbox","mode":"direct_erp","login_status":"login_verified","tin_brn_lookup_verified":True,"issuer_binding_verified":False,"submission_enabled":False}
        with self.assertRaises(ValueError):self.v.probe_staged(self.s,1,self.now,lambda s:active[0],check)
        result=self.v.status(self.s,self.now)
        self.assertTrue(result["verification_review_required"])
        self.assertFalse(result["issuer_binding_verified"])
    def test_sandbox_only(self):
        with self.assertRaises(ValueError):Scope(self.s.tenant,self.s.tin,self.s.brn,"production")
if __name__=="__main__":unittest.main()
