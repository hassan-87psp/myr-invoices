"""Private workflow core. Caller must supply a verified identity.
Only synthetic company operations are permitted until public auth and billing
are integrated. No email, external requests, or production account activation.
"""
from uuid import uuid4
from datetime import datetime, timezone
import re
from psycopg.types.json import Jsonb
from native_record_writes import require, WriteRejected, record_rows
from native_payment_ops import persist
from app import connect

TEAM_ROLES=("Admin","Accountant","Invoice Staff","Approver","Read-Only")

def onboarding(conn,uid,email,name):
    require(isinstance(name,str) and 1<=len(name.strip())<=120,"Invalid test company name")
    require(conn.execute("""SELECT 1 FROM myr_native.users WHERE id=%s AND email=%s
       AND email_verified_at IS NOT NULL AND NOT is_platform_admin FOR SHARE""",(uid,email)).fetchone() is not None,"Verified account required")
    cid=uuid4()
    name="TEST - "+name.strip()
    data={"id":str(cid),"name":name,"plan":"Starter","vpsSyntheticWriteTest":True,
          "approvalRequired":True,"prefix":"TEST-","nextNo":1001,"customers":[],
          "products":[],"invoices":[],"requests":[],"imports":[],"audit":[]}
    conn.execute("INSERT INTO myr_native.companies(id,name,created_by,data) VALUES(%s,%s,%s,%s)",(cid,name,uid,Jsonb(data)))
    conn.execute("INSERT INTO myr_native.company_members(company_id,email,role,status) VALUES(%s,%s,'Owner','active')",(cid,email))
    conn.execute("INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail) VALUES(%s,%s,%s,'company.create','Synthetic onboarding')",(cid,uid,email))
    return cid

def locked_company(conn,uid,email,cid,roles,*,synthetic=True):
    row=conn.execute("""SELECT c.version,c.data,m.role,c.plan FROM myr_native.companies c
      JOIN myr_native.company_members m ON m.company_id=c.id
      JOIN myr_native.users u ON u.email=m.email
      WHERE c.id=%s AND c.status='active' AND (c.data->>'vpsSyntheticWriteTest' IS NOT DISTINCT FROM 'true')=%s
      AND u.id=%s AND u.email=%s AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
      AND m.status='active' AND m.role=ANY(%s)
      FOR UPDATE OF c FOR SHARE OF m,u""",(cid,synthetic,uid,email,list(roles))).fetchone()
    require(row is not None,"Workflow not authorized")
    return row

