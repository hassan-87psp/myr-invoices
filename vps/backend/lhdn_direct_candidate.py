"""Direct taxpayer ERP connector, offline release candidate.
Never called from a customer route. Sandbox only; no submission, credential
persistence, or claim of taxpayer ownership from a successful TIN lookup.
"""
from dataclasses import dataclass,field
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode,quote
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler
from urllib.error import HTTPError
import json,re,ssl,time,unittest
from unittest.mock import Mock
from business_lhdn import NoRedirect
from lhdn_protocol_candidate import require,_unique_object

BASE="https://preprod-api.myinvois.hasil.gov.my"
def credentials(client_id,client_secret):
    require(isinstance(client_id,str) and 1<=len(client_id)<=512 and client_id.isascii() and all(33<=ord(x)<=126 for x in client_id),"Invalid ERP credentials")
    require(isinstance(client_secret,str) and 1<=len(client_secret)<=1024 and client_secret.isascii() and all(33<=ord(x)<=126 for x in client_secret),"Invalid ERP credentials")
    return client_id,client_secret

def transport(method,path,headers,body=None):
    # Fixed provider, HTTPS, no proxy, no redirects; never log request/response.
    require(path=="/connect/token" or re.fullmatch(r"/api/v1\.0/taxpayer/validate/[A-Z]{1,3}[0-9]{1,20}\?idType=BRN&idValue=[A-Z0-9-]{1,40}",path),"Unexpected provider path")
    req=Request(BASE+path,data=body,headers=headers,method=method)
    opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(req,timeout=20) as res:
            return res.status,res.headers.get("Retry-After"),res.read(65537)
    except HTTPError as exc:
        with exc:return exc.code,exc.headers.get("Retry-After"),b""

def retry_at(header,now):
    if isinstance(header,str) and header.isascii():
        if re.fullmatch(r"[0-9]{1,12}",header):return now+max(60,int(header))
        if re.fullmatch(r"[0-9]+",header):return float("inf")
        try:
            t=parsedate_to_datetime(header)
            if t.tzinfo is not None:return max(now+60,t.timestamp())
        except (TypeError,ValueError,OverflowError):pass
    return now+60

@dataclass(repr=False)
class Token:
    value:str=field(repr=False)
    expires_at:float

