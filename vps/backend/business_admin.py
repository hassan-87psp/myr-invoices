"""Administrative controls and public-link migration checks for the native API.
No public anonymous routes or live write enabling in this module.
"""
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row
from native_record_writes import require, WriteRejected
from app import connect

PLANS=("Starter","Pro","Business","Accountant","Enterprise")

def admin_company_rows(conn,profile):
    require(profile.get("is_platform_admin") is True,"Platform administrator required")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""SELECT c.id,c.name,c.tin,c.plan,c.status,c.created_at,c.version,
            (SELECT m.email FROM myr_native.company_members m WHERE m.company_id=c.id AND m.role='Owner' AND m.status='active' ORDER BY m.email LIMIT 1) owner,
            (SELECT count(*) FROM myr_native.company_members m WHERE m.company_id=c.id AND m.status='active') members,
            jsonb_array_length(coalesce(c.data->'invoices','[]'::jsonb)) invoices,
            (SELECT count(*) FROM myr_native.lhdn_documents d WHERE d.company_id=c.id AND d.status='Valid') valid,
            (SELECT count(*) FROM myr_native.lhdn_documents d WHERE d.company_id=c.id AND d.status='Invalid') invalid
            FROM myr_native.companies c WHERE c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
            ORDER BY c.created_at DESC,c.id LIMIT 500""")
        return cur.fetchall()

def set_company(conn,profile,cid,version,status=None,plan=None):
    require(profile.get("is_platform_admin") is True,"Platform administrator required")
    require(type(version) is int and version>0,"Invalid version")
    require(status in (None,"active","suspended") and plan in (None,*PLANS) and (status is not None or plan is not None),"Invalid change")
    actor=conn.execute("SELECT email,is_platform_admin FROM myr_native.users WHERE id=%s AND email_verified_at IS NOT NULL FOR SHARE",(profile["id"],)).fetchone()
    require(actor is not None and actor[1] and actor[0]==profile["email"],"Administrator no longer authorized")
    row=conn.execute("""SELECT version,data,status,plan FROM myr_native.companies WHERE id=%s
        AND data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' FOR UPDATE""",(cid,)).fetchone()
    require(row is not None and row[0]==version,"Company changed or unavailable")
    _,data,old_status,old_plan=row
    new_status=status or old_status
    new_plan=plan or old_plan
    limit={"Starter":1,"Pro":3,"Business":10}.get(new_plan)
    if plan and limit is not None:
        count=conn.execute("SELECT count(*) FROM myr_native.company_members WHERE company_id=%s AND status IN ('active','invited')",(cid,)).fetchone()[0]
        require(count<=limit,"Remove extra team seats before downgrade")
    updated={**data,"plan":new_plan}
    if new_plan!="Business":
        updated["approvalRequired"]=False
    conn.execute("INSERT INTO myr_native.company_revisions(company_id,version,data) VALUES(%s,%s,%s) ON CONFLICT(company_id,version) DO NOTHING",(cid,version,Jsonb(data)))
    conn.execute("UPDATE myr_native.companies SET status=%s,plan=%s,data=%s,version=%s,updated_at=now() WHERE id=%s",(new_status,new_plan,Jsonb(updated),version+1,cid))
    conn.execute("INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail) VALUES(%s,%s,%s,'admin.company',%s)",(cid,profile["id"],profile["email"],"status="+new_status+"; plan="+new_plan))
    return {"id":str(cid),"version":version+1,"status":new_status,"plan":new_plan}

def link_inventory(conn):
    today=datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date()
    rows=conn.execute("""SELECT l.kind,count(*),count(*) FILTER (WHERE l.closed),
        count(*) FILTER (WHERE NOT l.closed AND l.expires_at>=%s),
        count(*) FILTER (WHERE l.kind='invoice' AND NOT EXISTS
           (SELECT 1 FROM jsonb_array_elements(coalesce(c.data->'invoices','[]'::jsonb)) i WHERE i->>'id'=l.ref_id)
         OR l.kind='qr' AND NOT EXISTS
           (SELECT 1 FROM jsonb_array_elements(coalesce(c.data->'requests','[]'::jsonb)) r WHERE r->>'id'=l.ref_id))
        FROM myr_native.public_links l JOIN myr_native.companies c ON c.id=l.company_id
        WHERE c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' GROUP BY l.kind ORDER BY l.kind""",(today,)).fetchall()
    return [dict(zip(("kind","total","closed","unexpired_open","orphan_reference"),r)) for r in rows]

def test():
    admin,owner,cid,synth=uuid4(),uuid4(),uuid4(),uuid4()
    ae="admin-"+admin.hex+"@example.invalid"
    oe="owner-"+owner.hex+"@example.invalid"
    p={"id":admin,"email":ae,"is_platform_admin":True}
    conn=connect()
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    try:
        for uid,email,flag in ((admin,ae,True),(owner,oe,False)):
            conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,is_platform_admin,disabled) VALUES(%s,%s,now(),%s,true)",(uid,email,flag))
        for c,marker in ((cid,False),(synth,True)):
            conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,'Admin rollback',%s,%s)",(c,owner,Jsonb({"plan":"Starter","invoices":[],"requests":[{"id":"qr1"}],"vpsSyntheticWriteTest":marker})))
            conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(c,oe))
        reject(lambda:admin_company_rows(conn,{"is_platform_admin":False}))
        assert cid in [r["id"] for r in admin_company_rows(conn,p)]
        assert synth not in [r["id"] for r in admin_company_rows(conn,p)]
        reject(lambda:set_company(conn,p,synth,1,"suspended"))
        assert set_company(conn,p,cid,1,"suspended","Business")["version"]==2
        reject(lambda:set_company(conn,p,cid,1,"active"))
        assert set_company(conn,p,cid,2,"active","Starter")["status"]=="active"
        before=link_inventory(conn)
        token=uuid4().hex
        conn.execute("INSERT INTO myr_native.public_links(token,company_id,kind,ref_id,expires_at,closed) VALUES(%s,%s,'qr','qr1',current_date+1,true)",(token,cid))
        after=link_inventory(conn)
        assert sum(r["total"] for r in after)==sum(r["total"] for r in before)+1
        assert sum(r["orphan_reference"] for r in after)==sum(r["orphan_reference"] for r in before)
    finally:
        conn.rollback()
        conn.close()
    with connect() as c:
        assert c.execute("SELECT count(*) FROM myr_native.users WHERE id=ANY(%s)",([admin,owner],)).fetchone()[0]==0
        print("MYR_PUBLIC_LINK_INVENTORY",link_inventory(c))
    print("MYR_ADMIN_AND_LINK_INVENTORY_ROLLBACK_OK")

if __name__=="__main__":
    test()
