"""Private staging email configuration and template editor; no automatic mail yet."""
import json, os, re, ssl, smtplib, tempfile
from pathlib import Path
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from datetime import datetime, timezone
from threading import Lock
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from staging_api import api, db, identity

ROOT=Path.home()/".config"/"myrinvoice"
FILE=ROOT/"mail-staging.json"
SENDER="no-reply@myrinvoice.com"
ADMIN="invoicesmyr@gmail.com"
LOCK=Lock()
DEFAULTS={
"verify_email":["Verify your email","Verify your email","Confirm your MYR Invoice account using the secure verification link."],
"welcome":["Welcome to MYR Invoice","Welcome aboard","Your account is ready. Create and manage your business invoices."],
"reset_password":["Reset your password","Password reset","Use the secure password reset link to choose a new password."],
"invoice":["Your invoice","Invoice ready","Your invoice is ready for review."],
"quotation":["Your quotation","Quotation ready","Your quotation is ready for review."],
"payment_confirmation":["Payment received","Thank you for your payment","Your payment has been recorded."],
"payment_reminder":["Payment reminder","Upcoming payment","Please review your outstanding invoice."],
"overdue":["Overdue invoice","Payment overdue","Please arrange payment for the outstanding invoice."],
"team_invitation":["Team invitation","Join your team","You have been invited to join a business on MYR Invoice."],
"subscription_expiry":["Subscription reminder","Subscription renewal","Review your subscription before it expires."],
"lhdn_status":["MyInvois status update","Document status","The status of your e-Invoice has changed."]
}
def require_admin(request,conn):
    uid,email,_,admin=identity(conn,request)
    if not admin or email!=ADMIN:
        raise HTTPException(403,"Designated platform administrator required")
    return uid
def load():
    if not FILE.exists(): return {}
    return json.loads(FILE.read_text())
def save(data):
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=ROOT,prefix=".mail-")
    try:
        with os.fdopen(fd,"w") as f:
            json.dump(data,f);f.flush();os.fsync(f.fileno())
        os.replace(name,FILE)
    finally:
        if os.path.exists(name): os.unlink(name)
def render(title,body):
    return ('<!doctype html><html><body style="margin:0;background:#eef2fa;font-family:Arial,sans-serif;color:#17254a">'
      '<div style="max-width:560px;margin:24px auto;background:white;border-radius:12px;padding:28px">'
      '<div style="font-weight:bold;color:#3446df;font-size:20px">MYR Invoice</div><hr style="border:0;border-top:1px solid #e4e9f5">'
      '<h1 style="font-size:24px">'+escape(title)+'</h1><p style="line-height:1.6">'+escape(body).replace("\n","<br>")+
      '</p><hr style="border:0;border-top:1px solid #e4e9f5"><p style="font-size:12px;color:#67738b">MYR Invoice · Automated notification</p></div></body></html>')
class SMTPSettings(BaseModel):
    host:str=Field(min_length=3,max_length=253)
    port:int
    username:str=Field(min_length=1,max_length=254)
    password:str=Field(default="",max_length=1024)
class Template(BaseModel):
    subject:str=Field(min_length=1,max_length=150)
    title:str=Field(min_length=1,max_length=150)
    body:str=Field(min_length=1,max_length=5000)
@api.get("/admin/email")
def settings(request:Request,conn=Depends(db)):
    require_admin(request,conn)
    with LOCK: c=load()
    return {"sender":SENDER,"host":c.get("host",""),"port":c.get("port",587),"username":c.get("username",""),
        "password_configured":bool(c.get("password")),"templates":{**DEFAULTS,**c.get("templates",{})},"last_test":c.get("last_test")}
@api.post("/admin/email/settings")
def settings_save(body:SMTPSettings,request:Request,conn=Depends(db)):
    require_admin(request,conn)
    if body.port not in (465,587) or not re.fullmatch(r"[a-zA-Z0-9.-]+",body.host) or "." not in body.host:
        raise HTTPException(422,"Use SMTP provider hostname and TLS port 465 or 587")
    with LOCK:
        c=load()
        password=body.password or (c.get("password") if c.get("host")==body.host and c.get("username")==body.username and c.get("port")==body.port else "")
        if not password: raise HTTPException(422,"SMTP password required")
        c.update(host=body.host,port=body.port,username=body.username,password=password,last_test=None)
        save(c)
    return {"saved":True}
@api.post("/admin/email/templates/{key}")
def template_save(key:str,body:Template,request:Request,conn=Depends(db)):
    require_admin(request,conn)
    if key not in DEFAULTS or "\r" in body.subject or "\n" in body.subject:
        raise HTTPException(422,"Invalid template")
    with LOCK:
        c=load();c.setdefault("templates",{})[key]=[body.subject,body.title,body.body];save(c)
    return {"saved":True}
@api.post("/admin/email/test")
def test_mail(request:Request,conn=Depends(db)):
    require_admin(request,conn)
    with LOCK:
        c=load()
        if not c.get("password"): raise HTTPException(409,"Configure SMTP first")
        msg=EmailMessage()
        msg["From"]=formataddr(("MYR Invoice",SENDER))
        msg["To"]=ADMIN
        msg["Subject"]="MYR Invoice — SMTP test"
        msg.set_content("This is a private staging SMTP test. No account or invoice action is requested.")
        msg.add_alternative(render("Email connection test","Your MYR Invoice SMTP connection is being tested. No account action is required."),subtype="html")
        try:
            ctx=ssl.create_default_context()
            if c["port"]==465:
                with smtplib.SMTP_SSL(c["host"],465,timeout=15,context=ctx) as smtp:
                    smtp.login(c["username"],c["password"]);smtp.send_message(msg)
            else:
                with smtplib.SMTP(c["host"],587,timeout=15) as smtp:
                    smtp.ehlo();smtp.starttls(context=ctx);smtp.ehlo();smtp.login(c["username"],c["password"]);smtp.send_message(msg)
        except (OSError,smtplib.SMTPException):
            c["last_test"]={"status":"failed","time":datetime.now(timezone.utc).isoformat()};save(c)
            raise HTTPException(502,"SMTP failed. Check provider settings, sender authorization and VPS connectivity.")
        c["last_test"]={"status":"accepted_by_smtp","time":datetime.now(timezone.utc).isoformat()};save(c)
    return {"status":"accepted_by_smtp","recipient":ADMIN}
