"""Private account lifecycle primitives. Tokens go only to a trusted mail sender.
Not yet exposed via HTTP; no real mail is sent by this module.
All operations use the caller's database transaction.
"""
import re
import secrets
from native_auth import digest, hash_password

def normalize_email(email):
    if not isinstance(email, str):
        raise ValueError("Invalid email")
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email):
        raise ValueError("Invalid email")
    return email

def new_token(conn, uid, purpose):
    if purpose not in ("verify_email", "reset_password"):
        raise ValueError("Invalid purpose")
    conn.execute("""UPDATE myr_native.auth_tokens SET used_at=now()
        WHERE user_id=%s AND purpose=%s AND used_at IS NULL""", (uid,purpose))
    token = secrets.token_urlsafe(32)
    ttl = 60 if purpose == "verify_email" else 20
    conn.execute("""INSERT INTO myr_native.auth_tokens
        (token_digest,user_id,purpose,expires_at)
        VALUES (%s,%s,%s,now()+%s*interval '1 minute')""",
        (digest(token),uid,purpose,ttl))
    return token

def begin_signup(conn, email):
    email = normalize_email(email)
    conn.execute("""INSERT INTO myr_native.users(email,disabled)
        VALUES (%s,true) ON CONFLICT(email) DO NOTHING""", (email,))
    row = conn.execute("""SELECT id,disabled,email_verified_at,password_hash
        FROM myr_native.users WHERE email=%s FOR UPDATE""", (email,)).fetchone()
    if not row or not row[1] or row[2] is not None or row[3] is not None:
        return None
    return new_token(conn,row[0],"verify_email")

def begin_reset(conn,email):
    email = normalize_email(email)
    row = conn.execute("""SELECT id FROM myr_native.users
        WHERE email=%s AND NOT disabled AND email_verified_at IS NOT NULL
        AND password_hash IS NOT NULL FOR UPDATE""",(email,)).fetchone()
    return new_token(conn,row[0],"reset_password") if row else None

def finish_password(conn,token,password,purpose,name=None):
    if purpose not in ("verify_email","reset_password"):
        raise ValueError("Invalid purpose")
    try:
        key=digest(token)
    except (ValueError,UnicodeError):
        return False
    row=conn.execute("""SELECT user_id FROM myr_native.auth_tokens
        WHERE token_digest=%s AND purpose=%s AND used_at IS NULL
        AND expires_at>now()""",(key,purpose)).fetchone()
    if not row:
        return False
    uid=row[0]
    user=conn.execute("""SELECT disabled,email_verified_at,password_hash
        FROM myr_native.users WHERE id=%s FOR UPDATE""",(uid,)).fetchone()
    if not user:
        return False
    disabled,verified,old_hash=user
    if purpose=="verify_email" and (not disabled or verified is not None or old_hash is not None):
        return False
    if purpose=="reset_password" and (disabled or verified is None or old_hash is None):
        return False
    ph=hash_password(password)
    consumed=conn.execute("""UPDATE myr_native.auth_tokens SET used_at=now()
        WHERE token_digest=%s AND user_id=%s AND purpose=%s AND used_at IS NULL
        AND expires_at>now() RETURNING user_id""",(key,uid,purpose)).fetchone()
    if not consumed:
        return False
    if purpose=="verify_email":
        conn.execute("""UPDATE myr_native.users SET password_hash=%s,
            name=%s,email_verified_at=now(),disabled=false WHERE id=%s""",
            (ph,str(name or "").strip()[:120],uid))
    else:
        conn.execute("UPDATE myr_native.users SET password_hash=%s WHERE id=%s",(ph,uid))
    conn.execute("""UPDATE myr_native.auth_tokens SET used_at=now()
        WHERE user_id=%s AND used_at IS NULL""",(uid,))
    conn.execute("""UPDATE myr_native.sessions SET revoked_at=now()
        WHERE user_id=%s AND revoked_at IS NULL""",(uid,))
    return True
