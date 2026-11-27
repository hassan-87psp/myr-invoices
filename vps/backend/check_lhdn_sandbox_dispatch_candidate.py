"""Offline tests for the actual sandbox worker adapter. No real DB or HTTP."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256
from unittest import TestCase,main
from unittest.mock import MagicMock,patch
from uuid import UUID
import lhdn_sandbox_dispatch_candidate as w
from lhdn_protocol_candidate import Receipt

class Tests(TestCase):
    def setUp(self):
        self.cid=UUID(int=1);self.actor=UUID(int=2)
        raw=b'{"Invoice":[{"ID":[{"_":"INV-1"}]}]}'
        self.x={"tin":"C1234567890","hash":sha256(raw).hexdigest(),"bytes":raw,
                "code":"INV-1","state":"dispatching","version":1,"created_by":self.actor}
        self.g={"tenant_id":str(self.cid),"taxpayer":self.x["tin"],"document_hash":self.x["hash"],
                "code_number":"INV-1","expires_at":(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}
    def test_binding(self):
        with patch.object(w.central,"approved_target",return_value=self.x["tin"]):
            w.verify_grant(self.g,self.cid,self.x["tin"],"123456789012",self.x,datetime.now(timezone.utc))
            with self.assertRaises(ValueError):w.verify_grant(self.g,UUID(int=9),self.x["tin"],"123456789012",self.x,datetime.now(timezone.utc))
            with self.assertRaises(ValueError):w.verify_grant(self.g,self.cid,self.x["tin"],"123456789012",{**self.x,"bytes":b"changed"},datetime.now(timezone.utc))
    def test_expired_grant(self):
        with self.assertRaises(ValueError):
            w.verify_grant({**self.g,"expires_at":"2020-01-01T00:00:00Z"},self.cid,self.x["tin"],"123",self.x,datetime.now(timezone.utc))
    def test_wrong_database(self):
        c=MagicMock()
        c.execute.return_value.fetchone.return_value=("myrinvoice","myrinvoice_app","127.0.0.1")
        with self.assertRaises(ValueError):w.check_database(c)
        c.commit.assert_not_called()
    def test_production_gate(self):
        c=MagicMock()
        with patch.dict(w.os.environ,{"MYR_PRODUCTION_RELEASE":"synthetic"}):
            with self.assertRaises(ValueError):w.check_database(c)
        c.execute.assert_not_called()
    def exercise(self,timeout=False):
        c=MagicMock();c.__enter__.return_value=c
        c.execute.return_value.fetchone.return_value=(1,)
        connect=MagicMock(return_value=c)
        def send(g,payload):
            self.assertEqual(c.commit.call_count,1) # reservation already committed
            if timeout:raise TimeoutError("synthetic")
            return {"submissionUID":"SUB1"}
        with patch.object(w,"grant",return_value=self.g),patch.object(w,"check_database"),patch.object(w,"bind",return_value=(self.x["tin"],"123",self.x)),patch.object(w,"verify_grant"),patch.object(w,"reserve",return_value={"documents":[]}),patch.object(w,"post_once",side_effect=send) as post,patch.object(w,"accept",return_value=Receipt("SUB1","DOC1","INV-1")) as accept,patch.object(w,"outcome_unknown") as unknown:
            result=w.run_once(connect,self.cid,"INV-1",1)
            post.assert_called_once()
            if timeout:
                self.assertEqual(result["state"],"outcome_unknown")
                self.assertFalse(result["retry_enabled"])
                unknown.assert_called_once();accept.assert_not_called()
            else:
                self.assertEqual(result["state"],"accepted")
                accept.assert_called_once();unknown.assert_not_called()
    def test_success(self):self.exercise()
    def test_timeout(self):self.exercise(True)

if __name__=="__main__":main()
