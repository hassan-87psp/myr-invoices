"""Redacted display of an already verified, persisted Sandbox receipt.
Trusted caller must read the exact tenant-scoped intent after owner authorization.
No production projection, DB writes, browser-supplied status or QR provider.
The QR payload is a URL, not a generated QR image.
"""
import datetime as dt
import unittest
from lhdn_protocol_candidate import identifier,validation_link,require
STATES={"prepared","dispatching","outcome_unknown","accepted","valid","invalid","cancelled"}

def project(record,environment):
    require(environment=="sandbox","Sandbox only")
    if record is None:return {"environment":"sandbox","status":"Not submitted","uuid":None,"verification_url":None,"qr_payload":None}
    state=record["state"]
    require(state in STATES,"Invalid persisted state")
    result={"environment":"sandbox","status":{"prepared":"Prepared","dispatching":"Submitting","outcome_unknown":"Review required","accepted":"Submitted — validation pending","valid":"Valid","invalid":"Invalid","cancelled":"Cancelled"}[state],
            "uuid":None,"verification_url":None,"qr_payload":None}
    if state in ("accepted","valid","invalid","cancelled"):
        result["uuid"]=identifier(record["uuid"])
        identifier(record["submission"])
    if state=="valid":
        validated=record["validated_at"]
        require(isinstance(validated,dt.datetime) and validated.tzinfo is not None,"Verified timestamp required")
        long_id=identifier(record["long_id"])
        url=validation_link("sandbox",result["uuid"],long_id,"Valid")
        result.update(verification_url=url,qr_payload=url,validated_at=validated.astimezone(dt.timezone.utc).isoformat())
    return result

class Tests(unittest.TestCase):
    row={"state":"accepted","uuid":"DOC123","submission":"SUB123","long_id":"LONG123","validated_at":dt.datetime(2026,11,28,tzinfo=dt.timezone.utc),"bytes":b"private"}
    def test_pending(self):
        for state in ("prepared","dispatching","outcome_unknown","accepted","invalid","cancelled"):
            r=project({**self.row,"state":state},"sandbox")
            self.assertIsNone(r["qr_payload"]);self.assertNotIn("bytes",r)
    def test_valid(self):
        r=project({**self.row,"state":"valid"},"sandbox")
        self.assertEqual(r["qr_payload"],"https://preprod.myinvois.hasil.gov.my/DOC123/share/LONG123")
        self.assertEqual(r["verification_url"],r["qr_payload"])
    def test_fail_closed(self):
        with self.assertRaises(ValueError):project(self.row,"production")
        with self.assertRaises(ValueError):project({**self.row,"state":"valid","long_id":None},"sandbox")
        with self.assertRaises(ValueError):project({**self.row,"state":"valid","validated_at":None},"sandbox")
if __name__=="__main__":unittest.main()
