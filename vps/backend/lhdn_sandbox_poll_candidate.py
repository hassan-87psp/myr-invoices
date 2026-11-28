"""Private, staged Sandbox polling orchestration. Never mounts a public route.
Uses only a separately isolated worker DB and exact operator grant. A committed
poll claim is required before the read-only provider call. No submission retry.
"""
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
from hashlib import sha256
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
import json,re,ssl,unittest
from unittest.mock import patch,Mock
import business_lhdn as central
from lhdn_sandbox_dispatch_candidate import check_database,bind
from lhdn_lifecycle_candidate import scoped,sync,poll_plan
from lhdn_protocol_candidate import require,parse_time,_unique_object

URL="https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-lhdn-sandbox-poll"
TABLE="myr_native.lhdn_submission_intents"
FIELDS={"tenant_id","taxpayer","code_number","document_hash","submission_uid","uuid","expires_at"}

def grant():
    g=json.loads(central.private_text("sandbox-poll-grant.json"),object_pairs_hook=_unique_object)
    require(isinstance(g,dict) and set(g)==FIELDS,"Exact receipt grant required")
    require(all(isinstance(v,str) for v in g.values()),"Invalid receipt grant")
    require(str(UUID(g["tenant_id"]))==g["tenant_id"],"Invalid tenant")
    require(re.fullmatch(r"[A-Z]{1,3}[0-9]{1,13}",g["taxpayer"]),"Invalid taxpayer")
    require(re.fullmatch(r"[a-f0-9]{64}",g["document_hash"]),"Invalid hash")
    require(1<=len(g["code_number"])<=50,"Invalid code")
    require(all(re.fullmatch(r"[A-Za-z0-9]{26}",g[k]) for k in ("submission_uid","uuid")),"Invalid receipt")
    require(g["expires_at"].endswith("Z"),"UTC expiry required")
    return g

def verify(g,key,tin,brn,x,now):
    require(timedelta(0)<parse_time(g["expires_at"])-now<=timedelta(minutes=15),"Grant expired or too broad")
    require(g["tenant_id"]==str(key[0]) and g["taxpayer"]==tin==x["tin"],"Tenant mismatch")
    require(central.approved_target(key[0],tin,brn,"sandbox")==tin,"Approved Sandbox taxpayer required")
    require(x["state"]=="accepted","Only pending accepted receipts can be polled")
    require(g["document_hash"]==x["hash"]==sha256(bytes(x["bytes"])).hexdigest(),"Document mismatch")
    require(g["code_number"]==x["code"] and g["submission_uid"]==x["submission"] and g["uuid"]==x["uuid"],"Receipt mismatch")

def owner_active(c,key,x):
    found=c.execute("""SELECT 1 FROM myr_native.companies co
        JOIN myr_native.company_members m ON m.company_id=co.id
        JOIN myr_native.users u ON u.email=m.email
        WHERE co.id=%s AND co.version=%s AND co.status='active'
        AND u.id=%s AND u.disabled=false AND u.email_verified_at IS NOT NULL
        AND NOT u.is_platform_admin AND m.role='Owner' AND m.status='active'
        FOR SHARE OF co,m,u""",(key[0],x["version"],x["created_by"])).fetchone()
    require(found is not None,"Owner authorization or company revision changed")

def reserve_poll(c,key,x,now,claim):
    poll_plan(x,now)
    result=c.execute(f"""UPDATE {TABLE} SET poll_claim=%s,poll_not_before=%s
        WHERE company_id=%s AND invoice_id=%s AND environment=%s AND state='accepted'
        AND NOT poll_blocked AND (poll_not_before IS NULL OR poll_not_before<=%s)
        RETURNING poll_claim""",(claim,now+timedelta(seconds=90),*key,now)).fetchone()
    require(result is not None,"Poll already reserved, blocked or backing off")
    # Commit in caller before any network call. Ninety seconds outlasts the bounded bridge.

def verify_claim(c,key,claim):
    found=c.execute(f"""SELECT poll_claim FROM {TABLE} WHERE company_id=%s AND invoice_id=%s
        AND environment=%s AND state='accepted' AND NOT poll_blocked FOR UPDATE""",key).fetchone()
    require(found is not None and found[0]==claim,"Poll reservation changed")

