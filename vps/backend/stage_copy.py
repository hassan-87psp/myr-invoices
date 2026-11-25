"""Encrypted business-data snapshot, then isolated staging copy.
Source is read-only; no authentication credentials or live cutover.
"""
import argparse
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg
from psycopg import sql
from app import connect
from migration_rehearsal import PROJECT, BASE, ARCHIVE, rehearse

def gpg_run(args, password, data):
    # Passphrase travels over an anonymous pipe, never argv, environment or disk.
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(write_fd,"wb") as writer:
            writer.write(password.encode("utf-8")+b"\n")
        return subprocess.run(
            ["gpg","--batch","--yes","--no-symkey-cache","--pinentry-mode","loopback",
             "--passphrase-fd",str(read_fd),*args],
            pass_fds=(read_fd,),input=data,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,check=True).stdout
    finally:
        os.close(read_fd)

def snapshot(source,password):
    tables={}
    tables["auth.users_account_metadata"]= [r[0] for r in source.execute(
        """SELECT to_jsonb(u)::text FROM (SELECT id,email,email_confirmed_at,created_at
        FROM auth.users) u ORDER BY u.id""").fetchall()]
    for schema,table in [("public","profiles"),*[("public",t) for t in BASE],*ARCHIVE]:
        rows=source.execute(sql.SQL("SELECT to_jsonb(t)::text FROM {}.{} t").format(
            sql.Identifier(schema),sql.Identifier(table))).fetchall()
        tables[schema+"."+table]=[r[0] for r in rows]
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload=json.dumps({"format":"myr-business-snapshot-v1","project":PROJECT,
        "utc":stamp,"rows_as_json_text":tables},ensure_ascii=False).encode("utf-8")
    folder=Path.home()/"myr-private-backups"
    folder.mkdir(mode=0o700,exist_ok=True)
    folder.chmod(0o700)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        encrypted=Path(tmp)/"snapshot.json.gpg"
        gpg_run(["--symmetric","--cipher-algo","AES256","--output",str(encrypted)],
                password,payload)
        restored=gpg_run(["--decrypt",str(encrypted)],password,None)
        if hashlib.sha256(restored).digest()!=hashlib.sha256(payload).digest():
            raise RuntimeError("Encrypted backup verification failed")
        encrypted.chmod(0o600)
        target=folder/("supabase-business-"+stamp+".json.gpg")
        if target.exists():
            raise RuntimeError("Backup filename already exists")
        encrypted.rename(target)
    print("ENCRYPTED_BUSINESS_BACKUP_OK",target.name,flush=True)

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument("--host",required=True)
    parser.add_argument("--ca",required=True,type=Path)
    args=parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+\.pooler\.supabase\.com",args.host) or not args.ca.is_file():
        raise SystemExit("Invalid source host or CA")
    if not shutil.which("gpg"):
        raise SystemExit("Install gnupg first, then rerun.")
    source_password=getpass.getpass("Supabase database password: ")
    password=getpass.getpass("New backup encryption passphrase (at least 16 characters): ")
    if not source_password or not 16<=len(password)<=128 or "\n" in password or "\r" in password:
        raise SystemExit("Invalid password or passphrase.")
    if password!=getpass.getpass("Repeat backup encryption passphrase: "):
        raise SystemExit("Passphrases do not match.")
    try:
        with psycopg.connect(host=args.host,port=5432,dbname="postgres",
                user="postgres."+PROJECT,password=source_password,sslmode="verify-full",
                sslrootcert=str(args.ca.resolve()),connect_timeout=10,
                options="-c default_transaction_read_only=on -c statement_timeout=60000") as source:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if source.execute("SELECT count(*) FROM storage.objects").fetchone()[0]:
                raise RuntimeError("Storage needs separate backup")
            snapshot(source,password)
            with connect() as dest:
                try:
                    rehearse(source,dest)
                    src=source.execute("SELECT id,md5(data::text) FROM public.companies ORDER BY id").fetchall()
                    dst=dest.execute("SELECT id,md5(data::text) FROM myr_native.companies ORDER BY id").fetchall()
                    if src!=dst:
                        raise RuntimeError("Company JSON checksum mismatch")
                    for table in ("audit_logs","lhdn_events"):
                        next_id=dest.execute(sql.SQL("SELECT coalesce(max(id),0)+1 FROM myr_native.{}").format(sql.Identifier(table))).fetchone()[0]
                        dest.execute(sql.SQL("ALTER TABLE myr_native.{} ALTER COLUMN id RESTART WITH {}").format(sql.Identifier(table),sql.Literal(next_id)))
                    dest.execute("ALTER TABLE myr_native.migration_rehearsal_archive RENAME TO migration_source_archive")
                    dest.commit()
                except BaseException:
                    dest.rollback()
                    raise
            source.rollback()
    except Exception as exc:
        raise SystemExit("Stage copy stopped: "+type(exc).__name__+". Check backup and staging state.") from None
    print("VPS_STAGE_COPY_OK")
    print("Accounts remain disabled; public links closed. No DNS changes or source writes.")
    print("Business snapshot excludes password hashes and source service configuration; offsite backup still required.")

if __name__=="__main__":
    main()
