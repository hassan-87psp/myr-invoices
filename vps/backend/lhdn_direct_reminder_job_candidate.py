"""Sandbox reminder job candidate. No startup hook, automatic mail or live DB.

The future scheduler must supply a separately authorized opt-in subscription,
current active owner/verified email and fresh redacted vault status. A temporary
ERP pilot grant is not persistent consent for email. The job refuses unapproved
subscriptions and re-resolves the recipient and expiry after claiming the event.
"""
import datetime as dt
import re
import sqlite3
import unittest
from lhdn_direct_expiry_reminder_candidate import plan
from lhdn_direct_reminder_outbox_candidate import Outbox

LABELS={"30_days":"30-day window","7_days":"7-day window","1_day":"1-day window","expired":"Expired"}

def payload(event,recipient):
    if not isinstance(recipient,str) or len(recipient)>254 or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+",recipient):
        raise ValueError("Verified recipient required")
    expiry=dt.date.fromisoformat(event["expiry"])
    if expiry.isoformat()!=event["expiry"] or event["environment"]!="sandbox":
        raise ValueError("Invalid Sandbox event")
    return {"event":"direct_erp_expiry","recipient":recipient,"details":{"expiry_date":expiry.isoformat(),"reminder_stage":LABELS[event["stage"]]}}

def run(tenant,outbox,resolve,deliver,clock,enabled=False):
    """resolve(tenant) is a trusted server adapter, never browser input.
    Returns (verified_owner_email, redacted_status) only for active, opted-in,
    authorized subscriptions; None otherwise. deliver returns True only after
    gateway acceptance. Never calls either adapter unless explicitly enabled.
    """
    if enabled is not True:return "disabled"
    initial=resolve(tenant)
    if initial is None:return "not_eligible"
    event=plan(tenant,initial[1],clock())
    if event is None:return "not_due"
    if not outbox.enqueue(event["event_key"]):
        # A previously committed queued event can be claimed; sent, unknown
        # and interrupted sending states cannot automatically be retried.
        if outbox.state(event["event_key"])!="queued":return "already_processed"
    def recheck(e):
        current=resolve(tenant)
        if current is None or current[0]!=initial[0]:return None
        fresh=plan(tenant,current[1],clock())
        if fresh is None or fresh["event_key"]!=e["event_key"]:return None
        return current[0]
    return outbox.dispatch(event,recheck,lambda recipient,subject,body,key:deliver(payload(event,recipient),key))

class Tests(unittest.TestCase):
    tenant="00000000-0000-4000-8000-000000000001"
    date=dt.datetime(2027,1,30,4,tzinfo=dt.timezone.utc)
    status={"environment":"sandbox","mode":"direct_erp","status":"pending_identity_review","expiry":"2027-01-31"}
    def setUp(self):
        db=sqlite3.connect(":memory:");self.addCleanup(db.close);self.outbox=Outbox(db)
        self.sent=[]
    def resolver(self,t):return ("owner@example.invalid",self.status)
    def deliver(self,data,key):self.sent.append(data);return True
    def job(self,resolve=None,enabled=True,deliver=None):
        return run(self.tenant,self.outbox,resolve or self.resolver,deliver or self.deliver,lambda:self.date,enabled)
    def test_disabled(self):
        self.assertEqual(self.job(lambda t:self.fail("No DB read"),False),"disabled")
    def test_send_once(self):
        self.assertEqual(self.job(),"sent")
        self.assertEqual(self.job(),"already_processed")
        self.assertEqual(self.sent,[{"event":"direct_erp_expiry","recipient":"owner@example.invalid","details":{"expiry_date":"2027-01-31","reminder_stage":"1-day window"}}])
    def test_revoked(self):
        states=iter([self.resolver(None),None])
        self.assertEqual(self.job(lambda t:next(states)),"cancelled")
        self.assertEqual(self.sent,[])
    def test_changed_expiry(self):
        states=iter([self.resolver(None),("owner@example.invalid",{**self.status,"expiry":"2027-03-31"})])
        self.assertEqual(self.job(lambda t:next(states)),"cancelled")
    def test_uncertain(self):
        self.assertEqual(self.job(deliver=lambda *a:False),"unknown")
        self.assertEqual(self.job(),"already_processed")
    def test_no_subscription(self):
        self.assertEqual(self.job(lambda t:None),"not_eligible")
if __name__=="__main__":unittest.main()