def team_change(conn,uid,email,cid,operation,target,role=None,*,synthetic=True):
    version,data,_,plan=locked_company(conn,uid,email,cid,("Owner",),synthetic=synthetic)
    require(isinstance(target,str) and len(target)<=254 and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",target),"Invalid team email")
    target=target.lower()
    require(target!=email,"Owner membership is protected")
    member=conn.execute("SELECT role,status FROM myr_native.company_members WHERE company_id=%s AND email=%s FOR UPDATE",(cid,target)).fetchone()
    require(not member or member[0]!="Owner","Owner membership is protected")
    if operation=="invite":
        require(role in TEAM_ROLES and (not member or member[1]=="removed"),"Invalid or existing member")
        # Invitations are intentionally pending; no mail or automatic access.
        seat_limit=10 if synthetic else {"Starter":1,"Pro":3,"Business":10}.get(plan,1)
        require(conn.execute("SELECT count(*) FROM myr_native.company_members WHERE company_id=%s AND status IN ('active','invited')",(cid,)).fetchone()[0]<seat_limit,"Plan seat limit reached")
        conn.execute("""INSERT INTO myr_native.company_members(company_id,email,role,status)
          VALUES(%s,%s,%s,'invited') ON CONFLICT(company_id,email)
          DO UPDATE SET role=excluded.role,status='invited'""",(cid,target,role))
    elif operation=="role":
        require(role in TEAM_ROLES and member and member[1] in ("active","invited"),"Invalid role change")
        conn.execute("UPDATE myr_native.company_members SET role=%s WHERE company_id=%s AND email=%s",(role,cid,target))
    elif operation=="remove":
        require(member and member[1] in ("active","invited"),"Member unavailable")
        conn.execute("UPDATE myr_native.company_members SET status='removed' WHERE company_id=%s AND email=%s",(cid,target))
    else:
        raise WriteRejected("Unsupported team action")
    persist(conn,uid,email,cid,version,data,data,"team."+operation,target)
    return version+1

def invoice_workflow(conn,uid,email,cid,invoice_id,expected_version,action,*,synthetic=True):
    roles=("Owner","Admin","Accountant","Invoice Staff") if action=="request" else ("Owner","Admin","Approver")
    require(action in ("request","approve","reject"),"Invalid approval action")
    version,data,_,plan=locked_company(conn,uid,email,cid,roles,synthetic=synthetic)
    if not synthetic:
        require(plan=='Business' and data.get('approvalRequired') is True,'Business approval workflow not enabled')
    require(type(expected_version) is int and expected_version==version,"Company changed; reload")
    rows=record_rows(data,"invoices")
    inv=next((r for r in rows if r["id"]==invoice_id),None)
    require(inv is not None and inv.get("docType")=="01","Ordinary invoice required")
    require((inv.get("lhdn") or {}).get("status")=="Not Submitted" and not inv.get("payments") and not inv.get("share"),"Protected invoice")
    require(conn.execute("SELECT 1 FROM myr_native.lhdn_documents WHERE company_id=%s AND invoice_id=%s",(cid,invoice_id)).fetchone() is None,"Official invoice protected")
    require(inv.get("appStatus")==("Draft" if action=="request" else "Approval Pending"),"Invalid approval transition")
    if action!="request":
        require(inv.get("createdBy")!=email,"Creator cannot approve or reject own request")
    status={"request":"Approval Pending","approve":"Ready","reject":"Draft"}[action]
    updated={**inv,"appStatus":status,"approvalAction":action,"approvalActor":email,
             "approvalAt":datetime.now(timezone.utc).isoformat()}
    new={**data,"invoices":[updated if r["id"]==invoice_id else r for r in rows]}
    persist(conn,uid,email,cid,version,data,new,"invoice."+action,invoice_id)
    return {"version":version+1,"company_data":new,"record":updated}

def test():
    uid,staff,approver=uuid4(),uuid4(),uuid4()
    owner_email="owner-"+uid.hex+"@example.invalid"
    staff_email="staff-"+staff.hex+"@example.invalid"
    approver_email="approver-"+approver.hex+"@example.invalid"
    def reject(fn):
        try: fn()
        except WriteRejected: return
        raise AssertionError("Expected rejection")
    conn=connect()
    try:
        for user,email in ((uid,owner_email),(staff,staff_email),(approver,approver_email)):
            conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(user,email))
        cid=onboarding(conn,uid,owner_email,"Workflow rehearsal")
        assert team_change(conn,uid,owner_email,cid,"invite",staff_email,"Invoice Staff")==2
        assert team_change(conn,uid,owner_email,cid,"invite",approver_email,"Approver")==3
        reject(lambda:team_change(conn,uid,owner_email,cid,"role",owner_email,"Read-Only"))
        reject(lambda:team_change(conn,uid,owner_email,cid,"invite","new@example.invalid","Owner"))
        reject(lambda:team_change(conn,staff,staff_email,cid,"remove",approver_email))
        # Only the test harness activates its synthetic membership fixtures.
        conn.execute("UPDATE myr_native.company_members SET status='active' WHERE company_id=%s AND email IN (%s,%s)",(cid,staff_email,approver_email))
        row=conn.execute("SELECT data FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]
        inv={"id":"test-invoice","docType":"01","appStatus":"Draft","createdBy":staff_email,"lhdn":{"status":"Not Submitted"},"payments":[]}
        conn.execute("UPDATE myr_native.companies SET data=%s WHERE id=%s",(Jsonb({**row,"invoices":[inv]}),cid))
        assert invoice_workflow(conn,staff,staff_email,cid,"test-invoice",3,"request")["record"]["appStatus"]=="Approval Pending"
        reject(lambda:invoice_workflow(conn,staff,staff_email,cid,"test-invoice",4,"approve"))
        reject(lambda:invoice_workflow(conn,approver,approver_email,cid,"test-invoice",3,"approve"))
        assert invoice_workflow(conn,approver,approver_email,cid,"test-invoice",4,"reject")["record"]["appStatus"]=="Draft"
        assert invoice_workflow(conn,staff,staff_email,cid,"test-invoice",5,"request")["version"]==6
        assert invoice_workflow(conn,approver,approver_email,cid,"test-invoice",6,"approve")["record"]["appStatus"]=="Ready"
        assert team_change(conn,uid,owner_email,cid,"role",staff_email,"Read-Only")==8
        reject(lambda:invoice_workflow(conn,staff,staff_email,cid,"test-invoice",8,"request"))
        assert team_change(conn,uid,owner_email,cid,"remove",staff_email)==9
        assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s",(cid,)).fetchone()[0]==9
    finally:
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.users WHERE id=ANY(%s)",([uid,staff,approver],)).fetchone()[0]==0
    print("VPS_ONBOARDING_TEAM_APPROVAL_ROLLBACK_OK")
    print("Synthetic backend workflow only; HTTP/UI, invitations and real onboarding remain disabled.")

if __name__=="__main__":
    test()
