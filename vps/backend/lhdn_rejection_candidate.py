"""Offline buyer rejection planner. Not a transport or authorization service.
The binding must come from a trusted provider read under the authorized buyer
context, never from user-submitted JSON. No incoming invoice routes exist yet.
"""
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from lhdn_protocol_candidate import require,identifier,text_value,parse_time
import unittest

@dataclass(frozen=True)
class ReceivedDocument:
    company_id:str
    receiver_tin:str
    environment:str
    uuid:str
    issuer_tin:str
    status:str
    validated_at:str
    rejection_requested:bool
    observed_at:datetime

def rejection_plan(document,company_id,buyer_tin,now,reason,window_hours=72):
    require(type(document) is ReceivedDocument,"Trusted received document required")
    require(document.environment=="sandbox","Sandbox only")
    require(document.company_id==company_id and document.receiver_tin==buyer_tin and buyer_tin!=document.issuer_tin,"Buyer binding mismatch")
    require(isinstance(now,datetime) and now.tzinfo is not None,"UTC clock required")
    require(isinstance(document.observed_at,datetime) and document.observed_at.tzinfo is not None,"Provider observation required")
    require(timedelta(0)<=now-document.observed_at<=timedelta(minutes=5),"Refresh provider status")
    require(document.status=="Valid" and document.rejection_requested is False,"Rejection not eligible")
    require(type(window_hours) is int and 0<window_hours<=72,"Invalid workflow window")
    validated=parse_time(document.validated_at)
    require(validated<=now<validated+timedelta(hours=window_hours),"Rejection window closed")
    return {"method":"PUT","path":"/api/v1.0/documents/state/"+identifier(document.uuid)+"/state",
            "body":{"status":"rejected","reason":text_value(reason,300)}}

def parse_rejection(http_status,response,expected_uuid):
    require(http_status==200 and isinstance(response,dict),"Rejection outcome requires review")
    require(response.get("uuid")==identifier(expected_uuid),"Document UUID mismatch")
    require(response.get("status")=="Requested for Rejection" and not response.get("error"),"Unconfirmed rejection")
    # The seller still has to cancel. Do not replace official Valid status.
    return {"status":"Valid","rejection_requested":True,"cancelled":False}

class Tests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,27,3,tzinfo=timezone.utc)
        self.doc=ReceivedDocument("tenant-1","C1234567890","sandbox","DOC123","C9876543210","Valid",self.now.isoformat(),False,self.now)
    def plan(self,doc=None,now=None,tenant="tenant-1"):
        return rejection_plan(doc or self.doc,tenant,"C1234567890",now or self.now,"Incorrect buyer details")
    def test_plan(self):
        self.assertEqual(self.plan()["body"]["status"],"rejected")
    def test_tenant(self):
        with self.assertRaises(ValueError):self.plan(tenant="other")
    def test_duplicate(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):self.plan(replace(self.doc,rejection_requested=True))
    def test_production_blocked(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):self.plan(replace(self.doc,environment="production"))
    def test_stale(self):
        with self.assertRaises(ValueError):self.plan(now=self.now+timedelta(minutes=6))
    def test_window(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):self.plan(replace(self.doc,validated_at=(self.now-timedelta(hours=72)).isoformat()))
    def test_response(self):
        self.assertEqual(parse_rejection(200,{"uuid":"DOC123","status":"Requested for Rejection"},"DOC123"),
            {"status":"Valid","rejection_requested":True,"cancelled":False})
        with self.assertRaises(ValueError):parse_rejection(200,{"uuid":"OTHER","status":"Requested for Rejection"},"DOC123")

if __name__=="__main__":
    unittest.main()
