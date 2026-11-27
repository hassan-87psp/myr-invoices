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
    print("MYR_CHIP_TEST_LEDGER_DISPOSABLE_OK")
if __name__=="__main__":main()
