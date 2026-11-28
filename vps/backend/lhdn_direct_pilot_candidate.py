"""Owner-scoped Direct ERP Sandbox pilot orchestration.
No production submission, no implicit credential acceptance or issuer binding.
Requires an explicit private release/tenant/owner/version grant and reviewed
vault key/recovery configuration. The HTTP adapter supplies native identity.
"""
import datetime as dt
import json,os,re,unittest
from pathlib import Path
from uuid import UUID
from unittest.mock import Mock
import business_lhdn as central
from lhdn_direct_candidate import DirectSession
from lhdn_direct_vault_candidate import Vault,Scope
from lhdn_protocol_candidate import require,_unique_object

UTC=dt.timezone.utc
ROOT=Path.home()/".local/share/myrinvoice/direct-erp-vault"
def now():return dt.datetime.now(UTC)

def allowed(scope,owner,version,clock=now,read=central.private_text):
    try:
        release=os.environ.get("MYR_PRODUCTION_RELEASE","")
        if not re.fullmatch(r"[a-f0-9]{40}",release):return False
        d=json.loads(read("direct-erp-pilot.json"),object_pairs_hook=_unique_object)
        if set(d)!={"release","environment","credential_storage_reviewed","backup_recovery_reviewed","pilots"}:return False
        if d["release"]!=release or d["environment"]!="sandbox" or d["credential_storage_reviewed"] is not True or d["backup_recovery_reviewed"] is not True:return False
        # At most one pilot until cross-client distributed throttling is released.
        pilots=d["pilots"]
        if not isinstance(pilots,dict) or len(pilots)!=1:return False
        p=pilots.get(scope.tenant)
        if not isinstance(p,dict) or set(p)!={"owner","version","tin","brn","expires_at"}:return False
        if p["owner"]!=str(owner) or type(p["version"]) is not int or p["version"]!=version or p["tin"]!=scope.tin or p["brn"]!=scope.brn:return False
        expiry=dt.datetime.fromisoformat(p["expires_at"].replace("Z","+00:00"))
        return p["expires_at"].endswith("Z") and dt.timedelta(0)<expiry-clock()<=dt.timedelta(hours=24)
    except (OSError,ValueError,TypeError,KeyError,AttributeError):return False

def vault():return Vault.from_private_key(ROOT,central.CONFIG)
def unavailable():return {"environment":"sandbox","mode":"direct_erp","available":False,"status":"pilot_unavailable","issuer_binding_verified":False,"submission_enabled":False}
def provider(scope,client_id,client_secret):
    return DirectSession(scope.tenant,client_id,client_secret).probe(scope.tin,scope.brn)

def handle(scope,owner,version,body,approve=allowed,open_vault=vault,probe=provider,clock=now):
    # All body data is untrusted. No server identity can be supplied by the client.
    require(isinstance(body,dict),"Invalid request")
    action=body.get("action")
    fields={"status":{"action","p_company_id","p_version"},"save":{"action","p_company_id","p_version","revision","client_id","client_secret","expiry","consent"},"verify":{"action","p_company_id","p_version","revision"},"disconnect":{"action","p_company_id","p_version","revision"}}
    require(isinstance(action,str) and action in fields and set(body)==fields[action],"Invalid request")
    require(body["p_company_id"]==scope.tenant and type(body["p_version"]) is int and body["p_version"]==version,"Company revision changed")
    if not approve(scope,owner,version):return unavailable()
    v=open_vault()
    check=lambda s:approve(s,owner,version)
    if action=="status":return {**v.status(scope,clock()),"available":True}
    revision=body["revision"]
    require(type(revision) is int and 0<=revision<=2**53-1,"Invalid revision")
    if action=="disconnect":return {**v.disconnect(scope,revision,clock()),"available":True}
    if action=="save":
        require(body["consent"] is True,"Explicit owner consent required")
        result=v.stage(scope,body["client_id"],body["client_secret"],body["expiry"],revision,clock())
        revision=result["revision"]
        # Automatically perform a bounded verification after staging. If a
        # previously persisted rate limit/review prevents it, retain pending status.
        if result.get("verification_review_required"):return {**result,"available":True}
    try:
        result=v.probe_staged(scope,revision,clock(),check,probe)
    except ValueError:
        # Never report verified on a stale request, revoked grant or failed claim.
        if not check(scope):return unavailable()
        result=v.status(scope,clock())
        return {**result,"available":True,"verification_deferred":True}
    if not check(scope):return unavailable()
    return {**result,"available":True}

class PilotTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Scope("00000000-0000-4000-8000-000000000001","C1234567890","202001234567")
        self.owner=UUID(int=2);self.version=3;self.t=dt.datetime(2026,11,28,3,tzinfo=UTC)
        self.v=Vault(Path(self.tmp.name),os.urandom(32))
        self.approve=Mock(return_value=True);self.open=Mock(return_value=self.v)
        self.probe=Mock(return_value={"environment":"sandbox","mode":"direct_erp","login_status":"login_verified","tin_brn_lookup_verified":True,"issuer_binding_verified":False,"submission_enabled":False})
    def call(self,action,**data):
        return handle(self.s,self.owner,self.version,{"action":action,"p_company_id":self.s.tenant,"p_version":self.version,**data},self.approve,self.open,self.probe,lambda:self.t)
    def save(self,**changes):
        return self.call("save",**({"revision":0,"client_id":"synthetic-id","client_secret":"synthetic-secret","expiry":"2027-11-28","consent":True}|changes))
    def test_default_unavailable(self):
        self.approve.return_value=False
        self.assertFalse(self.call("status")["available"])
        self.assertFalse(self.save()["available"])
        self.open.assert_not_called();self.probe.assert_not_called()
    def test_save_auto_probe_disconnect(self):
        self.assertEqual(self.call("status")["status"],"not_configured")
        x=self.save()
        self.assertEqual(x["revision"],3);self.assertEqual(x["status"],"pending_identity_review")
        self.assertTrue(x["tin_brn_lookup_verified"]);self.assertFalse(x["issuer_binding_verified"])
        self.assertFalse(x["submission_enabled"]);self.assertNotIn("synthetic-secret",str(x))
        self.probe.assert_called_once()
        self.assertEqual(self.call("disconnect",revision=3)["status"],"disconnected")
        self.probe.assert_called_once()
    def test_consent_and_stale_revision(self):
        with self.assertRaises(ValueError):self.save(consent=False)
        self.probe.assert_not_called()
        self.save()
        with self.assertRaises(ValueError):self.save()
        self.assertEqual(self.probe.call_count,1)
    def test_invalid_fields_and_version(self):
        with self.assertRaises(ValueError):self.call("status",client_secret="never-echo")
        with self.assertRaises(ValueError):handle(self.s,self.owner,self.version,{"action":"status","p_company_id":self.s.tenant,"p_version":2},self.approve,self.open,self.probe,lambda:self.t)
        self.open.assert_not_called()
    def test_grant_exact_scope(self):
        from unittest.mock import patch
        release="a"*40
        d={"release":release,"environment":"sandbox","credential_storage_reviewed":True,"backup_recovery_reviewed":True,"pilots":{self.s.tenant:{"owner":str(self.owner),"version":3,"tin":self.s.tin,"brn":self.s.brn,"expires_at":"2026-11-28T04:00:00Z"}}}
        with patch.dict(os.environ,{"MYR_PRODUCTION_RELEASE":release}):
            def check(owner=self.owner,version=3):return allowed(self.s,owner,version,lambda:self.t,lambda _:json.dumps(d))
            self.assertTrue(check());self.assertFalse(check(UUID(int=4)));self.assertFalse(check(version=4))
            d["backup_recovery_reviewed"]=False;self.assertFalse(check())
            d["backup_recovery_reviewed"]=True;d["pilots"][self.s.tenant]["expires_at"]="2026-11-27T04:00:00Z";self.assertFalse(check())
if __name__=="__main__":unittest.main()
