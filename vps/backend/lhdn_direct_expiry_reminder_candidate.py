"""Offline expiry reminder planner. No email, credential access, DB or network.

Caller must obtain current owner authorization, redacted vault status and
verified email server-side, then atomically reserve the unique event key in
a durable outbox. Recheck expiry and ownership before sending. Never retry
an ambiguous send blindly. This module is not an active scheduler.
"""
import datetime as dt
import hashlib
import unittest
from uuid import UUID

MALAYSIA=dt.timezone(dt.timedelta(hours=8))
STAGES=((0,"expired"),(1,"1_day"),(7,"7_days"),(30,"30_days"))

def plan(tenant,status,now):
    if str(UUID(tenant))!=tenant or now.tzinfo is None:
        raise ValueError("Invalid tenant or clock")
    if status.get("environment")!="sandbox" or status.get("mode")!="direct_erp":
        raise ValueError("Sandbox direct ERP only")
    if status.get("status") not in ("pending_identity_review","expired"):
        return None
    expiry=dt.date.fromisoformat(status["expiry"])
    if expiry.isoformat()!=status["expiry"]:
        raise ValueError("Invalid expiry")
    remaining=(expiry-now.astimezone(MALAYSIA).date()).days
    stage=next((name for threshold,name in STAGES if remaining<=threshold),None)
    if not stage:return None
    # Independent of probe revisions and repeated daily runs.
    key=hashlib.sha256(("myr-direct-expiry-v1|sandbox|"+tenant+"|"+expiry.isoformat()+"|"+stage).encode()).hexdigest()
    subject="MYR Invoice: Direct Connect credential expiry"
    if stage=="expired":
        body="Your recorded Direct Connect credential expiry date has passed."
    else:
        body=f"Your recorded Direct Connect credential expiry date is in {remaining} day(s)."
    body+=f" Recorded expiry: {expiry.isoformat()} (Malaysia date). Sign in to MYR Invoice and review Integrations. Never send ERP credentials by email. This reminder is based on the date entered by your company, not independently confirmed by LHDN."
    return {"event_key":key,"stage":stage,"expiry":expiry.isoformat(),"subject":subject,"body":body,"environment":"sandbox"}

class Tests(unittest.TestCase):
    tenant="00000000-0000-4000-8000-000000000001"
    status={"environment":"sandbox","mode":"direct_erp","status":"pending_identity_review","expiry":"2027-01-31"}
    def at(self,days):
        return dt.datetime(2027,1,31,0,tzinfo=MALAYSIA)-dt.timedelta(days=days)
    def test_thresholds(self):
        for days,expected in [(31,None),(30,"30_days"),(8,"30_days"),(7,"7_days"),(2,"7_days"),(1,"1_day"),(0,"expired"),(-2,"expired")]:
            result=plan(self.tenant,self.status,self.at(days))
            self.assertEqual(result["stage"] if result else None,expected)
    def test_dedup(self):
        first=plan(self.tenant,self.status,self.at(30))
        second=plan(self.tenant,{**self.status,"revision":99},self.at(29))
        self.assertEqual(first["event_key"],second["event_key"])
        self.assertNotEqual(first["event_key"],plan(self.tenant,self.status,self.at(7))["event_key"])
        self.assertNotEqual(first["event_key"],plan(self.tenant,{**self.status,"expiry":"2027-01-30"},self.at(30))["event_key"])
    def test_scope_and_redaction(self):
        for state in ("disconnected","not_configured","connected"):
            self.assertIsNone(plan(self.tenant,{**self.status,"status":state},self.at(1)))
        with self.assertRaises(ValueError):plan(self.tenant,{**self.status,"environment":"production"},self.at(1))
        result=plan(self.tenant,{**self.status,"client_secret":"synthetic-secret"},self.at(1))
        self.assertNotIn("synthetic-secret",str(result))
    def test_midnight(self):
        before=dt.datetime(2027,1,30,15,59,tzinfo=dt.timezone.utc)
        self.assertEqual(plan(self.tenant,self.status,before)["stage"],"1_day")
        self.assertEqual(plan(self.tenant,self.status,before+dt.timedelta(minutes=1))["stage"],"expired")

if __name__=="__main__":unittest.main()
