"""Review-only verified revenue report. No provider calls or mutations.
Invoke only behind platform-admin authentication in a read-only transaction.
Do not mix manual receipts, plan list prices or sandbox receipts with CHIP revenue.
Gross receipts are not net revenue; refunds/fees need a separate reconciled ledger.
"""
from datetime import date,datetime,time,timedelta
from zoneinfo import ZoneInfo
from billing_ledger_candidate import require

def report(conn,actor,start,end):
    require(type(start) is date and type(end) is date and 0<(end-start).days<=366,"Invalid report range")
    require(conn.execute("""SELECT 1 FROM myr_native.users
      WHERE id=%s AND is_platform_admin AND NOT disabled AND email_verified_at IS NOT NULL""",(actor,)).fetchone(),"Admin required")
    tz=ZoneInfo("Asia/Kuala_Lumpur")
    lower=datetime.combine(start,time.min,tzinfo=tz)
    upper=datetime.combine(end,time.min,tzinfo=tz)
    rows=conn.execute("""SELECT i.plan,count(*)::bigint,coalesce(sum(r.amount_sen),0)::bigint
      FROM myr_native.chip_live_receipts r
      JOIN myr_native.chip_live_intents i ON i.id=r.intent_id
        AND i.provider_id=r.provider_id AND i.amount_sen=r.amount_sen AND i.currency=r.currency
      WHERE i.state='paid' AND r.currency='MYR' AND r.recorded_at >= %s AND r.recorded_at < %s
      GROUP BY i.plan ORDER BY i.plan""",(lower,upper)).fetchall()
    return {"currency":"MYR","period_start":start.isoformat(),"period_end_exclusive":end.isoformat(),
            "gross_recorded_receipts_sen":sum(r[2] for r in rows),
            "verified_receipt_count":sum(r[1] for r in rows),
            "by_plan":[{"plan":r[0],"receipt_count":r[1],"gross_receipts_sen":r[2]} for r in rows],
            "net_revenue_sen":None,"includes_refunds_or_fees":False,"timestamp_basis":"receipt_recorded_at"}

if __name__=="__main__":
    from uuid import uuid4
    class Result:
        def __init__(self,rows):self.rows=rows
        def fetchone(self):return self.rows[0] if self.rows else None
        def fetchall(self):return self.rows
    class Conn:
        def __init__(self,admin=True):self.admin=admin;self.calls=[]
        def execute(self,sql,args):
            self.calls.append((sql,args))
            if "myr_native.users" in sql:return Result([(1,)] if self.admin else [])
            assert "chip_live_receipts" in sql and "chip_test" not in sql and "i.state='paid'" in sql
            return Result([("Starter",2,1800),("Pro",1,1900)])
    start=date(2026,11,1);end=date(2026,12,1)
    c=Conn();r=report(c,uuid4(),start,end)
    assert r["gross_recorded_receipts_sen"]==3700 and r["verified_receipt_count"]==3
    assert r["net_revenue_sen"] is None
    assert c.calls[1][1][0].utcoffset()==timedelta(hours=8)
    c=Conn(False)
    try:report(c,uuid4(),start,end)
    except ValueError:pass
    else:raise AssertionError("Non-admin report allowed")
    assert len(c.calls)==1
    for a,b in ((start,start),(end,start),(start,start+timedelta(days=367))):
        try:report(Conn(),uuid4(),a,b)
        except ValueError:pass
        else:raise AssertionError("Invalid date range allowed")
    print("MYR_CHIP_REVENUE_REPORT_OFFLINE_OK")
