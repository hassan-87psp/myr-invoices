"""Local-only VPS backend foundation. No customer-data endpoints yet."""
import os
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="MYR Invoice staging API", docs_url=None, redoc_url=None,
              openapi_url=None)
PASSWORD_FILE = Path.home() / ".config" / "myrinvoice" / "db-password"

def connect():
    return psycopg.connect(
        host="127.0.0.1", port=5432, dbname="myrinvoice",
        user="myrinvoice_app", password=PASSWORD_FILE.read_text().rstrip("\n"),
        connect_timeout=5, sslmode="require",
    )

@app.get("/health")
def health():
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user")
            if cur.fetchone() != ("myrinvoice", "myrinvoice_app"):
                raise RuntimeError("Unexpected database identity")
        return {"status": "ok", "database": "connected", "stage": "foundation"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
