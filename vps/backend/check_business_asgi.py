"""Test the business candidate routes with verified-identity fixtures.
All transactions roll back. The running service remains hard-disabled.
"""
import asyncio
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
    conn=connect()
    def verify(token):
        if token=="owner": return uid,email
        if token=="stranger": return other,"stranger-"+other.hex+"@example.invalid"
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
    finally:
        b.api.dependency_overrides.pop(b.db,None)
        conn.rollback()
        conn.close()
    with connect() as check:
        assert check.execute("SELECT count(*) FROM myr_native.users WHERE id=%s",(uid,)).fetchone()[0]==0
    print("MYR_BUSINESS_ASGI_ROLLBACK_OK")
    print("Production cutover gate remains closed.")

if __name__=="__main__":
    main()
