"""Private billing ledger candidate. Not mounted on the live API.
Manual receipts record independently verified payments; no gateway or automatic entitlement.
"""
from datetime import date,datetime
from pathlib import Path
from uuid import uuid4
import re
CATALOG={"Starter":900,"Pro":1900,"Business":3900}

def require(ok,message):
    if not ok: raise ValueError(message)

def admin(conn,actor):
    require(conn.execute("""SELECT 1 FROM myr_native.users WHERE id=%s
      AND is_platform_admin AND NOT disabled AND email_verified_at IS NOT NULL FOR SHARE""",(actor,)).fetchone(),"Admin required")

def create_period(conn,actor,cid,month):
    require(type(month) is date and month.day==1,"First day of billing month required")
    admin(conn,actor)
    row=conn.execute("""SELECT plan,status FROM myr_native.companies WHERE id=%s FOR UPDATE""",(cid,)).fetchone()
    require(row and row[1]=="active" and row[0] in CATALOG,"Unsupported company or plan")
    plan=row[0]; pid=uuid4()
    conn.execute("""INSERT INTO myr_native.billing_periods(id,company_id,period_start,plan,amount_sen,created_by)
      VALUES(%s,%s,%s,%s,%s,%s)""",(pid,cid,month,plan,CATALOG[plan],actor))
    return pid

def record_receipt(conn,actor,cid,pid,amount_sen,method,reference):
    admin(conn,actor)
    require(type(amount_sen) is int and amount_sen>0,"Invalid amount")
    require(method in ("bank_transfer","duitnow","other_manual"),"Invalid method")
    require(isinstance(reference,str) and re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}",reference),"Invalid receipt reference")
    row=conn.execute("""SELECT amount_sen,currency FROM myr_native.billing_periods
       WHERE id=%s AND company_id=%s FOR UPDATE""",(pid,cid)).fetchone()
    require(row and row[0]==amount_sen,"Period or amount mismatch")
    conn.execute("""INSERT INTO myr_native.billing_receipts(period_id,amount_sen,currency,method,reference,recorded_by)
      VALUES(%s,%s,%s,%s,%s,%s)""",(pid,amount_sen,row[1],method,reference.upper(),actor))

def owner_history(conn,actor,cid):
    require(conn.execute("""SELECT 1 FROM myr_native.users u
      JOIN myr_native.company_members m ON m.email=u.email
      WHERE u.id=%s AND NOT u.disabled AND u.email_verified_at IS NOT NULL
      AND m.company_id=%s AND m.role='Owner' AND m.status='active'""",(actor,cid)).fetchone(),"Owner required")
    return conn.execute("""SELECT p.period_start,p.plan,p.amount_sen,p.currency,
      CASE WHEN r.period_id IS NULL THEN 'unpaid' ELSE 'recorded_paid' END,r.recorded_at
      FROM myr_native.billing_periods p LEFT JOIN myr_native.billing_receipts r ON r.period_id=p.id
      WHERE p.company_id=%s ORDER BY p.period_start DESC LIMIT 120""",(cid,)).fetchall()
