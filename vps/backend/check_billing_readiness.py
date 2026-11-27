"""Read-only billing audit for native VPS data. No payment or plan mutations.
Accepted-document row counts are a lower bound, not a complete attempt ledger.
Outputs aggregate counts only; no customer names, IDs, invoice data or secrets.
"""
import json
from app import connect

CATALOG = {"Starter": (900,100,1), "Pro": (1900,1000,3), "Business": (3900,3000,10)}

def audit(conn):
    conn.execute("SET TRANSACTION READ ONLY")
    assert conn.execute("SELECT current_database(),current_user").fetchone()==("myrinvoice","myrinvoice_app")
    rows=conn.execute("""
      WITH bounds AS (
        SELECT date_trunc('month',now() AT TIME ZONE 'Asia/Kuala_Lumpur') AS month_start
      ), stats AS (
        SELECT c.plan,c.status,
          (SELECT count(*) FROM myr_native.company_members m WHERE m.company_id=c.id AND m.status IN ('active','invited')) AS seats,
          (SELECT count(*) FROM myr_native.lhdn_documents d WHERE d.company_id=c.id
            AND d.accepted_at >= b.month_start AT TIME ZONE 'Asia/Kuala_Lumpur'
            AND d.accepted_at < (b.month_start+interval '1 month') AT TIME ZONE 'Asia/Kuala_Lumpur') AS accepted_rows
        FROM myr_native.companies c CROSS JOIN bounds b
        WHERE c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
      )
      SELECT plan,status,count(*),max(seats),max(accepted_rows),
        count(*) FILTER (WHERE seats>CASE plan WHEN 'Starter' THEN 1 WHEN 'Pro' THEN 3 WHEN 'Business' THEN 10 ELSE 0 END),
        count(*) FILTER (WHERE accepted_rows>CASE plan WHEN 'Starter' THEN 100 WHEN 'Pro' THEN 1000 WHEN 'Business' THEN 3000 ELSE 0 END)
      FROM stats GROUP BY plan,status ORDER BY plan,status
    """).fetchall()
    schema=conn.execute("""SELECT table_name FROM information_schema.tables
      WHERE table_schema='myr_native' AND table_type='BASE TABLE'
      AND (table_name LIKE '%billing%' OR table_name LIKE '%subscription%'
      OR table_name LIKE '%payment%' OR table_name LIKE '%usage%')
      ORDER BY table_name""").fetchall()
    groups=[]
    for plan,status,count,seats,docs,seat_over,doc_over in rows:
        known=plan in CATALOG
        groups.append(dict(plan=plan if known else "other",status=status if status in ("active","suspended") else "other",
          companies=count,max_seats=seats,max_accepted_document_rows=docs,
          over_seat_limit=seat_over if known else None,over_document_limit_lower_bound=doc_over if known else None))
    return {"catalog":[dict(plan=k,monthly_price_sen=v[0],documents=v[1],seats=v[2]) for k,v in CATALOG.items()],
      "company_groups":groups,"billing_related_native_tables":[r[0] for r in schema],
      "accepted_rows_are_lower_bound":True,"paid_subscription_verified":False,
      "payment_gateway_verified":False,"writes_performed":False}

if __name__=="__main__":
    with connect() as conn:
        result=audit(conn)
    print(json.dumps(result,indent=2))
    print("MYR_BILLING_READ_ONLY_AUDIT_OK")
