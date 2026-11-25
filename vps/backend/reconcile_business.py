"""Read-only reconciliation against a freshly supplied source fingerprint.
Does not freeze, copy, delete, or switch any production data.
"""
import argparse
import json
from app import connect

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--checksum",required=True)
    p.add_argument("--companies",type=int,required=True)
    p.add_argument("--invoices",type=int,required=True)
    p.add_argument("--customers",type=int,required=True)
    p.add_argument("--products",type=int,required=True)
    p.add_argument("--members",type=int,required=True)
    p.add_argument("--links",type=int,required=True)
    p.add_argument("--audit",type=int,required=True)
    args=p.parse_args()
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert conn.execute("SELECT current_database(),current_user").fetchone()==("myrinvoice","myrinvoice_app")
        row=conn.execute("""SELECT count(*),
            coalesce(sum(jsonb_array_length(coalesce(data->'invoices','[]'::jsonb))),0),
            coalesce(sum(jsonb_array_length(coalesce(data->'customers','[]'::jsonb))),0),
            coalesce(sum(jsonb_array_length(coalesce(data->'products','[]'::jsonb))),0),
            md5(string_agg(id::text || ':' || md5(data::text), ',' ORDER BY id))
            FROM myr_native.companies WHERE data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'""").fetchone()
        actual=dict(zip(("companies","invoices","customers","products","checksum"),row))
        for label,table in (("members","company_members"),("links","public_links"),("audit","audit_logs")):
            actual[label]=conn.execute("SELECT count(*) FROM myr_native."+table+" t JOIN myr_native.companies c ON c.id=t.company_id WHERE c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'").fetchone()[0]
        actual["audit"]+=conn.execute("SELECT count(*) FROM myr_native.audit_logs WHERE company_id IS NULL").fetchone()[0]
        synthetic=conn.execute("SELECT count(*) FROM myr_native.companies WHERE data->>'vpsSyntheticWriteTest'='true'").fetchone()[0]
        print("REAL_VPS_DATA",json.dumps(actual,default=str))
        print("SYNTHETIC_COMPANIES_EXCLUDED",synthetic)
        print("SOURCE_ARCHIVE_ROWS",conn.execute("SELECT count(*) FROM myr_native.migration_source_archive").fetchone()[0])
        expected=vars(args)
        mismatch=[k for k,v in expected.items() if actual[k]!=v]
        if mismatch:
            raise SystemExit("RECONCILIATION_BLOCKED: "+", ".join(mismatch))
        print("MYR_REAL_DATA_RECONCILIATION_OK")
        print("Point-in-time check only. Source remains writable; no production switch.")
if __name__=="__main__":
    main()
