"""Private Direct ERP sidecar rehearsal. No deployment or provider access.
Copy this file and candidate dependencies into a separate private directory;
use the existing pinned production backend on PYTHONPATH for native auth.
This release is deliberately guard-only; credential entry and all provider
operations remain hard-disabled. Do not route public traffic yet.
"""
from fastapi import FastAPI, HTTPException, Request
from uuid import UUID
from app import connect
from business_api import native_enabled, require_cutover, identity, owner_company
import business_native_auth as native

api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@api.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

def direct_pilot_operation(request,body):
    # Existing native-only session and tenant authorization; never accept a
    # caller-supplied TIN, owner or credential scope. No secret-bearing logs.
    import lhdn_direct_pilot_candidate as pilot
    from lhdn_direct_vault_candidate import Scope
    if not native_enabled() or not request.cookies.get(native.COOKIE) or request.headers.get("authorization"):
        raise HTTPException(401,"Native business sign-in required")
    require_cutover()
    try:
        cid=UUID(body.get("p_company_id",""))
        if str(cid)!=body.get("p_company_id"):raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise HTTPException(422,"Invalid request data") from None
    with connect() as conn:
        profile=identity(conn,request)
        owner_company(conn,profile,cid,lock=True)
        # Hold current owner and company locks for this bounded pilot operation.
        row=conn.execute("""SELECT c.tin,c.data->>'brn',c.version
            FROM myr_native.companies c JOIN myr_native.users u ON u.id=%s
            WHERE c.id=%s AND c.status='active' AND u.disabled=false
            AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
            AND c.data->>'demo' IS DISTINCT FROM 'true'
            AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
            FOR SHARE OF u""",(profile["id"],cid)).fetchone()
        if not row:raise HTTPException(404,"Company unavailable")
        try:
            scope=Scope(str(cid),row[0],row[1])
            return pilot.unavailable()  # Hard-disabled: separate vault/grant release required.
        except (ValueError,TypeError,KeyError):
            raise HTTPException(409,"Connection setup unavailable or changed. Refresh and contact support if needed.") from None
        except Exception:
            raise HTTPException(503,"Secure connection temporarily unavailable") from None

@api.post("/lhdn/direct-pilot")
async def direct_pilot(request:Request):
    # This candidate is not exposed by the pinned production backend.
    # No provider request or vault operation before authentication and grant.
    if request.headers.get("origin")!="https://myrinvoice.com":
        raise HTTPException(403,"Origin rejected")
    if request.headers.get("content-type","").split(";")[0].strip().lower()!="application/json":
        raise HTTPException(415,"JSON request required")
    if not native_enabled() or not request.cookies.get(native.COOKIE) or request.headers.get("authorization"):
        raise HTTPException(401,"Native business sign-in required")
    import json
    from starlette.concurrency import run_in_threadpool
    from lhdn_protocol_candidate import _unique_object
    try:
        raw=bytearray()
        async for part in request.stream():
            if len(raw)+len(part)>4096:raise ValueError()
            raw.extend(part)
        body=json.loads(raw,object_pairs_hook=_unique_object)
        if not isinstance(body,dict):raise ValueError()
    except (ValueError,TypeError):
        raise HTTPException(422,"Invalid request data") from None
    return await run_in_threadpool(direct_pilot_operation,request,body)

if __name__ == "__main__":
    import asyncio
    from unittest.mock import patch
    import sys
    # The existing ASGI harness performs requests in process, without a
    # socket, HTTP transport, production database or provider credentials.
    import check_hybrid_asgi as harness
    module = sys.modules[__name__]
    async def run():
        harness.api = api
        origin = (b"origin", b"https://myrinvoice.com")
        with patch.object(module, "native_enabled", return_value=True), \
             patch.object(module, "connect", side_effect=AssertionError("DB access forbidden")):
            for path, method, headers, token, expected in (
                ("/lhdn/direct-pilot","POST",[origin],None,401),
                ("/lhdn/direct-pilot","POST",[],None,403),
                ("/lhdn/direct-pilot","POST",[(b"origin",b"https://invalid.example")],None,403),
                ("/lhdn/direct-pilot","POST",[origin],"legacy-token",401),
                ("/lhdn/direct-pilot","GET",[origin],None,405),
                ("/health","GET",[],None,404),
                ("/workspace","GET",[],None,404),
                ("/docs","GET",[],None,404),
            ):
                code, _ = await harness.request(method,path,{},token=token,extra_headers=headers)
                assert code == expected, (method,path,code,expected)
        print("MYR_DIRECT_SIDECAR_GUARDS_OK")
    asyncio.run(run())
