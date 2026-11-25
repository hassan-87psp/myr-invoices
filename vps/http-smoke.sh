#!/usr/bin/env bash
# Temporary loopback-only HTTP smoke test. Does not install a service.
set -euo pipefail
cd "$(dirname "$0")/.."
test "$(id -un)" = myradmin
"$HOME/myr-venv/bin/python" -B - <<'PY'
import json
import socket
import subprocess
import sys
import time
import urllib.request

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
p = subprocess.Popen([sys.executable, "-B", "-m", "uvicorn", "app:app",
                      "--app-dir", "vps/backend", "--host", "127.0.0.1",
                      "--port", str(port)], stdout=subprocess.DEVNULL)
try:
    for attempt in range(30):
        if p.poll() is not None:
            raise SystemExit("API process stopped unexpectedly.")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ) as response:
                data = json.load(response)
                if data == {"status": "ok", "database": "connected", "stage": "foundation"}:
                    print(json.dumps(data))
                    print("VPS_HTTP_HEALTH_OK")
                    break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise SystemExit("API health failed. Check local database configuration.")
finally:
    p.terminate()
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
print("Temporary API stopped; no public service or DNS changes.")
PY
