"""Operator-only connection setup; does not activate native auth or send account links."""
import getpass,json,os,re,secrets,tempfile
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

def main():
    os.umask(0o077)
    folder=Path.home()/".config/myrinvoice"
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=folder/"supabase-mail-api-secret"
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise SystemExit("Unsafe secret file")
        key=path.read_text().strip()
    else:
        key=secrets.token_hex(32)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as f: f.write(key+"\n")
    if not re.fullmatch(r"[a-f0-9]{64}",key):
        raise SystemExit("Existing secret is not a valid 64-character hex value")
    print("Copy this private value ONLY into Supabase Edge Function Secrets as MYR_MAIL_SHARED_SECRET.")
    print("Do not send it in chat, screenshots or GitHub.")
    print(key)
    input("After saving the shared secret AND MYR_RESEND_API_KEY in Supabase, press Enter to send a test email: ")
    req=Request("https://nynghaleoaqilewmhbdi.supabase.co/functions/v1/myr-transactional-mail",
      data=b'{"event":"test"}',headers={"Content-Type":"application/json","X-MYR-Mail-Secret":key},method="POST")
    try:
        with urlopen(req,timeout=20) as res:
            if res.status!=200 or json.loads(res.read(2048)).get("accepted") is not True: raise ValueError()
    except HTTPError as e:
        try:
            data=json.loads(e.read(2048))
            code=data.get("code","AUTH_OR_CONFIGURATION")
            if code not in ("MAIL_PROVIDER_NOT_CONFIGURED","PROVIDER_REJECTED","INVALID_PROVIDER_RESPONSE","PROVIDER_UNAVAILABLE"): code="AUTH_OR_CONFIGURATION"
            print("MYR_MAIL_TEST_FAILED",e.code,code)
            if code=="PROVIDER_REJECTED": print("PROVIDER_HTTP",data.get("provider_status"))
        except Exception: print("MYR_MAIL_TEST_FAILED",e.code)
        raise SystemExit(1) from None
    except (OSError,ValueError,URLError):
        raise SystemExit("MYR_MAIL_TEST_CONNECTION_FAILED") from None
    print("MYR_MAIL_PROVIDER_ACCEPTED_TEST")
    print("Check inbox/spam at invoicesmyr@gmail.com. Native account emails remain disabled.")

if __name__=="__main__": main()
