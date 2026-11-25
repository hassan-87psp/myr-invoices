"""Local operator SMTP diagnostics; never print passwords or raw server replies."""
import getpass
import socket
import ssl
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from admin_email import load, save, render, SENDER, ADMIN, SMTPSettings
import re

def main():
    c=load()
    print("Saved host:",c.get("host") or "NOT SAVED")
    print("Saved port:",c.get("port") or "NOT SAVED")
    print("Saved username:",c.get("username") or "NOT SAVED")
    print("Password saved:",bool(c.get("password")))
    print("Last test status:",(c.get("last_test") or {}).get("status","not sent"))
    if c.get("password") and input("Use saved SMTP settings? [Y/n]: ").strip().lower() in ("","y","yes"):
        host,port,user,password=(c.get(k) for k in ("host","port","username","password"))
    else:
        host=input("Confirmed SMTP hostname from email provider: ").strip()
        try:
            port=int(input("SMTP port [465]: ").strip() or "465")
        except ValueError:
            raise SystemExit("Invalid port")
        user=input("SMTP username ["+SENDER+"]: ").strip() or SENDER
        password=getpass.getpass("Email mailbox SMTP password: ")
    try:
        SMTPSettings(host=host,port=port,username=user,password=password)
    except Exception:
        raise SystemExit("Invalid SMTP settings")
    if port not in (465,587) or not re.fullmatch(r"[A-Za-z0-9.-]+",host) or "." not in host or not password:
        raise SystemExit("Invalid host, port or empty password")
    print("Testing:",host,port,user,flush=True)
    stage="DNS"
    smtp=None
    accepted=False
    try:
        socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
        print("SMTP_DNS_OK",flush=True)
        stage="TCP_TLS"
        ctx=ssl.create_default_context()
        if port==465:
            smtp=smtplib.SMTP_SSL(host,port,timeout=15,context=ctx)
        else:
            smtp=smtplib.SMTP(host,port,timeout=15)
            smtp.ehlo()
            smtp.starttls(context=ctx)
        smtp.ehlo()
        print("SMTP_TLS_OK",flush=True)
        stage="AUTH"
        smtp.login(user,password)
        print("SMTP_AUTH_OK",flush=True)
        stage="SEND"
        msg=EmailMessage()
        msg["From"]=formataddr(("MYR Invoice",SENDER))
        msg["To"]=ADMIN
        msg["Subject"]="MYR Invoice - SMTP test"
        msg.set_content("Your private VPS SMTP delivery test. No action required.")
        msg.add_alternative(render("SMTP connection test","Your private VPS SMTP delivery test. No action required."),subtype="html")
        if smtp.send_message(msg):
            raise RuntimeError("Recipient refused")
        accepted=True
        print("SMTP_ACCEPTED_BY_SERVER",ADMIN,flush=True)
    except Exception as exc:
        print("SMTP_FAILED_STAGE:",stage)
        print("ERROR_TYPE:",type(exc).__name__)
        if isinstance(exc,smtplib.SMTPResponseException):
            print("SMTP_STATUS_CODE:",exc.smtp_code)
        raise SystemExit(1) from None
    finally:
        if smtp is not None:
            try: smtp.close()
            except OSError: pass
    if accepted:
        c.update(host=host,port=port,username=user,password=password,
                 last_test={"status":"accepted_by_smtp","time":datetime.now(timezone.utc).isoformat()})
        save(c)
        print("SMTP_SETTINGS_SAVED_ON_VPS")
        print("Check Gmail inbox and spam; SMTP acceptance does not prove inbox delivery.")

if __name__=="__main__":
    main()
