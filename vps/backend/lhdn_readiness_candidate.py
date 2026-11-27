"""Read-only invoice readiness candidate, no provider requests or writes.
Do not mount publicly until ASGI and database integration review passes.
"""
from datetime import datetime, timezone
from uuid import UUID
from lhdn_saved_invoice_candidate import preview
from lhdn_protocol_candidate import require
import unittest
from unittest.mock import patch

def readiness(conn,actor_id,company_id,invoice_id,expected_version,confirmed_total_sen,now):
    require(isinstance(actor_id,UUID) and isinstance(company_id,UUID),"Verified actor and company IDs required")
    require(type(expected_version) is int and expected_version>0,"Company version required")
    require(isinstance(invoice_id,str) and 1<=len(invoice_id)<=128,"Invoice ID required")
    # Recheck the actual native user, role, company and invoice version.
    company=conn.execute("""SELECT c.version,c.tin,c.data
        FROM myr_native.companies c JOIN myr_native.company_members m ON m.company_id=c.id
        JOIN myr_native.users u ON u.email=m.email
        WHERE c.id=%s AND u.id=%s AND u.disabled=false
          AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
          AND m.role='Owner' AND m.status='active' AND c.status='active'
          AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'""",
        (company_id,actor_id)).fetchone()
    if company is None:
        return {"status":"unavailable","submission_enabled":False}
    version,tin,data=company
    if version!=expected_version:
        return {"status":"stale","submission_enabled":False}
    if not isinstance(data,dict) or tin!=data.get("tin"):
        return {"status":"identity_review_required","submission_enabled":False}
    official=conn.execute("""SELECT 1 FROM myr_native.lhdn_documents
        WHERE company_id=%s AND invoice_id=%s""",(company_id,invoice_id)).fetchone()
    if official is not None:
        return {"status":"existing_document","submission_enabled":False}
    # No raw UBL, tax identifiers, credentials or provider token leave the server.
    try:
        result=preview(data,invoice_id,confirmed_total_sen,now)
    except (ValueError,TypeError,KeyError,OverflowError):
        return {"status":"invoice_review_required","submission_enabled":False}
    return {"status":"offline_preview_ready","submission_enabled":False,
            "provider_verified":False,"schema_verified":False,"signature_verified":False,
            "document_bytes":len(result["document"]),"company_version":version}

class FakeCursor:
    def __init__(self,value):self.value=value
    def fetchone(self):return self.value

class FakeConn:
    def __init__(self,*values):self.values=list(values);self.calls=[]
    def execute(self,sql,params):
        self.calls.append((sql,params))
        if not sql.lstrip().startswith("SELECT"):raise AssertionError("Unexpected write")
        return FakeCursor(self.values.pop(0))

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.actor=UUID(int=1);self.company=UUID(int=2);self.now=datetime(2026,11,27,3,tzinfo=timezone.utc)
    def call(self,conn):
        return readiness(conn,self.actor,self.company,"INV-1",3,1000,self.now)
    def test_not_member(self):
        c=FakeConn(None)
        self.assertEqual(self.call(c)["status"],"unavailable")
        self.assertEqual(c.calls[0][1],(self.company,self.actor))
    def test_stale(self):
        self.assertEqual(self.call(FakeConn((4,"C1",{"tin":"C1"})))["status"],"stale")
    def test_existing(self):
        self.assertEqual(self.call(FakeConn((3,"C1",{"tin":"C1"}),(1,)))["status"],"existing_document")
    def test_ready_not_verified(self):
        with patch(__name__+".preview",return_value={"document":b"synthetic"}):
            c=FakeConn((3,"C1",{"tin":"C1"}),None)
            d=self.call(c)
        self.assertEqual(d["status"],"offline_preview_ready")
        self.assertFalse(d["submission_enabled"])
        self.assertFalse(d["provider_verified"])
        self.assertNotIn("document",d)
    def test_invalid(self):
        with patch(__name__+".preview",side_effect=ValueError("private invoice value")):
            d=self.call(FakeConn((3,"C1",{"tin":"C1"}),None))
        self.assertEqual(d,{"status":"invoice_review_required","submission_enabled":False})

if __name__=="__main__":
    unittest.main()
