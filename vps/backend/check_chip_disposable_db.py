"""Offline disposable-cluster rehearsal for CHIP sandbox ledger."""
from pathlib import Path
from uuid import uuid4
from psycopg.errors import UniqueViolation
from check_lhdn_disposable_db import connect,reject
from chip_test_lifecycle_candidate import reserve,claim,unknown,accept_creation,record_verified_test_paid,admin_history

def main():
    with connect() as c:
        c.execute("""CREATE SCHEMA myr_native;
          CREATE TABLE myr_native.users(id uuid PRIMARY KEY,email text UNIQUE NOT NULL,
            disabled boolean DEFAULT false,email_verified_at timestamptz,is_platform_admin boolean DEFAULT false);
          CREATE TABLE myr_native.companies(id uuid PRIMARY KEY,plan text NOT NULL,status text NOT NULL,data jsonb NOT NULL DEFAULT '{}');""")
        c.execute((Path(__file__).resolve().parent.parent/"chip-test-ledger.review.sql").read_text())
        admin,other,company,second=uuid4(),uuid4(),uuid4(),uuid4()
        for uid,flag in ((admin,True),(other,False)):
            c.execute("INSERT INTO myr_native.users(id,email,email_verified_at,is_platform_admin) VALUES(%s,%s,now(),%s)",(uid,uid.hex+"@example.invalid",flag))
        for cid in (company,second):
            c.execute("INSERT INTO myr_native.companies(id,plan,status) VALUES(%s,'Starter','active')",(cid,))
        c.commit()
        reject(c,lambda:reserve(c,other,company,"Pro"))
        reject(c,lambda:reserve(c,admin,company,"invalid"))
        iid=reserve(c,admin,company,"Pro")
        c.commit()
        reject(c,lambda:reserve(c,admin,company,"Business"),UniqueViolation)
        assert claim(c,admin,iid)["amount_sen"]==1900
        c.commit()
        reject(c,lambda:claim(c,admin,iid))
        pid=uuid4()
        reject(c,lambda:accept_creation(c,admin,iid,{"status":"created","provider_id":str(pid),"entitlement_changed":True}))
        accept_creation(c,admin,iid,{"status":"created","provider_id":str(pid),"entitlement_changed":False})
        c.commit()
        result={"status":"verified_test_paid","provider_id":str(pid),"entitlement_changed":False}
        reject(c,lambda:record_verified_test_paid(c,other,iid,result))
        reject(c,lambda:record_verified_test_paid(c,admin,iid,{**result,"provider_id":str(uuid4())}))
        assert record_verified_test_paid(c,admin,iid,result)=="verified_test_paid"
        c.commit()
        assert record_verified_test_paid(c,admin,iid,result)=="already_verified"
        assert c.execute("SELECT count(*) FROM myr_native.chip_test_receipts").fetchone()==(1,)
        assert c.execute("SELECT plan FROM myr_native.companies WHERE id=%s",(company,)).fetchone()==("Starter",)
        iid2=reserve(c,admin,second,"Business")
        claim(c,admin,iid2)
        unknown(c,admin,iid2)
        c.commit()
        reject(c,lambda:claim(c,admin,iid2))
        reject(c,lambda:reserve(c,admin,second,"Starter"),UniqueViolation)
        reject(c,lambda:admin_history(c,other))
        assert len(admin_history(c,admin))==2
        c.rollback()
        from chip_checkout_orchestration_candidate import create_checkout,reconcile_checkout
        third,fourth=uuid4(),uuid4()
        for cid in (third,fourth):
            c.execute("INSERT INTO myr_native.companies(id,plan,status) VALUES(%s,'Starter','active')",(cid,))
        c.commit()
        calls=[]; provider=str(uuid4())
        def bridge(req):
            calls.append(req)
            amount={"Starter":900,"Pro":1900,"Business":3900}[req["plan"]]
            # The dispatch state must already be committed before the external call.
            with connect() as reader:
                state=reader.execute("SELECT state FROM myr_native.chip_test_intents WHERE id=%s",(req["intent_id"],)).fetchone()[0]
                assert state in ("dispatching","created","verified_test_paid")
            base={"ok":True,"is_test":True,"amount_sen":amount,"intent_id":req["intent_id"],
                  "purchase_id":provider,"entitlement_changed":False}
            if req["action"]=="create_reserved_test":
                return {**base,"status":"created","checkout_url":"https://gate.chip-in.asia/p/"+provider+"/"}
            return {**base,"status":"paid","verified_test_paid":True}
        result=create_checkout(c,admin,third,"Business",bridge)
        assert result["status"]=="created" and result["entitlement_changed"] is False
        iid=result["intent_id"]
        assert reconcile_checkout(c,admin,iid,bridge)["status"]=="verified_test_paid"
        assert reconcile_checkout(c,admin,iid,bridge)["status"]=="verified_test_paid"
        assert sum(x["action"]=="create_reserved_test" for x in calls)==1
        assert c.execute("SELECT count(*) FROM myr_native.chip_test_receipts WHERE intent_id=%s",(iid,)).fetchone()==(1,)
        assert c.execute("SELECT plan FROM myr_native.companies WHERE id=%s",(third,)).fetchone()==("Starter",)
        c.commit()
        def lost(req):raise TimeoutError("simulated network timeout")
        result=create_checkout(c,admin,fourth,"Pro",lost)
        assert result["status"]=="reconciliation_required"
        assert c.execute("SELECT state FROM myr_native.chip_test_intents WHERE id=%s",(result["intent_id"],)).fetchone()==("outcome_unknown",)
        reject(c,lambda:reserve(c,admin,fourth,"Starter"),UniqueViolation)
        c.rollback()
    # Fresh synthetic schema for route-level integration, in the same disposable cluster.
    with connect() as c:
        c.execute("DROP SCHEMA myr_native CASCADE")
        c.execute("""CREATE SCHEMA myr_native;
          CREATE TABLE myr_native.users(id uuid PRIMARY KEY,email text UNIQUE NOT NULL,name text,
             disabled boolean DEFAULT false,email_verified_at timestamptz,is_platform_admin boolean DEFAULT false);
          CREATE TABLE myr_native.companies(id uuid PRIMARY KEY,plan text NOT NULL,status text NOT NULL,data jsonb NOT NULL DEFAULT '{}');
          CREATE TABLE myr_native.company_members(company_id uuid REFERENCES myr_native.companies(id),
             email text REFERENCES myr_native.users(email),role text NOT NULL,status text NOT NULL,PRIMARY KEY(company_id,email));""")
        root=Path(__file__).resolve().parent.parent
        for sql in ("billing-ledger.review.sql","chip-test-ledger.review.sql"):
            c.execute((root/sql).read_text())
        admin,owner,other,company,second=(uuid4() for _ in range(5))
        for uid,flag in ((admin,True),(owner,False),(other,False)):
            c.execute("INSERT INTO myr_native.users(id,email,email_verified_at,is_platform_admin) VALUES(%s,%s,now(),%s)",(uid,uid.hex+"@example.invalid",flag))
        for cid,uid in ((company,owner),(second,other)):
            c.execute("INSERT INTO myr_native.companies(id,plan,status) VALUES(%s,'Starter','active')",(cid,))
            c.execute("INSERT INTO myr_native.company_members VALUES(%s,%s,'Owner','active')",(cid,uid.hex+"@example.invalid"))
        c.commit()
    from check_chip_billing_integration import exercise
    exercise(admin,owner,other,company,second)
    print("MYR_CHIP_TEST_LEDGER_DISPOSABLE_OK")
    print("MYR_CHIP_CHECKOUT_ORCHESTRATION_MOCK_OK")
if __name__=="__main__":main()