class DirectSession:
    """Short-lived, per-tenant/per-credential in-memory client. No shared token.
    Callers must enforce distributed throttling and verify actual issuer identity
    before persistence or document operations. No automatic retry on errors.
    """
    def __init__(self,tenant_id,client_id,client_secret,environment="sandbox",send=transport,clock=time.time):
        from uuid import UUID
        require(environment=="sandbox","Only Sandbox is supported")
        require(str(UUID(str(tenant_id)))==str(tenant_id),"Invalid tenant")
        self.tenant_id=str(tenant_id)
        self._id,self._secret=credentials(client_id,client_secret)
        self._send=send;self._clock=clock;self._token=None;self._blocked_until=0
    def _call(self,method,path,headers,body=None):
        if self._clock()<self._blocked_until:return 429,b""
        try:status,wait,raw=self._send(method,path,headers,body)
        except Exception:
            self._blocked_until=max(self._blocked_until,self._clock()+60)
            return 503,b""
        if status==429:self._blocked_until=max(self._blocked_until,retry_at(wait,self._clock()))
        elif status>=500:self._blocked_until=max(self._blocked_until,self._clock()+60)
        elif status in (400,401,403):self._blocked_until=max(self._blocked_until,self._clock()+60)
        if type(raw) is not bytes or len(raw)>65536:return 502,b""
        return status,raw
    def login(self):
        now=self._clock()
        if now<self._blocked_until:return "rate_limited"
        if self._token and self._token.expires_at>now+60:return "cached_login"
        self._token=None
        body=urlencode({"client_id":self._id,"client_secret":self._secret,"grant_type":"client_credentials","scope":"InvoicingAPI"}).encode()
        status,raw=self._call("POST","/connect/token",{"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json"},body)
        if status!=200:
            return "rate_limited" if status==429 else "credentials_rejected" if status in (400,401,403) else "provider_unavailable"
        try:
            d=json.loads(raw,object_pairs_hook=_unique_object)
            token=d["access_token"];ttl=d["expires_in"]
            require(isinstance(token,str) and 1<=len(token)<=32768 and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",token),"Invalid token format")
            require(isinstance(d.get("token_type"),str) and d["token_type"].lower()=="bearer","Invalid token type")
            require(type(ttl) is int and 60<ttl<=3600,"Invalid token lifetime")
            require(d.get("scope","InvoicingAPI")=="InvoicingAPI","Unexpected scope")
        except (KeyError,ValueError,TypeError,AttributeError):return "invalid_provider_response"
        self._token=Token(token,now+ttl)
        return "login_verified"
    def probe(self,tin,brn):
        require(isinstance(tin,str) and re.fullmatch(r"[A-Z]{1,3}[0-9]{1,20}",tin),"Invalid TIN")
        require(isinstance(brn,str) and re.fullmatch(r"[A-Z0-9-]{1,40}",brn),"Invalid BRN")
        login=self.login()
        out={"environment":"sandbox","mode":"direct_erp","login_status":login,"tin_brn_lookup_verified":False,"issuer_binding_verified":False,"submission_enabled":False}
        if login not in ("login_verified","cached_login"):return out
        status,_=self._call("GET","/api/v1.0/taxpayer/validate/"+quote(tin,safe="")+"?"+urlencode({"idType":"BRN","idValue":brn}),{"Authorization":"Bearer "+self._token.value,"Accept":"application/json"})
        if status in (401,403):self._token=None
        out["tin_brn_lookup_verified"]=status==200
        out["lookup_status"]="matched" if status==200 else "rate_limited" if status==429 else "not_matched" if status==404 else "unavailable"
        # Validate Taxpayer TIN is a lookup of any taxpayer; it does not prove
        # that the OAuth credential belongs to that TIN. Never infer ownership.
        return out

class DirectTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000
        self.token=b'{"access_token":"a.b.c","token_type":"Bearer","expires_in":3600}'
        self.send=Mock(side_effect=[(200,None,self.token),(200,None,b"")])
        self.c=DirectSession("00000000-0000-4000-8000-000000000001","synthetic-id","synthetic-secret",send=self.send,clock=lambda:self.now)
    def test_login_and_lookup_distinct_from_ownership(self):
        x=self.c.probe("C1234567890","202001234567")
        self.assertTrue(x["tin_brn_lookup_verified"]);self.assertFalse(x["issuer_binding_verified"]);self.assertFalse(x["submission_enabled"])
        method,path,headers,body=self.send.call_args_list[0].args
        self.assertEqual((method,path),("POST","/connect/token"))
        self.assertNotIn("onbehalfof",str(headers).lower())
        self.assertIn(b"client_secret=synthetic-secret",body)
        self.assertNotIn("synthetic-secret",str(x));self.assertNotIn("a.b.c",str(x))
    def test_cached_renewal(self):
        self.send.side_effect=[(200,None,self.token),(200,None,self.token)]
        self.assertEqual(self.c.login(),"login_verified")
        self.assertEqual(self.c.login(),"cached_login")
        self.now+=3541
        self.assertEqual(self.c.login(),"login_verified")
        self.assertEqual(self.send.call_count,2)
    def test_rejected_credentials(self):
        self.send.side_effect=[(401,None,b"")]
        self.assertEqual(self.c.probe("C1234567890","202001234567")["login_status"],"credentials_rejected")
        self.assertEqual(self.c.login(),"rate_limited");self.assertEqual(self.send.call_count,1)
    def test_backoff(self):
        self.send.side_effect=[(429,"7200",b""),(200,None,self.token)]
        self.assertEqual(self.c.login(),"rate_limited")
        self.now+=7199;self.assertEqual(self.c.login(),"rate_limited")
        self.now+=1;self.assertEqual(self.c.login(),"login_verified")
    def test_validation_and_environment(self):
        with self.assertRaises(ValueError):DirectSession(self.c.tenant_id,"id","secret","production",self.send)
        with self.assertRaises(ValueError):self.c.probe("C1234567890","bad & path")
        self.send.assert_not_called()
    def test_wrong_token(self):
        self.send.side_effect=[(200,None,b'{"access_token":"a.b.c","token_type":"Bearer","expires_in":3600,"scope":"wrong"}')]
        self.assertEqual(self.c.login(),"invalid_provider_response")
    def test_revoked_token(self):
        self.send.side_effect=[(200,None,self.token),(403,None,b"")]
        x=self.c.probe("C1234567890","202001234567")
        self.assertFalse(x["tin_brn_lookup_verified"]);self.assertIsNone(self.c._token)
if __name__=="__main__":unittest.main()
