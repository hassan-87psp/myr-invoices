"""Unreleased billing integration router.
Uses existing VPS identity, company ownership and admin guards. Sandbox operations
are admin-only and explicitly gated. This router does not expose a live payment path.
"""
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel, Field, ConfigDict
from psycopg.errors import UniqueViolation
from billing_ledger_candidate import owner_history, CATALOG
from chip_test_lifecycle_candidate import admin_history
from chip_checkout_orchestration_candidate import create_checkout,reconcile_checkout
from chip_billing_view_candidate import admin_view

class SandboxCheckout(BaseModel):
    model_config=ConfigDict(extra="forbid")
    company_id:UUID
    plan:str=Field(max_length=16)

class SandboxVerify(BaseModel):
    model_config=ConfigDict(extra="forbid")
    intent_id:UUID

def build_router(db,identity,owner_company,admin_identity,require_sandbox,bridge):
    router=APIRouter(prefix="/billing")
    def guard_origin(request):
        if request.headers.get("origin")!="https://myrinvoice.com":
            raise HTTPException(403,"Origin rejected")
        if request.headers.get("content-type","").split(";",1)[0].strip().lower()!="application/json":
            raise HTTPException(415,"JSON required")
    @router.get("/customer/{company_id}")
    def customer(company_id:UUID,request:Request,conn=Depends(db)):
        conn.execute("SET TRANSACTION READ ONLY")
        profile=identity(conn,request)
        owner_company(conn,profile,company_id)
        try:
            rows=owner_history(conn,profile["id"],company_id)
        except ValueError:
            raise HTTPException(403,"Billing access denied") from None
        return {"history":[dict(zip(("period_start","plan","amount_sen","currency","status","recorded_at"),row)) for row in rows],
                "checkout_enabled":False,"auto_renewal_enabled":False,"gateway":"CHIP"}
    @router.get("/admin/sandbox")
    def sandbox_status(request:Request,conn=Depends(db)):
        conn.execute("SET TRANSACTION READ ONLY")
        profile=admin_identity(conn,request)
        try:return admin_view(admin_history(conn,profile["id"]))
        except ValueError:raise HTTPException(403,"Admin required") from None
    @router.post("/admin/sandbox/checkout")
    def sandbox_checkout(body:SandboxCheckout,request:Request,conn=Depends(db)):
        guard_origin(request)
        profile=admin_identity(conn,request)
        require_sandbox()
        if body.plan not in CATALOG:raise HTTPException(422,"Unknown plan")
        try:return create_checkout(conn,profile["id"],body.company_id,body.plan,bridge)
        except (ValueError,UniqueViolation):
            conn.rollback()
            raise HTTPException(409,"Checkout unavailable or existing payment requires reconciliation") from None
    @router.post("/admin/sandbox/verify")
    def sandbox_verify(body:SandboxVerify,request:Request,conn=Depends(db)):
        guard_origin(request)
        profile=admin_identity(conn,request)
        require_sandbox()
        try:return reconcile_checkout(conn,profile["id"],body.intent_id,bridge)
        except (ValueError,KeyError,TypeError,RuntimeError,UniqueViolation):
            conn.rollback()
            raise HTTPException(409,"Payment not verified; reconcile before retrying") from None
    return router
