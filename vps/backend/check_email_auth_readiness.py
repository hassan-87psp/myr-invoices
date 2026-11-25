"""Run all native auth and email readiness checks; never change public release."""
import subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
env={k:v for k,v in os.environ.items() if k!="MYR_PRODUCTION_RELEASE"}
for script in ("check_business_asgi.py","check_native_business_asgi.py","check_account_mail_asgi.py","build_native_auth_candidate.py"):
    subprocess.run([sys.executable,"-B",str(ROOT/script)],check=True,env=env)
print("MYR_NATIVE_AUTH_CODE_CHECKS_PASSED")
result=subprocess.run([sys.executable,"-B",str(ROOT/"check_email_logo.py")],env=env)
if result.returncode:
    print("MYR_MAIL_RELEASE_BLOCKED: exact approved logo is not available")
    raise SystemExit(1)
print("MYR_MAIL_AND_AUTH_REHEARSAL_READY; public release and delivery acceptance still required")
