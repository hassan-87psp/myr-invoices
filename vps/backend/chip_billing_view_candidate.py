"""Private billing UI view-model candidate. No browser-side secret, no payment mutation."""
from billing_ledger_candidate import CATALOG

def owner_view(history, current_plan, document_count, seats):
    if current_plan not in CATALOG or type(document_count) is not int or document_count<0 or type(seats) is not int or seats<0:
        raise ValueError("Invalid billing state")
    limits={"Starter":(100,1),"Pro":(1000,3),"Business":(3000,10)}
    plans=[]
    for plan,amount in CATALOG.items():
        docs,users=limits[plan]
        plans.append({"plan":plan,"amount_sen":amount,"currency":"MYR","period":"month",
                      "documents":docs,"seats":users,"current":plan==current_plan,
                      "eligible_for_change":seats<=users,"checkout_enabled":False})
    return {"plans":plans,"current_plan":current_plan,"documents_used":document_count,
            "seats_used":seats,"payment_history":list(history),"gateway":"CHIP",
            "checkout_enabled":False,"auto_renewal_enabled":False}

def admin_view(test_history):
    # Never present sandbox receipts as revenue or live paid subscriptions.
    rows=list(test_history)
    return {"mode":"test","live_revenue_sen":None,"live_payments_enabled":False,
            "test_paid_count":sum(x["state"]=="verified_test_paid" for x in rows),
            "open_test_count":sum(x["state"] in ("reserved","dispatching","created","outcome_unknown") for x in rows),
            "needs_reconciliation":sum(x["state"]=="outcome_unknown" for x in rows),
            "test_history":rows}

if __name__=="__main__":
    a=owner_view([],"Starter",0,2)
    assert a["plans"][0]["eligible_for_change"] is False
    assert a["plans"][1]["eligible_for_change"] is True
    assert all(not x["checkout_enabled"] for x in a["plans"])
    assert [x["amount_sen"] for x in a["plans"]]==[900,1900,3900]
    b=admin_view([{"state":"verified_test_paid"},{"state":"outcome_unknown"}])
    assert b["live_revenue_sen"] is None and b["test_paid_count"]==1 and b["needs_reconciliation"]==1
    print("MYR_CHIP_BILLING_VIEW_MODEL_OK")
