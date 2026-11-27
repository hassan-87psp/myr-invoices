"""Atomic subscription activation rehearsal against the disposable test cluster."""
from pathlib import Path
from uuid import uuid4
from datetime import date
from check_lhdn_disposable_db import connect,reject
from chip_live_activation_candidate import activate

def exercise(actor):
    with connect() as c:
        # connect() asserts this is the temporary cluster, never production.
        c.execute("""ALTER TABLE myr_native.companies ADD COLUMN version bigint NOT NULL DEFAULT 1,
          ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
          CREATE TABLE myr_native.company_revisions(company_id uuid,version bigint,data jsonb,PRIMARY KEY(company_id,version));
          CREATE TABLE myr_native.audit_logs(company_id uuid,actor uuid,actor_email text,action text,detail text);""")
        c.execute((Path(__file__).resolve().parent.parent/"chip-live-subscription.review.sql").read_text())
        cid,brand=uuid4(),uuid4()
        c.execute("INSERT INTO myr_native.companies(id,plan,status) VALUES(%s,'Starter','active')",(cid,))
        c.commit()
        def intent(start,end,anchor=31):
            iid,pid=uuid4(),uuid4()
            c.execute("""INSERT INTO myr_native.chip_live_intents(id,company_id,provider_id,brand_id,plan,amount_sen,period_start,period_end,anchor_day)
              VALUES(%s,%s,%s,%s,'Pro',1900,%s,%s,%s)""",(iid,cid,pid,brand,start,end,anchor))
            c.commit()
            proof={"is_test":False,"provider_id":pid,"brand_id":brand,"reference":"myr-live-"+str(iid),
                   "status":"paid","marked_as_paid":False,"is_outgoing":False,"amount_sen":1900,"currency":"MYR"}
            return iid,proof
        start=date(2026,1,31);end=date(2026,2,28)
        iid,proof=intent(start,end)
        reject(c,lambda:activate(c,actor,iid,proof,start))
        reject(c,lambda:activate(c,actor,iid,{**proof,"is_test":True},start,live_enabled=True))
        reject(c,lambda:activate(c,actor,iid,{**proof,"brand_id":uuid4()},start,live_enabled=True))
        reject(c,lambda:activate(c,actor,iid,{**proof,"amount_sen":1899},start,live_enabled=True))
        assert c.execute("SELECT count(*) FROM myr_native.chip_live_receipts").fetchone()==(0,)
        assert activate(c,actor,iid,proof,start,live_enabled=True)["status"]=="activated"
        c.commit()
        assert activate(c,actor,iid,proof,start,live_enabled=True)["status"]=="already_activated"
        assert c.execute("SELECT plan,version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()==("Pro",2)
        assert c.execute("SELECT count(*) FROM myr_native.chip_live_receipts").fetchone()==(1,)
        assert c.execute("SELECT count(*) FROM myr_native.audit_logs").fetchone()==(1,)
        c.commit()
        overlap,overlap_proof=intent(date(2026,2,1),date(2026,3,1),1)
        reject(c,lambda:activate(c,actor,overlap,overlap_proof,date(2026,2,1),live_enabled=True))
        renew,rproof=intent(end,date(2026,3,31))
        assert activate(c,actor,renew,rproof,end,live_enabled=True)["status"]=="activated"
        c.commit()
        assert c.execute("SELECT plan,period_end FROM myr_native.chip_subscriptions WHERE company_id=%s",(cid,)).fetchone()==("Pro",date(2026,3,31))
        assert c.execute("SELECT count(*) FROM myr_native.chip_live_receipts").fetchone()==(2,)
        assert c.execute("SELECT version FROM myr_native.companies WHERE id=%s",(cid,)).fetchone()==(3,)
        c.rollback()
    print("MYR_CHIP_LIVE_ACTIVATION_DISPOSABLE_OK")
