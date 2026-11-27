"""Sandbox-only CHIP intent lifecycle; never modifies company plans.
Provider results must come from the trusted server-side adapter, never a browser.
Transaction boundaries: commit reservation and dispatch claim before outbound POST.
"""
from uuid import UUID,uuid4
from billing_ledger_candidate import CATALOG,admin,require

def reserve(conn,actor,cid,plan):
    admin(conn,actor)
    require(isinstance(plan,str) and plan in CATALOG,"Unsupported plan")
    row=conn.execute("""SELECT 1 FROM myr_native.companies WHERE id=%s
      AND status='active' AND data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' FOR SHARE""",(cid,)).fetchone()
    require(row,"Active company required")
    iid=uuid4()
    conn.execute("""INSERT INTO myr_native.chip_test_intents(id,company_id,created_by,plan,amount_sen)
       VALUES(%s,%s,%s,%s,%s)""",(iid,cid,actor,plan,CATALOG[plan]))
    return iid

def claim(conn,actor,iid):
    admin(conn,actor)
    row=conn.execute("""UPDATE myr_native.chip_test_intents SET state='dispatching'
       WHERE id=%s AND state='reserved' RETURNING id,plan,amount_sen,mode,state,provider_id""",(iid,)).fetchone()
    require(row,"Dispatch already claimed or unavailable")
    return dict(zip(("id","plan","amount_sen","mode","state","provider_id"),row))

def unknown(conn,actor,iid):
    admin(conn,actor)
    require(conn.execute("""UPDATE myr_native.chip_test_intents SET state='outcome_unknown'
       WHERE id=%s AND state='dispatching' RETURNING id""",(iid,)).fetchone(),"Not dispatching")

def accept_creation(conn,actor,iid,result):
    admin(conn,actor)
    require(result.get("status")=="created" and result.get("entitlement_changed") is False,"Invalid trusted result")
    pid=UUID(result["provider_id"])
    require(conn.execute("""UPDATE myr_native.chip_test_intents SET state='created',provider_id=%s
       WHERE id=%s AND state='dispatching' RETURNING id""",(pid,iid)).fetchone(),"Invalid creation state")

def record_verified_test_paid(conn,actor,iid,result):
    admin(conn,actor)
    require(result.get("status")=="verified_test_paid" and result.get("entitlement_changed") is False,"Invalid trusted result")
    pid=UUID(result["provider_id"])
    row=conn.execute("""SELECT state,provider_id,amount_sen,currency
      FROM myr_native.chip_test_intents WHERE id=%s FOR UPDATE""",(iid,)).fetchone()
    require(row and row[1]==pid and row[0] in ("created","verified_test_paid"),"Unknown or mismatched purchase")
    if row[0]=="verified_test_paid":
        require(conn.execute("""SELECT 1 FROM myr_native.chip_test_receipts WHERE intent_id=%s
          AND provider_id=%s AND amount_sen=%s AND currency=%s""",(iid,pid,row[2],row[3])).fetchone(),"Receipt invariant broken")
        return "already_verified"
    conn.execute("""INSERT INTO myr_native.chip_test_receipts(intent_id,provider_id,amount_sen,currency)
       VALUES(%s,%s,%s,%s)""",(iid,pid,row[2],row[3]))
    conn.execute("""UPDATE myr_native.chip_test_intents SET state='verified_test_paid',verified_at=now()
       WHERE id=%s""",(iid,))
    return "verified_test_paid"

def admin_history(conn,actor):
    admin(conn,actor)
    rows=conn.execute("""SELECT id,company_id,plan,amount_sen,currency,state,provider_id,created_at,verified_at
      FROM myr_native.chip_test_intents ORDER BY created_at DESC,id LIMIT 100""").fetchall()
    return [dict(zip(("id","company_id","plan","amount_sen","currency","state","provider_id","created_at","verified_at"),r)) for r in rows]
