"""Restricted company profile edits for the private synthetic workspace."""
from uuid import uuid4
from psycopg.types.json import Jsonb
from native_record_writes import require, WriteRejected
from native_payment_ops import persist
from app import connect

PROFILE_FIELDS=("name","tin","brn","sst","ttx","msic","msicDesc","email","phone")
ADDRESS_FIELDS=("line","city","postcode","state","country")

def save_profile(conn,uid,email,cid,expected_version,profile):
    require(type(expected_version) is int and expected_version>0,"Invalid company version")
    require(isinstance(profile,dict) and set(profile)==set(PROFILE_FIELDS)|{"addr"},"Unexpected profile fields")
    require(all(isinstance(profile[k],str) and len(profile[k])<=300 for k in PROFILE_FIELDS),"Invalid company profile")
    addr=profile["addr"]
    require(isinstance(addr,dict) and set(addr)==set(ADDRESS_FIELDS) and all(isinstance(v,str) and len(v)<=300 for v in addr.values()),"Invalid address")
    row=conn.execute("""SELECT c.version,c.data,c.name FROM myr_native.companies c
        JOIN myr_native.company_members m ON m.company_id=c.id
        JOIN myr_native.users u ON u.email=m.email
        WHERE c.id=%s AND c.status='active' AND u.id=%s AND u.email=%s
        AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
        AND m.status='active' AND m.role IN ('Owner','Admin')
        FOR UPDATE OF c FOR SHARE OF m,u""",(cid,uid,email)).fetchone()
    require(row is not None,"Company settings not authorized")
    version,previous,name=row
    require(previous.get("vpsSyntheticWriteTest") is True,"Only synthetic settings enabled")
    require(version==expected_version,"Company changed; reload before saving")
    require(profile["name"]==name,"Synthetic company name is fixed")
    data={**previous,**profile}
    persist(conn,uid,email,cid,version,previous,data,"settings.company","Synthetic profile updated")
    conn.execute("UPDATE myr_native.companies SET tin=%s WHERE id=%s",(profile["tin"].upper(),cid))
    return {"version":version+1,"company_data":data}

def test():
    uid,cid=uuid4(),uuid4()
    email="test-"+uid.hex+"@example.invalid"
    name="Synthetic profile rollback"
    p={k:"" for k in PROFILE_FIELDS}
    p.update(name=name,phone="000",addr={k:"" for k in ADDRESS_FIELDS})
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    conn=connect()
    try:
        conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(uid,email))
        conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,%s,%s,%s)",(cid,name,uid,Jsonb({"vpsSyntheticWriteTest":True,"invoices":[{"id":"keep"}]})))
        conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
        r=save_profile(conn,uid,email,cid,1,p)
        assert r["version"]==2 and r["company_data"]["invoices"]==[{"id":"keep"}]
        reject(lambda:save_profile(conn,uid,email,cid,1,p))
        reject(lambda:save_profile(conn,uid,email,cid,2,{**p,"plan":"Enterprise"}))
        reject(lambda:save_profile(conn,uid,email,cid,2,{**p,"name":"Other"}))
        conn.execute("UPDATE myr_native.company_members SET role='Invoice Staff' WHERE company_id=%s AND email=%s",(cid,email))
        reject(lambda:save_profile(conn,uid,email,cid,2,p))
    finally:
        conn.rollback()
        conn.close()
    print("VPS_COMPANY_PROFILE_ROLLBACK_OK")
if __name__=="__main__":
    test()