def finish(c,key,claim,now,delay,blocked=False):
    result=c.execute(f"""UPDATE {TABLE} SET poll_claim=NULL,poll_not_before=%s,poll_blocked=%s
        WHERE company_id=%s AND invoice_id=%s AND environment=%s AND poll_claim=%s
        RETURNING 1""",(now+timedelta(seconds=delay),blocked,*key,claim)).fetchone()
    require(result is not None,"Poll reservation changed")

def backoff(result):
    seconds=result.get("retry_after",60) if isinstance(result,dict) else 60
    if type(seconds) is not int or seconds<0:return 60,False
    # An excessive provider backoff must not be silently truncated into an early retry.
    if seconds>604800:return 604800,True
    return max(60,seconds),False

def post_poll(g):
    key=central.private_text("sandbox-poll-secret").strip()
    require(re.fullmatch(r"[a-f0-9]{64}",key),"Invalid poll secret")
    data=json.dumps({"environment":"sandbox","tenant_id":g["tenant_id"],"submission_uid":g["submission_uid"],"uuid":g["uuid"]},separators=(",",":")).encode()
    req=Request(URL,data=data,method="POST",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"})
    opener=build_opener(ProxyHandler({}),central.NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    from urllib.error import HTTPError
    try:
        with opener.open(req,timeout=55) as response:
            raw=response.read(65537);status=response.status
    except HTTPError as exc:
        with exc:raw=exc.read(65537);status=exc.code
    require(len(raw)<=65536,"Oversized response")
    result=json.loads(raw,object_pairs_hook=_unique_object)
    require(isinstance(result,dict),"Invalid response")
    if status==200 and result.get("state")=="polled" and result.get("http_status")==200:
        require(isinstance(result.get("response"),dict),"Missing status")
        return result
    return {"state":"poll_unavailable","retry_after":result.get("retry_after",60)}

def run_poll_once(connect,company_id,invoice_id,send=post_poll,clock=lambda:datetime.now(timezone.utc)):
    """Operator harness only. No scheduler, no production records, no API writes."""
    key=scoped(company_id,invoice_id,"sandbox")
    g=grant();claim=uuid4()
    with connect() as c:
        check_database(c)
        tin,brn,x=bind(c,key)
        now=clock()
        verify(g,key,tin,brn,x,now);owner_active(c,key,x)
        reserve_poll(c,key,x,now,claim)
        c.commit()
    # Recheck current owner, receipt and grant immediately before network read.
    with connect() as c:
        check_database(c)
        tin,brn,x=bind(c,key)
        require(grant()==g,"Poll grant changed")
        verify(g,key,tin,brn,x,clock());owner_active(c,key,x);verify_claim(c,key,claim)
    try:result=send(g)
    except Exception:result={"state":"poll_unavailable","retry_after":60}
    with connect() as c:
        check_database(c)
        tin,brn,x=bind(c,key)
        now=clock()
        require(grant()==g,"Poll grant changed")
        verify(g,key,tin,brn,x,now);owner_active(c,key,x);verify_claim(c,key,claim)
        if isinstance(result,dict) and result.get("state")=="polled" and result.get("http_status")==200:
            try:change=sync(c,*key,result["response"],now)
            except (ValueError,KeyError,TypeError):
                finish(c,key,claim,now,60,True);c.commit()
                return {"state":"review_required","environment":"sandbox"}
            finish(c,key,claim,now,5);c.commit()
            return {"state":change["state"],"environment":"sandbox","verification_url":change["verification_url"]}
        delay,blocked=backoff(result)
        finish(c,key,claim,now,delay,blocked);c.commit()
        return {"state":"review_required" if blocked else "poll_unavailable","environment":"sandbox","retry_after":delay}

class PollTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,28,7,tzinfo=timezone.utc)
        self.company=UUID(int=1);self.key=(self.company,"INV1","sandbox")
        self.tin="C1234567890";self.brn="202001234567"
        self.raw=b"synthetic";self.x={"state":"accepted","tin":self.tin,"hash":sha256(self.raw).hexdigest(),"bytes":self.raw,"code":"PILOT1","submission":"S"*26,"uuid":"D"*26,"updated_at":self.now-timedelta(seconds=10),"version":1,"created_by":UUID(int=2)}
        self.g={"tenant_id":str(self.company),"taxpayer":self.tin,"code_number":self.x["code"],"document_hash":self.x["hash"],"submission_uid":self.x["submission"],"uuid":self.x["uuid"],"expires_at":(self.now+timedelta(minutes=10)).isoformat().replace("+00:00","Z")}
    def test_grant_binding(self):
        with patch.object(central,"approved_target",return_value=self.tin):
            verify(self.g,self.key,self.tin,self.brn,self.x,self.now)
            for change in ({"uuid":"X"*26},{"tenant_id":str(UUID(int=3))},{"document_hash":"f"*64},{"expires_at":"2020-01-01T00:00:00Z"}):
                with self.assertRaises(ValueError):verify(self.g|change,self.key,self.tin,self.brn,self.x,self.now)
            with self.assertRaises(ValueError):verify(self.g,self.key,self.tin,self.brn,self.x|{"state":"outcome_unknown"},self.now)
        with patch.object(central,"approved_target",return_value=None):
            with self.assertRaises(ValueError):verify(self.g,self.key,self.tin,self.brn,self.x,self.now)
    def test_reserve_and_backoff(self):
        c=Mock();c.execute.return_value.fetchone.return_value=(UUID(int=3),)
        reserve_poll(c,self.key,self.x,self.now,UUID(int=3))
        args=c.execute.call_args.args
        self.assertIn("NOT poll_blocked",args[0]);self.assertIn(self.now+timedelta(seconds=90),args[1])
        c.execute.return_value.fetchone.return_value=None
        with self.assertRaises(ValueError):reserve_poll(c,self.key,self.x,self.now,UUID(int=4))
        self.assertEqual(backoff({"retry_after":7200}),(7200,False))
        self.assertEqual(backoff({"retry_after":999999999}),(604800,True))
        self.assertEqual(backoff({"retry_after":True}),(60,False))
    def test_committed_reservation_and_verified_sync(self):
        c=Mock();ctx=Mock();ctx.__enter__=Mock(return_value=c);ctx.__exit__=Mock(return_value=False)
        connect=Mock(return_value=ctx)
        result={"state":"polled","http_status":200,"response":{"synthetic":True}}
        with patch(__name__+".check_database"),patch(__name__+".grant",return_value=self.g),patch(__name__+".bind",return_value=(self.tin,self.brn,self.x)),patch(__name__+".verify"),patch(__name__+".owner_active"),patch(__name__+".reserve_poll"),patch(__name__+".verify_claim"),patch(__name__+".finish") as fin,patch(__name__+".sync",return_value={"state":"valid","verification_url":"https://preprod.myinvois.hasil.gov.my/example"}) as synced:
            def send(g):
                self.assertGreaterEqual(c.commit.call_count,1)
                self.assertEqual(g,self.g)
                return result
            out=run_poll_once(connect,self.company,"INV1",send,lambda:self.now)
            self.assertEqual(out["state"],"valid");synced.assert_called_once();fin.assert_called_once()
            self.assertEqual(c.commit.call_count,2)
    def test_failed_reservation_prevents_network(self):
        c=Mock();ctx=Mock();ctx.__enter__=Mock(return_value=c);ctx.__exit__=Mock(return_value=False)
        send=Mock()
        with patch(__name__+".check_database"),patch(__name__+".grant",return_value=self.g),patch(__name__+".bind",return_value=(self.tin,self.brn,self.x)),patch(__name__+".verify"),patch(__name__+".owner_active"),patch(__name__+".reserve_poll",side_effect=ValueError("busy")):
            with self.assertRaises(ValueError):run_poll_once(Mock(return_value=ctx),self.company,"INV1",send,lambda:self.now)
        send.assert_not_called()
    def test_unavailable_does_not_sync(self):
        c=Mock();ctx=Mock();ctx.__enter__=Mock(return_value=c);ctx.__exit__=Mock(return_value=False)
        with patch(__name__+".check_database"),patch(__name__+".grant",return_value=self.g),patch(__name__+".bind",return_value=(self.tin,self.brn,self.x)),patch(__name__+".verify"),patch(__name__+".owner_active"),patch(__name__+".reserve_poll"),patch(__name__+".verify_claim"),patch(__name__+".finish") as fin,patch(__name__+".sync") as synced:
            out=run_poll_once(Mock(return_value=ctx),self.company,"INV1",Mock(side_effect=TimeoutError),lambda:self.now)
            self.assertEqual(out["state"],"poll_unavailable");synced.assert_not_called();self.assertEqual(fin.call_args.args[-2:],(60,False))
if __name__=="__main__":unittest.main()
