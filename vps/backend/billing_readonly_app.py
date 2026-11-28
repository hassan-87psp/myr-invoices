"""Read-only production billing status sidecar. No checkout or write endpoints."""
from uuid import UUID
from fastapi import FastAPI,Depends,Request,HTTPException
from business_api import db,identity,owner_company,admin_identity
from billing_ledger_candidate import owner_history
from chip_test_lifecycle_candidate import admin_history
from chip_billing_view_candidate import admin_view

api=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
@api.get("/health")
def health(conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    for table in ("billing_periods","billing_receipts","chip_test_intents","chip_test_receipts"):
        conn.execute("SELECT 1 FROM myr_native."+table+" LIMIT 1").fetchall()
    return {"status":"ok","mode":"read_only"}

@api.get("/billing/customer")
def customer(company_id:UUID,request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    profile=identity(conn,request)
    owner_company(conn,profile,company_id)
    try:rows=owner_history(conn,profile["id"],company_id)
    except ValueError:raise HTTPException(403,"Billing access denied") from None
    return {"history":[dict(zip(("period_start","plan","amount_sen","currency","status","recorded_at"),r)) for r in rows],
            "checkout_enabled":False,"auto_renewal_enabled":False,"gateway":"CHIP"}

@api.get("/billing/admin/sandbox")
def sandbox(request:Request,conn=Depends(db)):
    conn.execute("SET TRANSACTION READ ONLY")
    profile=admin_identity(conn,request)
    try:return admin_view(admin_history(conn,profile["id"]))
    except ValueError:raise HTTPException(403,"Admin required") from None
