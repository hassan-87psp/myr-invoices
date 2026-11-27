"""Private sandbox checkout orchestration, not mounted in production.
Only the verified platform admin may reserve or reconcile test transactions.
Never retry a provider POST after a dispatch claim, even if the response is lost.
The real subscription, invoices and revenue are deliberately untouched.
"""
from uuid import UUID
from billing_ledger_candidate import CATALOG,admin,require
from chip_test_lifecycle_candidate import reserve,claim,unknown,accept_creation,record_verified_test_paid

def create_checkout(conn,actor,company,plan,bridge):
    iid=reserve(conn,actor,company,plan)
    conn.commit()
    row=claim(conn,actor,iid)
    conn.commit()
    request={"action":"create_reserved_test","intent_id":str(iid),"plan":row["plan"],
             "confirm":"I_VERIFIED_CHIP_TEST_KEY"}
    try:
        result=bridge(request)
        require(result.get("ok") is True and result.get("is_test") is True and
                result.get("intent_id")==str(iid) and result.get("amount_sen")==row["amount_sen"] and
                result.get("entitlement_changed") is False and result.get("status")=="created","Unverified creation")
        provider=str(UUID(result["purchase_id"]))
        expected="https://gate.chip-in.asia/p/"+provider+"/"
        require(result.get("checkout_url")==expected,"Unexpected checkout URL")
        accept_creation(conn,actor,iid,{"status":"created","provider_id":provider,"entitlement_changed":False})
        conn.commit()
        return {"intent_id":str(iid),"status":"created","checkout_url":expected,"mode":"test","entitlement_changed":False}
    except Exception:
        conn.rollback()
        # An unknown commit or outbound outcome must never cause another purchase POST.
        try:
            unknown(conn,actor,iid)
            conn.commit()
        except Exception:
            conn.rollback()
        return {"intent_id":str(iid),"status":"reconciliation_required","mode":"test","entitlement_changed":False}

def reconcile_checkout(conn,actor,iid,bridge):
    admin(conn,actor)
    row=conn.execute("""SELECT plan,amount_sen,provider_id,state FROM myr_native.chip_test_intents
      WHERE id=%s""",(iid,)).fetchone()
    require(row and row[2] is not None and row[3] in ("created","verified_test_paid"),"Known test purchase required")
    plan,amount,provider,state=row
    conn.commit()
    result=bridge({"action":"verify_reserved_test","intent_id":str(iid),"plan":plan,"purchase_id":str(provider)})
    require(result.get("ok") is True and result.get("is_test") is True and
            result.get("intent_id")==str(iid) and result.get("purchase_id")==str(provider) and
            result.get("amount_sen")==amount and result.get("entitlement_changed") is False,"Unverified purchase")
    if result.get("verified_test_paid") is True and result.get("status")=="paid":
        record_verified_test_paid(conn,actor,iid,{"status":"verified_test_paid","provider_id":str(provider),"entitlement_changed":False})
        conn.commit()
        return {"status":"verified_test_paid","mode":"test","entitlement_changed":False}
    return {"status":"not_verified_paid","mode":"test","entitlement_changed":False}
