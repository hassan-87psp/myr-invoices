"""Test the business candidate routes with verified-identity fixtures.
All transactions roll back. The running service remains hard-disabled.
"""
import asyncio
import sys
from unittest.mock import patch
from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from psycopg.types.json import Jsonb
import business_api as b
import check_hybrid_asgi as harness
from app import connect

def main():
    uid,other=uuid4(),uuid4()
    email="business-"+uid.hex+"@example.invalid"
    staff,approver=uuid4(),uuid4()
    staff_email="staff-"+staff.hex+"@example.invalid"
    approver_email="approver-"+approver.hex+"@example.invalid"
    conn=connect()
    def verify(token):
        if token=="owner": return uid,email
        if token=="stranger": return other,"stranger-"+other.hex+"@example.invalid"
        if token=="staff": return staff,staff_email
        if token=="approver": return approver,approver_email
        raise HTTPException(401,"Test auth rejected")
    def override():
        with conn.transaction():
            yield harness.RollbackConnection(conn)
    def call(path,body,status=200,token="owner"):
        code,data=asyncio.run(harness.request("POST",path,body,token))
        assert code==status,(path,code,status,data)
        return data
    profile={k:"" for k in ("name","tin","brn","sst","ttx","msic","msicDesc","email","phone")}
    profile.update(name="Rollback business",tin="C12345678901",brn="TEST",msic="46900",msicDesc="Test",phone="000",addr={"line":"Test","city":"Test","postcode":"00000","state":"14","country":"MYS"})
    try:
        # Start an outer transaction BEFORE any request enters conn.transaction().
        # Otherwise psycopg commits each top-level request transaction.
        conn.execute("SELECT 1")
        b.api.dependency_overrides[b.db]=override
        with patch.object(harness,"api",b.api),patch.object(b,"verify_user",verify):
            call("/onboard",{"p_profile":profile},401,None)
            call("/onboard",{"p_profile":profile},503)
            with patch.object(b,"require_cutover",lambda:None):
                result=call("/onboard",{"p_profile":profile})
                cid=result["id"]
                call("/onboard",{"p_profile":profile},409)
                assert call("/profile",{"p_company_id":cid,"p_version":1,"p_profile":profile})["version"]==2
                call("/profile",{"p_company_id":cid,"p_version":1,"p_profile":profile},409)
                customer={"id":str(uuid4()),"name":"Test customer"}
                product={"id":str(uuid4()),"name":"Test product"}
                def record(kind,data,expected=None,auto=False):
                    return {"p_company_id":cid,"p_kind":kind,"p_record":data,"p_expected":expected,"p_auto":auto}
                assert call("/records",record("customers",customer))["version"]==3
                assert call("/records",record("products",product))["version"]==4
                call("/records",record("products",product),409)
                call("/records",record("products",product),403,"stranger")
                invoice={"id":str(uuid4()),"number":"INV-1001","docType":"01","appStatus":"Draft","customerId":customer["id"],"items":[{"id":"line","qty":1,"price":10000,"discount":0,"taxRate":0}],"payments":[]}
                result=call("/records",record("invoices",invoice,auto=True))
                assert result["version"]==5 and result["record"]["number"]=="INV-1001"
                pay={"p_company_id":cid,"p_invoice_id":invoice["id"],"p_payment":{"id":"pay1","amount":5000,"date":datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat(),"method":"Cash","ref":""}}
                assert call("/payments",pay)["version"]==6
                assert call("/payments",pay)["existing"] is True
                assert call("/delete",{"p_company_id":cid,"p_kind":"products","p_expected":product})["version"]==7
            call("/records",record("customers",{"id":"blocked","name":"Blocked"}),503)
            assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]==7
            team={"p_company_id":cid,"p_operation":"invite","p_email":staff_email,"p_role":"Invoice Staff"}
            call("/team",team,503)
            code,_=asyncio.run(harness.request("GET","/admin/summary",token="owner"))
            assert code==403
            with patch.object(b,"require_cutover",lambda:None):
                call("/team",team,409) # Starter already has its only seat.
                conn.execute("UPDATE myr_native.companies SET plan='Business',data=jsonb_set(jsonb_set(data,'{plan}','\"Business\"'::jsonb),'{approvalRequired}','true'::jsonb) WHERE id=%s",(cid,))
                assert call("/team",team)["version"]==8
                assert call("/team",{**team,"p_email":approver_email,"p_role":"Approver"})["version"]==9
                for actor,addr in ((staff,staff_email),(approver,approver_email)):
                    conn.execute("INSERT INTO myr_native.users(id,email,email_verified_at,disabled) VALUES(%s,%s,now(),true)",(actor,addr))
                # Activate only test fixtures; actual invitations remain pending.
                conn.execute("UPDATE myr_native.company_members SET status='active' WHERE company_id=%s AND email IN (%s,%s)",(cid,staff_email,approver_email))
                draft={**invoice,"id":str(uuid4()),"number":"INV-1002","payments":[]}
                assert call("/records",record("invoices",draft,auto=True))["version"]==10
                approval={"p_company_id":cid,"p_invoice_id":draft["id"],"p_version":10,"p_action":"request"}
                assert call("/approval",approval)["record"]["appStatus"]=="Approval Pending"
                approval={**approval,"p_version":11,"p_action":"approve"}
                call("/approval",approval,409) # Creator cannot approve own invoice.
                call("/approval",approval,409,"staff")
                assert call("/approval",approval,200,"approver")["record"]["appStatus"]=="Ready"
                assert call("/team",{**team,"p_operation":"remove"})["version"]==13
            call("/approval",{**approval,"p_version":13},503,"approver")
            assert conn.execute("SELECT version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()[0]==13
            print("MYR_BUSINESS_TEAM_APPROVAL_ROLLBACK_OK")
    finally:
        b.api.dependency_overrides.pop(b.db,None)
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.users WHERE id=ANY(%s)",([uid,staff,approver],)).fetchone()[0]==0
    print("MYR_BUSINESS_ASGI_ROLLBACK_OK")
    print("Production cutover gate remains closed.")

def cleanup_failed_fixture():
    # Only the exact previous failed test fixture, never a real company.
    # Refuse ambiguous candidates or any unexpected related data.
    with connect() as conn:
        rows=conn.execute("""SELECT u.id,u.email,c.id,c.data,c.version
            FROM myr_native.users u JOIN myr_native.companies c ON c.created_by=u.id
            WHERE u.email='business-'||replace(u.id::text,'-','')||'@example.invalid'
            AND u.disabled AND NOT u.is_platform_admin AND u.password_hash IS NULL
            AND c.name='Rollback business' AND c.tin='C12345678901'
            AND c.plan='Starter' FOR UPDATE OF u,c""").fetchall()
        if not rows:
            print("MYR_FAILED_TEST_FIXTURE_NONE")
            return
        if len(rows)!=1:
            raise RuntimeError("Ambiguous failed test fixtures; manual review required")
        uid,email,cid,d,version=rows[0]
        inv=d.get("invoices",[])
        customers=d.get("customers",[])
        assert version==7 and d.get("name")=="Rollback business" and d.get("brn")=="TEST"
        assert d.get("products")==[] and len(customers)==1 and customers[0].get("name")=="Test customer"
        assert len(inv)==1 and inv[0].get("number")=="INV-1001" and inv[0].get("createdBy")==email
        assert inv[0].get("customerId")==customers[0].get("id") and inv[0].get("appStatus")=="Draft"
        pays=inv[0].get("payments",[])
        assert len(pays)==1 and pays[0].get("id")=="pay1" and pays[0].get("amount")==5000
        assert conn.execute("SELECT count(*) FROM myr_native.companies WHERE created_by=%s",(uid,)).fetchone()[0]==1
        assert conn.execute("SELECT company_id,email,role,status FROM myr_native.company_members WHERE company_id=%s OR email=%s",(cid,email)).fetchall()==[(cid,email,"Owner","active")]
        for table in ("lhdn_documents","lhdn_events","public_links"):
            assert conn.execute("SELECT count(*) FROM myr_native."+table+" WHERE company_id=%s",(cid,)).fetchone()[0]==0
        assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s AND actor=%s",(cid,uid)).fetchone()[0]==7
        assert conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id=%s OR actor=%s",(cid,uid)).fetchone()[0]==7
        conn.execute("DELETE FROM myr_native.audit_logs WHERE company_id=%s AND actor=%s",(cid,uid))
        conn.execute("DELETE FROM myr_native.companies WHERE id=%s AND created_by=%s",(cid,uid))
        conn.execute("DELETE FROM myr_native.users WHERE id=%s AND email=%s",(uid,email))
    print("MYR_FAILED_TEST_FIXTURE_REMOVED")

if __name__=="__main__":
    if "--cleanup-failed-fixture" in sys.argv:
        cleanup_failed_fixture()
    main()
