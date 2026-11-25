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
