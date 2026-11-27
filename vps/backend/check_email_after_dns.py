"""Post-DNS email delivery diagnostic. Sends one test to the configured support inbox only.
No credentials, raw SMTP replies, recipients, or verification tokens printed.
"""
import json,re,ssl,subprocess
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
from business_lhdn import private_text,NoRedirect

def dns(name):
    try:
        p=subprocess.run(["dig","+time=3","+tries=1","+short","TXT",name],capture_output=True,text=True,timeout=6,check=True)
        return ["".join(re.findall(r'"([^"]*)"',line)) for line in p.stdout.splitlines()]
    except (OSError,subprocess.SubprocessError):
        return None

def main():
    spf=dns("myrinvoice.com");dkim=dns("default._domainkey.myrinvoice.com");dmarc=dns("_dmarc.myrinvoice.com")
    records=[s for s in (spf or []) if s.lower().startswith("v=spf1")]
    print(json.dumps({"dns_lookup_available":spf is not None,
      "single_spf":len(records)==1,"namecheap_hosting_spf":len(records)==1 and "include:spf.web-hosting.com" in records[0],
      "forwarding_spf":len(records)==1 and "include:spf.efwd.registrar-servers.com" in records[0],
      "default_dkim_present":None if dkim is None else any("p=" in s for s in dkim),
      "dmarc_present":None if dmarc is None else any(s.lower().startswith("v=dmarc1") for s in dmarc)},indent=2))
    try:
        key=private_text("supabase-mail-api-secret").strip()
        if not re.fullmatch(r"[a-f0-9]{64}",key):raise ValueError("invalid key")
        req=Request("https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-transactional-mail",
          data=b'{"event":"test"}',headers={"X-MYR-Mail-Secret":key,"Content-Type":"application/json"},method="POST")
        opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(req,timeout=40) as res:status=res.status;body=json.loads(res.read(8192))
        except HTTPError as exc:status=exc.code;body=json.loads(exc.read(8192))
        print("MAIL_HTTP",status)
        if status!=200 or body.get("accepted") is not True:
            print("MYR_EMAIL_NOT_ACCEPTED");return 1
        trace=body.get("queue_id","")
        if isinstance(trace,str) and re.fullmatch(r"[A-Za-z0-9-]{1,80}",trace):print("MAIL_QUEUE_ID",trace)
        print("MYR_SMTP_ACCEPTED_INBOX_DELIVERY_UNVERIFIED")
        return 0
    except Exception:
        print("MYR_EMAIL_TEST_UNAVAILABLE");return 1
if __name__=="__main__":raise SystemExit(main())
