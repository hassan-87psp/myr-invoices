"""Review-only subscription policy: no provider calls or database mutations.
Billing periods use Malaysian calendar dates, end-exclusive; preserve original
billing-day anchor when a shorter month clips the renewal date.
"""
from calendar import monthrange
from datetime import date
from uuid import UUID
from billing_ledger_candidate import CATALOG

def renewal_date(start,anchor):
    if type(start) is not date or type(anchor) is not int or not 1<=anchor<=31:
        raise ValueError("Invalid billing date")
    year,month=(start.year+1,1) if start.month==12 else (start.year,start.month+1)
    return date(year,month,min(anchor,monthrange(year,month)[1]))

def next_charge(sub,today,*,gateway_approved=False,live_enabled=False):
    """Return a decision only; no charge. Do not catch up multiple missed months."""
    if type(today) is not date:raise ValueError("Invalid date")
    if not live_enabled or not gateway_approved:return {"action":"disabled"}
    if sub["state"]!="active" or sub.get("cancel_at_period_end") is True:return {"action":"no_charge"}
    if sub.get("consent") is not True or sub.get("token_verified") is not True:return {"action":"manual_renewal"}
    plan=sub["plan"]; amount=CATALOG.get(plan)
    if amount is None or sub.get("consented_amount_sen")!=amount or sub.get("consented_currency")!="MYR":
        return {"action":"new_consent_required"}
    if type(sub["period_end"]) is not date or today<sub["period_end"]:return {"action":"not_due"}
    if today>sub["period_end"]:return {"action":"manual_review_overdue"}
    if sub.get("open_payment") is True:return {"action":"reconcile_existing"}
    return {"action":"reserve_renewal","amount_sen":amount,"currency":"MYR",
            "period_start":today,"period_end":renewal_date(today,sub["anchor_day"])}

def paid_period(intent,verified,*,live_enabled=False):
    """Only trusted server verification may enter this decision function."""
    if not live_enabled:raise ValueError("Live activation disabled")
    if intent.get("mode")!="live" or verified.get("is_test") is not False:raise ValueError("Test payment rejected")
    if intent.get("provider_id")!=verified.get("provider_id") or not isinstance(intent.get("provider_id"),UUID):
        raise ValueError("Purchase identity mismatch")
    if verified.get("status")!="paid" or verified.get("marked_as_paid") is not False or verified.get("is_outgoing") is not False:
        raise ValueError("Unverified incoming payment")
    amount=CATALOG.get(intent.get("plan"))
    if amount is None or intent.get("amount_sen")!=amount or verified.get("amount_sen")!=amount or verified.get("currency")!="MYR":
        raise ValueError("Plan or amount mismatch")
    start=intent["period_start"]; end=intent["period_end"]
    if end!=renewal_date(start,intent["anchor_day"]):raise ValueError("Period mismatch")
    if intent.get("seats_fit") is not True:raise ValueError("Seat limit exceeded")
    # Future caller must perform unique receipt and entitlement update in one DB transaction.
    return {"plan":intent["plan"],"period_start":start,"period_end":end,"provider_id":intent["provider_id"]}

if __name__=="__main__":
    from uuid import uuid4
    a=date(2026,1,31);b=renewal_date(a,31)
    assert b==date(2026,2,28) and renewal_date(b,31)==date(2026,3,31)
    assert renewal_date(date(2028,1,31),31)==date(2028,2,29)
    assert renewal_date(date(2026,12,31),31)==date(2027,1,31)
    sub=dict(state="active",plan="Pro",consent=True,token_verified=True,consented_amount_sen=1900,
             consented_currency="MYR",period_end=b,anchor_day=31)
    def decide(**changes):return next_charge({**sub,**changes},b,gateway_approved=True,live_enabled=True)["action"]
    assert next_charge(sub,b)["action"]=="disabled"
    assert decide()=="reserve_renewal"
    assert decide(cancel_at_period_end=True)=="no_charge"
    assert decide(consent=False)=="manual_renewal"
    assert decide(token_verified=False)=="manual_renewal"
    assert decide(consented_amount_sen=900)=="new_consent_required"
    assert decide(open_payment=True)=="reconcile_existing"
    assert next_charge(sub,a,gateway_approved=True,live_enabled=True)["action"]=="not_due"
    assert next_charge(sub,date(2026,3,1),gateway_approved=True,live_enabled=True)["action"]=="manual_review_overdue"
    pid=uuid4()
    i=dict(mode="live",plan="Pro",amount_sen=1900,provider_id=pid,period_start=b,
           period_end=date(2026,3,31),anchor_day=31,seats_fit=True)
    v=dict(is_test=False,provider_id=pid,status="paid",marked_as_paid=False,is_outgoing=False,amount_sen=1900,currency="MYR")
    assert paid_period(i,v,live_enabled=True)["plan"]=="Pro"
    for bad in (dict(is_test=True),dict(is_test=None),dict(status="pending_charge"),dict(marked_as_paid=True),
                dict(is_outgoing=True),dict(amount_sen=1899),dict(currency="USD"),dict(provider_id=uuid4())):
        try:paid_period(i,{**v,**bad},live_enabled=True)
        except ValueError:pass
        else:raise AssertionError("Unsafe activation accepted")
    try:paid_period(i,v)
    except ValueError:pass
    else:raise AssertionError("Live gate bypass")
    print("MYR_SUBSCRIPTION_POLICY_OFFLINE_OK")
