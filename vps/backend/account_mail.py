"""Staging email composition. Real delivery deliberately disabled until
the native HTTPS activation pages and mail transport are ready."""
from email.message import EmailMessage
from urllib.parse import urlsplit, urlencode
from account_lifecycle import normalize_email

def compose_account_mail(recipient, token, purpose, origin, sender):
    recipient=normalize_email(recipient)
    sender=normalize_email(sender)
    url=urlsplit(origin)
    if url.scheme!="https" or not url.hostname or url.username or url.password or url.path not in ("","/") or url.query or url.fragment:
        raise ValueError("HTTPS application origin required")
    if purpose=="verify_email":
        subject="Verify your MYR Invoice email"
        action="verify-email"
        validity="60 minutes"
    elif purpose=="reset_password":
        subject="Reset your MYR Invoice password"
        action="reset-password"
        validity="20 minutes"
    else:
        raise ValueError("Invalid email purpose")
    link=origin.rstrip("/")+"/#/auth/"+action+"?"+urlencode({"token":token})
    message=EmailMessage()
    message["From"]=sender
    message["To"]=recipient
    message["Subject"]=subject
    message.set_content(f"{subject}\n\nOpen this link: {link}\n\nThis link expires in {validity}. If you did not request this, ignore this email.")
    return message

def staging_mailer():
    # No live messages or token disclosure before the native UI exists.
    from fastapi import HTTPException
    raise HTTPException(503,"Account email service is not configured")
