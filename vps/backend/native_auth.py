"""Native authentication and tenant authorization primitives.

Staging only: not exposed by HTTP routes. Callers must supply a database
transaction; HTTP rate limits, verified email delivery and migration remain
required before enabling public authentication.
"""
import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY = HASHER.hash(secrets.token_urlsafe(32))
VALID_ROLES = frozenset(("Owner", "Admin", "Accountant", "Invoice Staff",
                         "Approver", "Read-Only"))

def hash_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("Password must contain 12 to 128 characters")
    return HASHER.hash(password)

def authenticate(conn, email, password):
    if not isinstance(email, str) or not isinstance(password, str):
        return None
    if not 1 <= len(email) <= 254 or not 1 <= len(password) <= 128:
        return None
    row = conn.execute(
        """SELECT id, password_hash, email_verified_at, disabled
           FROM myr_native.users WHERE email = %s""",
        (email.strip().lower(),),
    ).fetchone()
    try:
        valid = HASHER.verify(row[1] if row and row[1] else DUMMY, password)
    except (InvalidHashError, VerificationError):
        valid = False
    if not row or not row[1] or not valid or not row[2] or row[3]:
        return None
    return row[0]

def digest(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ValueError("Invalid token")
    return hashlib.sha256(token.encode("ascii")).digest()

def issue_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    result = conn.execute(
        """INSERT INTO myr_native.sessions(token_digest,user_id,expires_at)
           SELECT %s,id,now()+interval '12 hours' FROM myr_native.users
           WHERE id=%s AND NOT disabled AND email_verified_at IS NOT NULL
             AND password_hash IS NOT NULL RETURNING user_id""",
        (digest(token), user_id),
    ).fetchone()
    if not result:
        raise PermissionError("Account unavailable")
    return token

def session_user(conn, token):
    try:
        key = digest(token)
    except (ValueError, UnicodeError):
        return None
    row = conn.execute(
        """SELECT u.id,u.email,u.name,u.is_platform_admin
           FROM myr_native.sessions s JOIN myr_native.users u ON u.id=s.user_id
           WHERE s.token_digest=%s AND s.revoked_at IS NULL
             AND s.expires_at>now() AND NOT u.disabled
             AND u.email_verified_at IS NOT NULL""", (key,),
    ).fetchone()
    return row

def revoke_session(conn, token):
    try:
        key = digest(token)
    except (ValueError, UnicodeError):
        return
    conn.execute(
        """UPDATE myr_native.sessions SET revoked_at=now()
           WHERE token_digest=%s AND revoked_at IS NULL""", (key,),
    )

def tenant_role(conn, user_id, company_id, allowed_roles=None):
    if allowed_roles is not None and not set(allowed_roles).issubset(VALID_ROLES):
        raise ValueError("Unknown role")
    row = conn.execute(
        """SELECT m.role FROM myr_native.users u
           JOIN myr_native.company_members m ON m.email=u.email
           JOIN myr_native.companies c ON c.id=m.company_id
           WHERE u.id=%s AND c.id=%s AND c.status='active'
             AND m.status='active' AND NOT u.disabled
             AND u.email_verified_at IS NOT NULL""",
        (user_id, company_id),
    ).fetchone()
    if not row or (allowed_roles is not None and row[0] not in allowed_roles):
        return None
    return row[0]
