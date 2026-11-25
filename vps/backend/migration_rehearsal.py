"""Read-only source -> rollback-only destination migration rehearsal.
No credentials, exports, tokens or customer records are printed or committed.
Run only with the project's verified Supabase root CA and session pooler.
"""
import argparse
import getpass
import re
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from app import connect

PROJECT = "nynghaleoaqilewmhbdi"
BASE = {
    "companies": "id name tin plan status version data created_by created_at updated_at",
    "company_members": "company_id email name role status created_at",
    "lhdn_documents": "company_id invoice_id environment code_number submission_uid uuid long_id status validated_at errors accepted_at updated_at",
    "lhdn_events": "id company_id kind detail created_at",
    "public_links": "token company_id kind ref_id expires_at closed meta data submits created_at",
    "audit_logs": "id company_id actor actor_email action detail created_at",
}
ARCHIVE = (
    ("public","customer_records"),("public","product_records"),
    ("public","invoice_records"),("public","invoice_line_records"),
    ("public","payment_records"),("public","invoice_number_reservations"),
    ("public","lhdn_tenant_approvals"),("myr_internal","company_revisions"),
    ("myr_internal","company_snapshots"),
)
JSON_COLUMNS = {"data","meta","errors"}

def write_rows(dest, table, columns, rows):
    statement = sql.SQL("INSERT INTO myr_native.{} ({}) VALUES ({})").format(
        sql.Identifier(table),sql.SQL(",").join(map(sql.Identifier,columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns))
    for row in rows:
        dest.execute(statement,tuple(Jsonb(v) if k in JSON_COLUMNS and v is not None else v
                                     for k,v in zip(columns,row)))

def count(conn, schema, table):
    return conn.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
        sql.Identifier(schema),sql.Identifier(table))).fetchone()[0]

def rehearse(source,dest):
    if dest.execute("SELECT current_database(),current_user").fetchone()!=("myrinvoice","myrinvoice_app"):
        raise RuntimeError("Wrong destination")
    dest.execute("SET LOCAL lock_timeout='5s'")
    dest.execute("SET LOCAL statement_timeout='60s'")
    for table in ("users","sessions","auth_tokens","company_revisions",*BASE):
        dest.execute(sql.SQL("LOCK TABLE myr_native.{} IN SHARE ROW EXCLUSIVE MODE").format(sql.Identifier(table)))
        if count(dest,"myr_native",table):
            raise RuntimeError("Destination is not empty; no overwrite allowed")
    if count(source,"storage","objects"):
        raise RuntimeError("Storage objects require a separate migration")
    users=source.execute("""SELECT u.id,lower(u.email),p.name,u.email_confirmed_at,
        coalesce(p.is_platform_admin,false),u.created_at
        FROM auth.users u LEFT JOIN public.profiles p ON p.id=u.id ORDER BY u.id""").fetchall()
    if any(not r[1] for r in users):
        raise RuntimeError("Non-email identities require explicit migration mapping")
    for row in users:
        dest.execute("""INSERT INTO myr_native.users
            (id,email,name,email_verified_at,is_platform_admin,created_at,disabled)
            VALUES (%s,%s,%s,%s,%s,%s,true)""",row)
    if count(dest,"myr_native","users")!=len(users):
        raise RuntimeError("User count mismatch")
    print("users:",len(users),"mapped; disabled pending activation")
    for table,fields in BASE.items():
        cols=fields.split()
        rows=source.execute(sql.SQL("SELECT {} FROM public.{}").format(
            sql.SQL(",").join(map(sql.Identifier,cols)),sql.Identifier(table))).fetchall()
        if table=="public_links":
            pos=cols.index("closed")
            rows=[tuple(True if i==pos else v for i,v in enumerate(r)) for r in rows]
        write_rows(dest,table,cols,rows)
        if count(dest,"myr_native",table)!=len(rows):
            raise RuntimeError("Count mismatch: "+table)
        print(table+":",len(rows),"mapped")
    # Keep old mirror and recovery shapes intact in a private staging archive.
    # This is rolled back too; canonical normalized migration is a later step.
    dest.execute("""CREATE TABLE myr_native.migration_rehearsal_archive
        (source_table text NOT NULL, record jsonb NOT NULL)""")
    for schema,table in ARCHIVE:
        rows=source.execute(sql.SQL("SELECT to_jsonb(t) FROM {}.{} t").format(
            sql.Identifier(schema),sql.Identifier(table))).fetchall()
        for (value,) in rows:
            dest.execute("INSERT INTO myr_native.migration_rehearsal_archive VALUES (%s,%s)",
                         (schema+"."+table,Jsonb(value)))
        print(schema+"."+table+":",len(rows),"archive-mapped")
    print("MIGRATION_MAPPING_OK")

def main():
    parser=argparse.ArgumentParser(description="Rollback-only migration rehearsal")
    parser.add_argument("--host",required=True,help="Session pooler host from Supabase Connect")
    parser.add_argument("--ca",required=True,type=Path,help="Supabase root certificate path")
    args=parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+\.pooler\.supabase\.com",args.host):
        raise SystemExit("Invalid session pooler hostname")
    if not args.ca.is_file():
        raise SystemExit("Supabase CA certificate not found")
    pw=getpass.getpass("Existing Supabase database password (not VPS password): ")
    if not pw:
        raise SystemExit("Password required")
    try:
        with psycopg.connect(host=args.host,port=5432,dbname="postgres",
              user="postgres."+PROJECT,password=pw,sslmode="verify-full",
              sslrootcert=str(args.ca.resolve()),connect_timeout=10,
              options="-c default_transaction_read_only=on -c statement_timeout=60000") as source:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            with connect() as dest:
                try:
                    rehearse(source,dest)
                finally:
                    dest.rollback()
            source.rollback()
    except Exception as exc:
        # No exception text: database errors can contain sensitive row values.
        raise SystemExit("Rehearsal stopped: "+type(exc).__name__+
                         ". No destination changes committed.") from None
    print("MIGRATION_DRY_RUN_OK — source unchanged; destination rolled back.")

if __name__=="__main__":
    main()
