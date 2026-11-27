"""Operator-only CHIP test credential setup and read-only connectivity check.
No payment creation, database writes, or credential output.
"""
import os,stat,json,getpass
from pathlib import Path
from uuid import UUID
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def main():
    os.umask(0o077)
    folder=Path.home()/".config/myrinvoice"
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    st=folder.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise SystemExit("Unsafe configuration directory")
    p=folder/"chip-sandbox.json"
    if not p.exists() and not p.is_symlink():
        key=getpass.getpass("Paste CHIP TEST API key: ").strip()
        brand=str(UUID(getpass.getpass("Paste CHIP Brand ID: ").strip()))
        if not 1<=len(key)<=1024 or any(ord(x)<33 or ord(x)>126 for x in key):
            raise SystemExit("Invalid key format")
        with p.open("x") as f:
            json.dump({"api_key":key,"brand_id":brand,"mode":"test"},f)
    st=p.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise SystemExit("Unsafe credential file")
    cfg=json.loads(p.read_text())
    if cfg.get("mode")!="test":raise SystemExit("Test configuration required")
    brand=str(UUID(cfg["brand_id"]))
    key=cfg["api_key"]
    if not isinstance(key,str) or not 1<=len(key)<=1024 or any(ord(x)<33 or ord(x)>126 for x in key):
        raise SystemExit("Invalid key format")
    print("CHIP_SANDBOX_CONFIG_SAVED")
    url="https://gate.chip-in.asia/api/v1/payment_methods/?"+urlencode({"brand_id":brand,"currency":"MYR","amount":900})
    req=Request(url,headers={"Authorization":"Bearer "+key,"Accept":"application/json"})
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=20) as res:
            raw=res.read(65537)
            if len(raw)>65536:raise ValueError("response size")
            data=json.loads(raw)
            if not isinstance(data,(dict,list)):raise ValueError("response format")
            print("CHIP_API_HTTP",res.status)
            print("CHIP_READ_ONLY_CONNECTION_OK")
    except HTTPError as e:
        print("CHIP_API_HTTP",e.code)
        raise SystemExit("Connection not verified; credentials or brand may require review")
    except (URLError,ValueError,TimeoutError):
        raise SystemExit("Connection not verified; network or response error")
if __name__=="__main__":main()
