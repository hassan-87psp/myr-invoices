"""Billing API candidate, not mounted by production.
The caller must supply the existing authenticated identity and cutover guards.
No checkout, automatic activation, or verification of bank transactions.
"""
from datetime import date
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field,StrictInt
from psycopg.errors import UniqueViolation
from billing_ledger_candidate import create_period,record_receipt,owner_history

class PeriodBody(BaseModel):
    company_id:UUID
    period_start:date

class ReceiptBody(BaseModel):
    company_id:UUID
    period_id:UUID
    amount_sen:StrictInt=Field(gt=0,le=3900)
    method:str=Field(max_length=24)
    reference:str=Field(min_length=1,max_length=100)

def build_router(db,identity,owner_company,admin_identity,require_cutover):
    router=APIRouter(prefix="/billing")
    def origin(request):
        if request.headers.get("origin")!="https://myrinvoice.com":
            raise HTTPException(403,"Origin rejected")
        if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
            raise HTTPException(415,"JSON required")
    def write(conn,operation):
        try:
            out=operation()
            conn.commit()
            return out
        except (ValueError,UniqueViolation):
            conn.rollback()
            raise HTTPException(409,"Billing operation rejected") from None

    @router.get("/history/{company_id}")
    def history(company_id:UUID,request:Request,conn=Depends(db)):
        conn.execute("SET TRANSACTION READ ONLY")
        profile=identity(conn,request)
        owner_company(conn,profile,company_id)
        try:
            rows=owner_history(conn,profile["id"],company_id)
        except ValueError:
            raise HTTPException(403,"Billing access denied") from None
        return {"history":[dict(zip(("period_start","plan","amount_sen","currency","status","recorded_at"),r)) for r in rows],
                "gateway_enabled":False,"payment_basis":"manual operator record"}

    @router.post("/admin/period")
    def period(body:PeriodBody,request:Request,conn=Depends(db)):
        origin(request)
        profile=admin_identity(conn,request)
        require_cutover()
        return write(conn,lambda:{"period_id":str(create_period(conn,profile["id"],body.company_id,body.period_start))})

    @router.post("/admin/receipt")
    def receipt(body:ReceiptBody,request:Request,conn=Depends(db)):
        origin(request)
        profile=admin_identity(conn,request)
        require_cutover()
        def operation():
            record_receipt(conn,profile["id"],body.company_id,body.period_id,body.amount_sen,body.method,body.reference)
            return {"status":"recorded_paid","gateway_verified":False,"entitlement_changed":False}
        return write(conn,operation)
    return router
