"""Send the original connection test only, with the existing private SMTP gateway.
Never print credentials, create an account, or change the live website.
"""
import json,os,re,sys
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
path=Path.home()/".config/myrinvoice/supabase-mail-api-secret"
if path.is_symlink() or not path.is_file() or path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o077:
    raise SystemExit("Missing or unsafe mail secret")
key=path.read_text().strip()
if not re.fullmatch(r"[a-f0-9]{64}",key): raise SystemExit("Invalid mail secret")
events={"connection":"test","verify":"test_verify","reset":"test_reset","welcome":"test_welcome"}
args=sys.argv[1:] or ["connection"]
if len(args)!=1 or args[0] not in events: raise SystemExit("Choose connection, verify, reset or welcome")
req=Request("https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-transactional-mail",
    data=json.dumps({"event":events[args[0]]}).encode(),headers={"Content-Type":"application/json","X-MYR-Mail-Secret":key},method="POST")
try:
    with build_opener(NoRedirect()).open(req,timeout=45) as res:
        result=json.loads(res.read(2048))
        if res.status!=200 or result.get("accepted") is not True: raise ValueError()
        print("ORIGINAL_EMAIL_SMTP_ACCEPTED",args[0],"queue_id:",result.get("queue_id","not supplied"))
except HTTPError as e:
    raise SystemExit("ORIGINAL_EMAIL_FAILED HTTP "+str(e.code)) from None
except (OSError,ValueError):
    raise SystemExit("ORIGINAL_EMAIL_CONNECTION_FAILED") from None
print("Check invoicesmyr@gmail.com inbox and spam. SMTP acceptance is not mailbox delivery.")
