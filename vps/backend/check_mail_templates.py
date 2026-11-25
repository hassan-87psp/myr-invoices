"""Send three branded previews to the fixed operator inbox; never creates accounts."""
import json,sys
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

path=Path.home()/".config/myrinvoice/supabase-mail-api-secret"
if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
    raise SystemExit("Missing or unsafe mail secret")
key=path.read_text().strip()
keys=("verify_email","welcome","reset_password","activate_import","invoice","quotation","payment_confirmation","payment_reminder","overdue","team_invitation","subscription_expiry","lhdn_status")
selected=tuple(sys.argv[1:]) or ("verify_email","reset_password","welcome")
if selected==("--all",): selected=keys
if not all(k in keys for k in selected): raise SystemExit("Unknown template")
for event in selected:
    req=Request("https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-transactional-mail",
        data=json.dumps({"event":"test_template","template":event}).encode(),headers={"Content-Type":"application/json","X-MYR-Mail-Secret":key},method="POST")
    try:
        with build_opener(NoRedirect()).open(req,timeout=45) as res:
            result=json.loads(res.read(2048))
            if res.status!=200 or result.get("accepted") is not True: raise ValueError()
            trace=result.get("queue_id","not supplied")
            print(event,"SMTP_ACCEPTED","queue_id:",trace,flush=True)
    except HTTPError as e:
        print(event,"FAILED HTTP",e.code,flush=True)
        raise SystemExit(1) from None
    except (OSError,ValueError):
        raise SystemExit(event+" CONNECTION_FAILED") from None
print("MYR_TEMPLATE_PREVIEWS_ACCEPTED; check Gmail inbox/spam. No account activation performed.")
