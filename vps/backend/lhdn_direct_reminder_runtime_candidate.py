"""Private one-company Sandbox expiry reminder runtime, not installed.

Default is disabled. Separate opt-in grant is required, bound to the current
owner, company identity and version. The grant must be renewed explicitly.
No real credentials, tokens or email addresses are printed. No LHDN calls.
"""
import datetime as dt
import json, os, re, sqlite3, ssl, stat, sys, unittest
from pathlib import Path
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler
from uuid import UUID
from lhdn_direct_reminder_job_candidate import run
from lhdn_direct_reminder_outbox_candidate import Outbox

ROOT=Path.home()/".local/share/myrinvoice/direct-erp-reminders"
GATE="direct-erp-reminder-optin.json"
URL="https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-transactional-mail"
UTC=dt.timezone.utc
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None

def require(ok,msg):
    if not ok:raise ValueError(msg)
def grant(raw,now):
    def unique(items):
        d={}
        for k,v in items:
            require(k not in d,"Duplicate configuration field")
            d[k]=v
        return d
    d=json.loads(raw,object_pairs_hook=unique)
    require(type(d) is dict and set(d)=={"environment","enabled","owner_opt_in","tenant","owner","tin","brn","version","expires_at"},"Invalid opt-in grant")
    require(d["environment"]=="sandbox" and d["enabled"] is True and d["owner_opt_in"] is True,"Disabled")
    for k in ("tenant","owner"):require(str(UUID(d[k]))==d[k],"Invalid identifier")
    require(type(d["version"]) is int and d["version"]>=0,"Invalid revision")
    require(re.fullmatch(r"[A-Z]{1,3}[0-9]{1,20}",d["tin"]) and re.fullmatch(r"[A-Z0-9-]{1,40}",d["brn"]),"Invalid scope")
    require(d["expires_at"].endswith("Z"),"UTC expiry required")
    expiry=dt.datetime.fromisoformat(d["expires_at"].replace("Z","+00:00"))
    require(dt.timedelta(0)<expiry-now<=dt.timedelta(days=90),"Grant expired or too broad")
    return d

def resolve(g,connect,read_status,read_grant,clock):
    if read_grant()!=g:return None
    with connect() as c:
        rows=c.execute("""SELECT u.email FROM myr_native.companies co
          JOIN myr_native.company_members m ON m.company_id=co.id
          JOIN myr_native.users u ON u.email=m.email
          WHERE co.id=%s AND co.tin=%s AND co.data->>'brn'=%s
          AND co.version=%s AND co.status='active'
          AND co.data->>'demo' IS DISTINCT FROM 'true'
          AND co.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
          AND u.id=%s AND u.disabled=false AND u.email_verified_at IS NOT NULL
          AND NOT u.is_platform_admin AND m.role='Owner' AND m.status='active'
          FOR SHARE OF co,m,u""",(UUID(g["tenant"]),g["tin"],g["brn"],g["version"],UUID(g["owner"]))).fetchall()
        if len(rows)!=1:return None
        status=read_status(g,clock())
        if read_grant()!=g:return None
        return rows[0][0],status

def open_outbox():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    s=ROOT.lstat()
    require(stat.S_ISDIR(s.st_mode) and s.st_uid==os.getuid() and not(s.st_mode&0o077),"Unsafe outbox directory")
    p=ROOT/"events.sqlite3"
    fd=os.open(p,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        s=os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_nlink==1 and not(s.st_mode&0o077),"Unsafe outbox file")
    finally:os.close(fd)
    db=sqlite3.connect(p,timeout=5)
    db.execute("PRAGMA synchronous=FULL")
    return db

def gateway(payload,key,read_secret):
    secret=read_secret("supabase-mail-api-secret").strip()
    require(re.fullmatch(r"[a-f0-9]{64}",secret),"Invalid gateway configuration")
    require(payload["event"]=="direct_erp_expiry","Invalid event")
    req=Request(URL,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","X-MYR-Mail-Secret":secret},method="POST")
    opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(req,timeout=40) as res:
        raw=res.read(8193)
        require(len(raw)<=8192,"Oversized response")
        return res.status==200 and json.loads(raw).get("accepted") is True

def main():
    # No startup hooks and no automatic opt-in. Never install this from a
    # frontend updater. Deploy only with reviewed service, mail release and
    # verified offsite restore/outbox retention.
    if sys.argv[1:]!=["--run-approved-sandbox"]:
        print("MYR_DIRECT_REMINDER_DISABLED");return
    import business_lhdn as central
    from app import connect
    from lhdn_direct_vault_candidate import Scope,Vault
    clock=lambda:dt.datetime.now(UTC)
    def read_grant():return grant(central.private_text(GATE),clock())
    g=read_grant()
    def read_status(g,now):
        v=Vault.from_private_key(Path.home()/".local/share/myrinvoice/direct-erp-vault",central.CONFIG)
        return v.status(Scope(g["tenant"],g["tin"],g["brn"]),now)
    db=open_outbox()
    try:
        outcome=run(g["tenant"],Outbox(db),lambda _:resolve(g,connect,read_status,read_grant,clock),
                    lambda p,k:gateway(p,k,central.private_text),clock,True)
        print("MYR_DIRECT_REMINDER_RESULT",outcome)
    finally:db.close()

class Tests(unittest.TestCase):
    def test_grant(self):
        now=dt.datetime(2026,11,28,tzinfo=UTC)
        g={"environment":"sandbox","enabled":True,"owner_opt_in":True,"tenant":str(UUID(int=1)),"owner":str(UUID(int=2)),"tin":"C1234567890","brn":"202001234567","version":1,"expires_at":"2026-12-01T00:00:00Z"}
        self.assertEqual(grant(json.dumps(g),now),g)
        for change in ({"enabled":False},{"owner_opt_in":False},{"environment":"production"},{"expires_at":"2027-12-01T00:00:00Z"}):
            with self.assertRaises(ValueError):grant(json.dumps(g|change),now)
    def test_revoked_before_read(self):
        self.assertIsNone(resolve({},lambda:self.fail("No DB"),lambda *a:self.fail("No vault"),lambda:{"changed":True},lambda:None))
if __name__=="__main__":
    if sys.argv[1:]==["--test"]:unittest.main(argv=[sys.argv[0]])
    else:
        try:main()
        except Exception:
            print("MYR_DIRECT_REMINDER_REVIEW_REQUIRED",file=sys.stderr)
            sys.exit(1)
