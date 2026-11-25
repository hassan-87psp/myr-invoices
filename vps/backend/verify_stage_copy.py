"""Verify staged copy without modifying real data."""
from app import connect
from psycopg import sql

with connect() as conn:
    conn.execute("SET TRANSACTION READ ONLY")
    if conn.execute("SELECT current_database(),current_user").fetchone()!=("myrinvoice","myrinvoice_app"):
        raise SystemExit("Wrong database")
    for table in ("users","companies","company_members","lhdn_documents","lhdn_events","public_links","audit_logs","migration_source_archive"):
        count=conn.execute(sql.SQL("SELECT count(*) FROM myr_native.{}").format(sql.Identifier(table))).fetchone()[0]
        print(f"{table}: {count}")
    if conn.execute("SELECT count(*) FROM myr_native.companies").fetchone()[0]==0:
        raise SystemExit("No staged companies found")
    for name,n in conn.execute("SELECT source_table,count(*) FROM myr_native.migration_source_archive GROUP BY source_table ORDER BY source_table"):
        print(f"{name}: {n} archived")
    if conn.execute("SELECT count(*) FROM myr_native.public_links WHERE NOT closed").fetchone()[0]:
        raise SystemExit("Unexpected open public links")
    for key in ("invoices","customers","products","quotations"):
        n=conn.execute("""SELECT coalesce(sum(CASE WHEN jsonb_typeof(data->%s)='array'
           THEN jsonb_array_length(data->%s) ELSE 0 END),0) FROM myr_native.companies""",(key,key)).fetchone()[0]
        print(f"Company JSON {key}: {n}")
    print("VPS_MIGRATED_DATA_VERIFIED")
    conn.rollback()
