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
    row=conn.execute("""SELECT (SELECT count(*) FROM myr_native.users),
        (SELECT count(*) FROM myr_native.companies),
        (SELECT count(*) FROM myr_native.companies WHERE status='active')""").fetchone()
    return dict(zip(("users","companies","active_companies"),row))

import admin_email  # registers private admin-only email routes
