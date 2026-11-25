"""Connection-only taxpayer credential check. No database writes or invoice submission.
Credentials and access token stay in process memory; no output of provider response bodies.
"""
import getpass
import json
import sys
import ssl
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError, URLError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def main():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit("Run interactively in your private VPS terminal.")
    if sys.argv[1:] not in (["production"], ["sandbox"]):
        raise SystemExit("Choose production or sandbox explicitly.")
    env=sys.argv[1]
    base={"production":"https://api.myinvois.hasil.gov.my","sandbox":"https://preprod-api.myinvois.hasil.gov.my"}[env]
    print("LHDN",env,"connection test only. No invoice will be submitted.",flush=True)
    client_id=getpass.getpass("Client ID (hidden): ").strip()
    secret=getpass.getpass("Client Secret 1 (hidden): ").strip()
    if not client_id or not secret or len(client_id)>512 or len(secret)>2048:
        raise SystemExit("Missing or invalid credentials.")
    req=Request(base+"/connect/token",data=urlencode({"client_id":client_id,"client_secret":secret,"grant_type":"client_credentials","scope":"InvoicingAPI"}).encode("ascii"),headers={"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json"},method="POST")
    opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(req,timeout=25) as res:
            data=json.loads(res.read(65536))
            if res.status!=200 or not isinstance(data,dict) or not isinstance(data.get("access_token"),str) or not data["access_token"] or str(data.get("token_type","")).lower()!="bearer":
                raise ValueError("Invalid token response")
            ttl=data.get("expires_in")
            if not isinstance(ttl,int) or isinstance(ttl,bool) or ttl<=0:
                raise ValueError("Invalid expiration")
            print("MYR_LHDN_TAXPAYER_LOGIN_OK",env,"HTTP",res.status,"expires_in",ttl,flush=True)
    except HTTPError as exc:
        code="unknown"
        try:
            candidate=json.loads(exc.read(16384)).get("error")
            if candidate in ("invalid_request","invalid_client","invalid_grant","unauthorised_client","unauthorized_client","unsupported_grant_type","invalid_scope"):
                code=candidate
        except (ValueError,AttributeError,TypeError):
            pass
        print("MYR_LHDN_LOGIN_FAILED",env,"HTTP",exc.code,"error",code,flush=True)
        raise SystemExit(1) from None
    except (OSError,URLError,ValueError):
        raise SystemExit("MYR_LHDN_CONNECTION_OR_RESPONSE_FAILED") from None
    print("Authentication only verified. Credentials were not saved; no invoices or taxpayer records modified.")

if __name__=="__main__":
    main()
