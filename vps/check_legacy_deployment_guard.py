"""Offline safety regression. No VPS, production paths, or database connections."""
import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "vps/install-core-backend-auto-deploy.sh"

def main():
    for marker in ("native-auth-pilot-enabled", "frontend-autodeploy/worker.py"):
        for symlink in (False, True):
            for args in ([], ["--run"]):
                with tempfile.TemporaryDirectory() as tmp:
                    root = pathlib.Path(tmp)
                    home = root / "home"
                    config = home / ".config/myrinvoice"
                    target = config / marker
                    target.parent.mkdir(parents=True)
                    if symlink:
                        target.symlink_to(root / "missing")
                    else:
                        target.write_text("fixture")
                    bin_dir = root / "bin"
                    bin_dir.mkdir()
                    fake_id = bin_dir / "id"
                    fake_id.write_text("#!/bin/sh\nprintf 'myradmin\\n'\n")
                    fake_id.chmod(0o700)
                    fake_systemctl = bin_dir / "systemctl"
                    fake_systemctl.write_text("#!/bin/sh\ntouch \"$HOME/systemctl-called\"\nexit 99\n")
                    fake_systemctl.chmod(0o700)
                    env = {"HOME": str(home), "PATH": str(bin_dir) + ":/usr/bin:/bin", "LANG": "C"}
                    result = subprocess.run(["bash", str(SCRIPT), *args], env=env,
                                            capture_output=True, text=True, timeout=10)
                    assert result.returncode == 78, result.stderr
                    assert "MYR_LEGACY_BACKEND_DEPLOY_BLOCKED" in result.stderr
                    assert not (home / "systemctl-called").exists()
    print("MYR_LEGACY_DEPLOYMENT_GUARD_OFFLINE_OK")

if __name__ == "__main__":
    main()
