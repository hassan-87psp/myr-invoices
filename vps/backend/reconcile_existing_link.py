"""Reconcile the one existing unexpired invoice link without leaking its token.
Private VPS copy only. No source mutation and no release of anonymous routes.
This deliberately refuses multi-link datasets rather than guessing closed flags.
"""
import argparse
from pathlib import Path
from app import connect
from business_links import read_link
from business_admin import link_inventory

def fingerprint(conn,ignore_closed=False):
    expr="(to_jsonb(l)-'closed')::text" if ignore_closed else "to_jsonb(l)::text"
    return conn.execute("""SELECT count(*),md5(string_agg(md5("""+expr+"""),',' ORDER BY l.token))
        FROM myr_native.public_links l JOIN myr_native.companies c ON c.id=l.company_id
        WHERE c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'""").fetchone()

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--without-closed",required=True)
    p.add_argument("--full",required=True)
    p.add_argument("--apply-private",action="store_true")
    args=p.parse_args()
    if (Path.home()/".config/myrinvoice/production-writes-enabled").exists():
        raise SystemExit("Production marker exists; refuse staging link reconciliation")
    with connect() as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='30s'")
        assert conn.execute("SELECT current_database(),current_user").fetchone()==("myrinvoice","myrinvoice_app")
        conn.execute("LOCK TABLE myr_native.companies, myr_native.public_links IN SHARE ROW EXCLUSIVE MODE")
        if fingerprint(conn,True)!=(1,args.without_closed):
            raise SystemExit("Link content differs from source or link count changed; no changes")
        row=conn.execute("""SELECT l.token,l.kind,l.closed FROM myr_native.public_links l
            JOIN myr_native.companies c ON c.id=l.company_id
            WHERE c.status='active' AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
            AND l.expires_at >= (now() AT TIME ZONE 'Asia/Kuala_Lumpur')::date
            AND l.kind='invoice'
            AND EXISTS (SELECT 1 FROM jsonb_array_elements(c.data->'invoices') i WHERE i->>'id'=l.ref_id)""").fetchone()
        if row is None:
            raise SystemExit("No eligible source-matching invoice link")
        conn.execute("UPDATE myr_native.public_links SET closed=false WHERE token=%s",(row[0],))
        if fingerprint(conn)!=(1,args.full):
            raise SystemExit("Full source checksum mismatch; no changes")
        result=read_link(conn,row[0])
        assert result["kind"]=="invoice" and result["data"] is None
        assert result["meta"]["invoice"] and result["meta"]["company"]
        assert not any(x["orphan_reference"] for x in link_inventory(conn))
        if args.apply_private:
            conn.commit()
            print("MYR_PRIVATE_LINK_RECONCILED")
        else:
            conn.rollback()
            print("MYR_LINK_RECONCILIATION_ROLLBACK_OK")
    print("Source link untouched; private candidate API remains gated. Recheck against frozen source at cutover.")

if __name__=="__main__":
    main()
