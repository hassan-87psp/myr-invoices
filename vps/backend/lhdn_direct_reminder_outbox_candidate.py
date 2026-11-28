"""Private reminder outbox state machine, SQLite rehearsal only.
No mail provider or database used automatically. Caller must verify active
owner, verified recipient and current expiry again immediately before send.
Unknown delivery is terminal until operator reconciliation; no blind retry.
"""
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA="""CREATE TABLE IF NOT EXISTS expiry_outbox (
 event_key TEXT PRIMARY KEY,
 state TEXT NOT NULL CHECK(state IN ('queued','sending','sent','unknown','cancelled')),
 updated TEXT NOT NULL
)"""
class Outbox:
    def __init__(self,db):
        self.db=db
        db.execute(SCHEMA)
        db.commit()
    def stamp(self):
        return datetime.now(timezone.utc).isoformat()
    def enqueue(self,key):
        if len(key)!=64 or any(c not in "0123456789abcdef" for c in key):raise ValueError("Invalid event key")
        with self.db:
            return self.db.execute("INSERT OR IGNORE INTO expiry_outbox VALUES (?, 'queued', ?)",(key,self.stamp())).rowcount==1
    def transition(self,key,old,new):
        with self.db:
            return self.db.execute("UPDATE expiry_outbox SET state=?,updated=? WHERE event_key=? AND state=?",(new,self.stamp(),key,old)).rowcount==1
    def dispatch(self,event,resolve,send):
        # resolve returns current verified owner recipient, or None if revoked,
        # stale or disabled. Both callbacks are trusted server-side adapters.
        key=event["event_key"]
        if not self.transition(key,"queued","sending"):return "not_claimed"
        try:
            recipient=resolve(event)
            if not recipient:
                self.transition(key,"sending","cancelled")
                return "cancelled"
            if send(recipient,event["subject"],event["body"],key) is not True:
                raise ValueError("Unconfirmed delivery")
        except Exception:
            self.transition(key,"sending","unknown")
            return "unknown"
        if not self.transition(key,"sending","sent"):
            return "unknown"
        return "sent"
    def state(self,key):
        row=self.db.execute("SELECT state FROM expiry_outbox WHERE event_key=?",(key,)).fetchone()
        return row[0] if row else None

class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.o=Outbox(self.db)
        self.e={"event_key":"a"*64,"subject":"Expiry","body":"Renew"}
        self.k=self.e["event_key"]
        self.o.enqueue(self.k)
    def test_dedup(self):
        sent=[]
        def sender(*args):sent.append(args);return True
        self.assertFalse(self.o.enqueue(self.k))
        self.assertEqual(self.o.dispatch(self.e,lambda e:"owner@example.invalid",sender),"sent")
        self.assertEqual(self.o.dispatch(self.e,lambda e:"owner@example.invalid",sender),"not_claimed")
        self.assertEqual(len(sent),1)
    def test_revoked(self):
        self.assertEqual(self.o.dispatch(self.e,lambda e:None,lambda *a:self.fail("No send")),"cancelled")
    def test_ambiguous(self):
        self.assertEqual(self.o.dispatch(self.e,lambda e:"owner@example.invalid",lambda *a:False),"unknown")
        self.assertEqual(self.o.dispatch(self.e,lambda e:self.fail("No retry"),lambda *a:False),"not_claimed")
    def test_interrupted(self):
        self.assertTrue(self.o.transition(self.k,"queued","sending"))
        self.assertEqual(self.o.dispatch(self.e,lambda e:self.fail("No retry"),lambda *a:False),"not_claimed")

if __name__=="__main__":unittest.main()
