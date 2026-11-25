"""Local encrypted PostgreSQL backup with archive and encryption validation.
Key remains on this VPS; independent offsite copy and restore drill still needed.
"""
import datetime, hashlib, os, secrets, subprocess, tempfile
from pathlib import Path

def main():
    os.umask(0o077)
    home=Path.home()
    cfg=home/".config/myrinvoice"
    folder=home/"myr-private-backups/native"
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    folder.chmod(0o700)
    key=cfg/"native-backup-key"
    try:
        with key.open("x") as f:
            f.write(secrets.token_hex(32)+"\n")
    except FileExistsError:
        pass
    if key.is_symlink() or not key.is_file() or key.stat().st_mode & 0o077:
        raise SystemExit("Unsafe local backup key permissions")
    pw=(cfg/"db-password").read_text().rstrip("\n")
    if not pw or "\n" in pw or "\r" in pw:
        raise SystemExit("Invalid database password file")
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with tempfile.TemporaryDirectory(prefix=".backup-",dir=folder) as tmp:
        root=Path(tmp)
        pgpass=root/"pgpass"
        pgpass.write_text("127.0.0.1:5432:myrinvoice:myrinvoice_app:"+pw.replace("\\","\\\\").replace(":","\\:")+"\n")
        pgpass.chmod(0o600)
        env={**os.environ,"PGPASSFILE":str(pgpass),"PGSSLMODE":"require"}
        env.pop("PGPASSWORD",None)
        plain=root/"db.dump"
        encrypted=root/"db.dump.gpg"
        subprocess.run(["pg_dump","--host=127.0.0.1","--port=5432","--username=myrinvoice_app","--dbname=myrinvoice","--format=custom","--no-password","--file",str(plain)],env=env,check=True)
        subprocess.run(["pg_restore","--list",str(plain)],stdout=subprocess.DEVNULL,check=True)
        gpg=["gpg","--batch","--yes","--no-symkey-cache","--pinentry-mode","loopback","--passphrase-file",str(key)]
        subprocess.run(gpg+["--symmetric","--cipher-algo","AES256","--output",str(encrypted),str(plain)],check=True)
        def file_hash(path):
            with path.open("rb") as f: return hashlib.file_digest(f,"sha256").digest()
        restored=root/"restored.dump"
        subprocess.run(gpg+["--decrypt","--output",str(restored),str(encrypted)],check=True)
        if file_hash(plain)!=file_hash(restored):
            raise SystemExit("Backup decrypt verification failed")
        target=folder/("native-"+stamp+".dump.gpg")
        encrypted.chmod(0o600)
        checksum=root/"archive.sha256"
        checksum.write_text(file_hash(encrypted).hex()+"  "+target.name+"\n")
        checksum.chmod(0o600)
        encrypted.rename(target)
        checksum.rename(target.with_name(target.name+".sha256"))
    # Prune only our own completed native backup files, after successful verification.
    cutoff=datetime.datetime.now(datetime.timezone.utc).timestamp()-14*86400
    for p in folder.glob("native-*.dump.gpg"):
        if p.is_file() and not p.is_symlink() and p.stat().st_mtime<cutoff:
            p.unlink()
            checksum=p.with_name(p.name+".sha256")
            if checksum.is_file() and not checksum.is_symlink(): checksum.unlink()
    print("VPS_ENCRYPTED_NATIVE_BACKUP_OK",target.name)
    print("Local backup and checksum verified; offsite transfer must be checked independently.")

if __name__=="__main__":
    main()
