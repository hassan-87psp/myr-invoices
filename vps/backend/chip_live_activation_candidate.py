"""Review-only atomic activation for a trusted, server-verified live CHIP payment.
No browser payload or direct webhook may call this. Not mounted in production.
Caller must roll back on errors and commit only after all operations succeed.
"""
from uuid import UUID
from datetime import date
from psycopg.types.json import Jsonb
from billing_ledger_candidate import admin,require
from chip_subscription_policy_candidate import paid_period

def activate(conn,actor,iid,verified,today,*,live_enabled=False):
    require(live_enabled is True,"Live activation disabled")
    require(type(today) is date,"Invalid billing date")
    admin(conn,actor)
    # Always lock company before intent; existing company writes also lock company.
    company=conn.execute("SELECT company_id FROM myr_native.chip_live_intents WHERE id=%s",(iid,)).fetchone()
    require(company,"Unknown intent")
    cid=company[0]
    row=conn.execute("""SELECT version,data,status,plan FROM myr_native.companies WHERE id=%s
      AND data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true' FOR UPDATE""",(cid,)).fetchone()
    require(row and row[2]=="active","Company unavailable")
    intent=conn.execute("""SELECT provider_id,brand_id,plan,amount_sen,currency,period_start,period_end,anchor_day,state
      FROM myr_native.chip_live_intents WHERE id=%s AND company_id=%s FOR UPDATE""",(iid,cid)).fetchone()
    require(intent,"Intent unavailable")
    pid,brand,plan,amount,currency,start,end,anchor,state=intent
    require(verified.get("brand_id")==brand and verified.get("reference")=="myr-live-"+str(iid),"Wrong merchant or reference")
    # Replays still require the same authoritative provider proof; never extend twice.
    seats=conn.execute("""SELECT count(*) FROM myr_native.company_members
      WHERE company_id=%s AND status IN ('active','invited')""",(cid,)).fetchone()[0]
    paid_period(dict(mode="live",provider_id=pid,plan=plan,amount_sen=amount,period_start=start,period_end=end,
                     anchor_day=anchor,seats_fit=state=="paid" or seats<={"Starter":1,"Pro":3,"Business":10}[plan]),
                verified,live_enabled=True)
    if state=="paid":
        require(conn.execute("""SELECT 1 FROM myr_native.chip_live_receipts
          WHERE intent_id=%s AND provider_id=%s AND amount_sen=%s AND currency=%s""",(iid,pid,amount,currency)).fetchone(),"Receipt invariant broken")
        return {"status":"already_activated","provider_id":str(pid)}
    prior=conn.execute("""SELECT plan,period_end,anchor_day FROM myr_native.chip_subscriptions
      WHERE company_id=%s FOR UPDATE""",(cid,)).fetchone()
    require(start<=today<end,"Payment period requires review")
    if prior:
        require(prior[1]<=start,"Overlapping paid period")
        if prior[1]==start and prior[0]==plan:require(prior[2]==anchor,"Renewal anchor changed")
    else:
        require(start==today,"Initial activation must start today")
    version,data,_,_=row
    updated={**data,"plan":plan}
    if plan!="Business":updated["approvalRequired"]=False
    conn.execute("INSERT INTO myr_native.chip_live_receipts(intent_id,provider_id,amount_sen,currency) VALUES(%s,%s,%s,%s)",(iid,pid,amount,currency))
    conn.execute("UPDATE myr_native.chip_live_intents SET state='paid' WHERE id=%s",(iid,))
    conn.execute("""INSERT INTO myr_native.chip_subscriptions(company_id,plan,period_start,period_end,anchor_day,latest_intent)
      VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(company_id) DO UPDATE SET plan=excluded.plan,
      period_start=excluded.period_start,period_end=excluded.period_end,anchor_day=excluded.anchor_day,
      latest_intent=excluded.latest_intent,updated_at=now()""",(cid,plan,start,end,anchor,iid))
    conn.execute("INSERT INTO myr_native.company_revisions(company_id,version,data) VALUES(%s,%s,%s) ON CONFLICT(company_id,version) DO NOTHING",(cid,version,Jsonb(data)))
    conn.execute("UPDATE myr_native.companies SET plan=%s,data=%s,version=%s,updated_at=now() WHERE id=%s",(plan,Jsonb(updated),version+1,cid))
    email=conn.execute("SELECT email FROM myr_native.users WHERE id=%s",(actor,)).fetchone()[0]
    conn.execute("""INSERT INTO myr_native.audit_logs(company_id,actor,actor_email,action,detail)
      VALUES(%s,%s,%s,'billing.verified_activation',%s)""",(cid,actor,email,"plan="+plan+"; provider="+str(pid)))
    return {"status":"activated","plan":plan,"period_end":end.isoformat(),"provider_id":str(pid)}
