"""Real-company onboarding primitives. Only callable behind the cutover gate.
Supabase verified UUID/email is the identity authority. No password or role
from the browser is accepted. No email delivery or LHDN calls here.
"""
import re
from uuid import uuid4
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from native_record_writes import require, WriteRejected
from native_payment_ops import persist
from app import connect

FIELDS=("name","tin","brn","sst","ttx","msic","msicDesc","email","phone")
ADDR=("line","city","postcode","state","country")

def provision(conn,uid,email):
    require(isinstance(email,str) and len(email)<=254 and email==email.lower(),"Invalid verified email")
    conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true) ON CONFLICT DO NOTHING",(uid,email))
    row=conn.execute("SELECT id,email,is_platform_admin FROM myr_native.users WHERE id=%s FOR UPDATE",(uid,)).fetchone()
    require(row is not None and row[1]==email,"Account identity conflict; contact support")
    return row

def validate_profile(value):
    require(isinstance(value,dict) and set(value)==set(FIELDS)|{"addr"},"Unexpected profile fields")
    require(all(isinstance(value[k],str) and len(value[k])<=300 for k in FIELDS),"Invalid profile fields")
    addr=value["addr"]
    require(isinstance(addr,dict) and set(addr)==set(ADDR) and all(isinstance(v,str) and len(v)<=300 for v in addr.values()),"Invalid address")
    p={k:value[k].strip() for k in FIELDS}
    p["addr"]={k:addr[k].strip() for k in ADDR}
    p["tin"]=p["tin"].upper()
    require(p["name"] and p["brn"] and p["phone"] and p["msicDesc"] and p["addr"]["line"] and p["addr"]["city"],"Required company fields missing")
    require(re.fullmatch(r"(EI\d{11}|[A-Z]{1,2}\d{8,12})",p["tin"]) is not None,"Invalid TIN format")
    require(re.fullmatch(r"\d{5}",p["msic"]) is not None,"Invalid MSIC format")
    require(p["addr"]["country"]=="MYS","Malaysian company address required")
    return p

def create_company(conn,uid,email,profile):
    p=validate_profile(profile)
    row=provision(conn,uid,email)
    require(not row[2],"Platform admin cannot create a real company via owner onboarding")
    require(conn.execute("""SELECT count(*) FROM myr_native.companies WHERE created_by=%s
        AND data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'""",(uid,)).fetchone()[0]==0,"Initial Starter company already exists")
    cid=uuid4()
    now=datetime.now(timezone.utc).isoformat()
    data={**p,"id":str(cid),"plan":"Starter","prefix":"INV-","nextNo":1001,
          "approvalRequired":False,"logo":"","customers":[],"products":[],"invoices":[],
          "requests":[],"imports":[],"audit":[],"usage":{},"createdAt":now,
          "lhdn":{"env":"sandbox","health":"not_connected","proxyUrl":"","incidents":[]},
          "reminders":{"enabled":True,"before":3,"onDue":True,"after":7}}
    conn.execute("INSERT INTO myr_native.companies(id,name,tin,created_by,data) VALUES(%s,%s,%s,%s,%s)",(cid,p["name"],p["tin"],uid,Jsonb(data)))
    conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
    conn.execute("INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail) VALUES(%s,%s,%s,'company.create','Initial Starter company')",(cid,uid,email))
    return {"id":str(cid),"version":1,"company_data":data}

def update_profile(conn,uid,email,cid,version,value):
    p=validate_profile(value)
    require(type(version) is int and version>0,"Invalid version")
    row=conn.execute("""SELECT c.version,c.data FROM myr_native.companies c
        JOIN myr_native.company_members m ON m.company_id=c.id JOIN myr_native.users u ON u.email=m.email
        WHERE c.id=%s AND c.status='active' AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
        AND u.id=%s AND u.email=%s AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
        AND m.status='active' AND m.role='Owner' FOR UPDATE OF c FOR SHARE OF m,u""",(cid,uid,email)).fetchone()
    require(row is not None,"Company unavailable")
    require(row[0]==version,"Company changed; reload")
    new={**row[1],**p}
    persist(conn,uid,email,cid,version,row[1],new,"settings.company","Profile updated")
    conn.execute("UPDATE myr_native.companies SET name=%s,tin=%s WHERE id=%s",(p["name"],p["tin"],cid))
    return {"version":version+1,"company_data":new}

def test():
    uid,other=uuid4(),uuid4()
    email="onboard-"+uid.hex+"@example.invalid"
    p={k:"" for k in FIELDS}
    p.update(name="Rollback fixture",tin="C12345678901",brn="TEST",msic="46900",msicDesc="Test",phone="000",addr={"line":"Test","city":"Test","postcode":"00000","state":"14","country":"MYS"})
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    conn=connect()
    try:
        r=create_company(conn,uid,email,p)
        cid=r["id"]
        assert r["company_data"]["plan"]=="Starter"
        reject(lambda:create_company(conn,uid,email,p))
        reject(lambda:provision(conn,other,email))
        reject(lambda:update_profile(conn,uid,email,cid,1,{**p,"plan":"Enterprise"}))
        reject(lambda:update_profile(conn,other,email,cid,1,p))
        assert update_profile(conn,uid,email,cid,1,{**p,"name":"Renamed fixture"})["version"]==2
        reject(lambda:update_profile(conn,uid,email,cid,1,p))
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.users WHERE id=%s",(uid,)).fetchone()[0]==0
    print("MYR_REAL_ONBOARDING_PROFILE_ROLLBACK_OK")

if __name__=="__main__":
    test()
