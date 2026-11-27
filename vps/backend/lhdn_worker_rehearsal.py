"""Controlled worker orchestration, no network adapter and no scheduled process.
Only an explicitly injected synthetic transport is accepted. Never import in live API.
The connection factory must target a disposable database; actual credentials are not used.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from lhdn_lifecycle_candidate import reserve, accept, outcome_unknown, row, scoped, sync, poll_plan
from lhdn_protocol_candidate import require
import unittest
from unittest.mock import patch,MagicMock

@dataclass(frozen=True)
class MockResponse:
    status:int
    body:dict

class SyntheticTransport:
    def __init__(self,responses):
        self.responses=list(responses)
        self.calls=[]
    def request(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        require(bool(self.responses),"No synthetic response configured")
        r=self.responses.pop(0)
        if isinstance(r,Exception):raise r
        require(type(r) is MockResponse,"Synthetic response required")
        return r

def dispatch_once(connect,transport,company_id,invoice_id,version,now):
    require(type(transport) is SyntheticTransport,"Real transport disabled")
    key=scoped(company_id,invoice_id,"sandbox")
    # Transaction commits before simulated dispatch. A reservation failure
    # is not caught as an external failure and makes zero transport calls.
    with connect() as conn:
        payload=reserve(conn,*key,version,now)
        conn.commit()
    try:
        response=transport.request("POST","/api/v1.0/documentsubmissions",payload)
        with connect() as conn:
            receipt=accept(conn,*key,response.status,response.body,now)
            conn.commit()
        return {"state":"accepted","uuid":receipt.uuid}
    except Exception:
        # If this write itself fails, the durable dispatching reservation still
        # prevents retries. A separate reconciliation job must investigate it.
        with connect() as conn:
            outcome_unknown(conn,*key,now)
            conn.commit()
        return {"state":"outcome_unknown","retry_enabled":False}

def poll_once(connect,transport,company_id,invoice_id,now,retry_header=None):
    require(type(transport) is SyntheticTransport,"Real transport disabled")
    key=scoped(company_id,invoice_id,"sandbox")
    with connect() as conn:
        x=row(conn,key,False)
        path=poll_plan(x,now,retry_header)
    response=transport.request("GET",path)
    require(response.status==200,"Polling unsuccessful; no state changed")
    with connect() as conn:
        result=sync(conn,*key,response.body,now)
        conn.commit()
    return result

class WorkerTests(unittest.TestCase):
    def setUp(self):
        from uuid import UUID
        self.cid=UUID(int=1);self.now=datetime(2026,11,27,3,tzinfo=timezone.utc)
        self.conn=MagicMock()
        self.conn.__enter__.return_value=self.conn
        self.connect=MagicMock(return_value=self.conn)
        self.body={"documents":[{"codeNumber":"INV1"}]}
    def dispatch(self,transport):
        return dispatch_once(self.connect,transport,self.cid,"INV1",1,self.now)
    def test_committed_before_transport(self):
        from lhdn_protocol_candidate import Receipt
        tr=SyntheticTransport([MockResponse(202,{})])
        original=tr.request
        def checked(*args):
            self.conn.commit.assert_called_once()
            return original(*args)
        with patch.object(tr,"request",side_effect=checked),patch(__name__+".reserve",return_value=self.body),patch(__name__+".accept",return_value=Receipt("SUB1","UUID1","INV1")):
            result=self.dispatch(tr)
        self.assertEqual(result,{"state":"accepted","uuid":"UUID1"})
        self.assertEqual(len(tr.calls),1)
        self.assertEqual(self.conn.commit.call_count,2)
    def test_timeout_no_retry(self):
        tr=SyntheticTransport([TimeoutError("synthetic timeout")])
        with patch(__name__+".reserve",return_value=self.body),patch(__name__+".outcome_unknown") as unknown:
            result=self.dispatch(tr)
        self.assertEqual(result,{"state":"outcome_unknown","retry_enabled":False})
        self.assertEqual(len(tr.calls),1)
        unknown.assert_called_once()
    def test_duplicate_no_dispatch(self):
        tr=SyntheticTransport([])
        with patch(__name__+".reserve",side_effect=ValueError("Already reserved")):
            with self.assertRaises(ValueError):self.dispatch(tr)
        self.assertEqual(tr.calls,[])
    def test_ambiguous_receipt(self):
        tr=SyntheticTransport([MockResponse(202,{"ambiguous":True})])
        with patch(__name__+".reserve",return_value=self.body),patch(__name__+".accept",side_effect=ValueError("Bad receipt")),patch(__name__+".outcome_unknown"):
            self.assertEqual(self.dispatch(tr)["state"],"outcome_unknown")
    def test_real_transport_disabled(self):
        with self.assertRaises(ValueError):self.dispatch(object())
    def test_poll_failure(self):
        tr=SyntheticTransport([MockResponse(429,{})])
        with patch(__name__+".row",return_value={}),patch(__name__+".poll_plan",return_value="/synthetic"),patch(__name__+".sync") as save:
            with self.assertRaises(ValueError):poll_once(self.connect,tr,self.cid,"INV1",self.now)
        save.assert_not_called()

if __name__=="__main__":
    unittest.main()
