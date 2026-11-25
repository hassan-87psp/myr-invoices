"""Authenticated read-only preview of native staging records.
Serve only via a loopback SSH tunnel; not the production frontend.
"""
from pathlib import Path
from fastapi.responses import HTMLResponse
from staging_api import api

@api.get("/", response_class=HTMLResponse)
def preview():
    return HTMLResponse(
        (Path(__file__).parent/"preview.html").read_text(encoding="utf-8"),
        headers={"Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
                 "Referrer-Policy":"no-referrer","X-Content-Type-Options":"nosniff"})

from fastapi import Depends, HTTPException, Request
from staging_api import db, identity

@api.get("/admin/summary")
def admin_summary(request: Request, conn=Depends(db)):
    _,_,_,admin=identity(conn,request)
    if not admin:
        raise HTTPException(403,"Platform administrator required")
    row=conn.execute("""SELECT
        (SELECT count(*) FROM myr_native.users),
        count(*) FILTER (WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'),
        count(*) FILTER (WHERE status='active' AND data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'),
        count(*) FILTER (WHERE data->>'vpsSyntheticWriteTest'='true'),
        coalesce(sum(CASE WHEN jsonb_typeof(data->'invoices')='array' THEN jsonb_array_length(data->'invoices') ELSE 0 END)
          FILTER (WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'),0),
        coalesce(sum(CASE WHEN jsonb_typeof(data->'customers')='array' THEN jsonb_array_length(data->'customers') ELSE 0 END)
          FILTER (WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'),0)
        FROM myr_native.companies""").fetchone()
    return dict(zip(("users","companies","active_companies","test_companies","business_invoices","business_customers"),row))

# SMTP and LHDN are delegated to Supabase by the operator.
# Do not expose or use the previous VPS mail configuration endpoints.
from app import health as database_health

@api.get("/health")
def private_health():
    return database_health()

# Private original-UI preview, separate from production and the native admin.
from fastapi.staticfiles import StaticFiles
from hybrid_workspace import ORIGIN
import hybrid_workspace  # registers verified read-only endpoint
import hybrid_write_test  # synthetic-only write rehearsal endpoints

@api.middleware("http")
async def website_headers(request: Request, call_next):
    response=await call_next(request)
    if request.url.path.startswith("/website"):
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self' "+ORIGIN+"; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; worker-src 'none'"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Cache-Control"]="no-store"
    return response

api.mount("/website",StaticFiles(directory=Path.home()/"myr-staging/hybrid-website",html=True,check_dir=False),name="private_original_ui")

api.mount("/website-write",StaticFiles(directory=Path.home()/"myr-staging/hybrid-write-website",html=True,check_dir=False),name="private_synthetic_write_ui")
