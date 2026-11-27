"""Sandbox-only database lifecycle candidate. No HTTP endpoints or network calls.

Requires the separately reviewed intent table and trusted provider responses.
Caller owns transaction boundaries; commit reservation before any future HTTP call.
Do not wire to production until invoice edit/delete guards and authorization gates pass.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from uuid import UUID
import re
import unittest
from lhdn_protocol_candidate import (
    require, Receipt, make_submission, parse_accepted, parse_status,
    parse_time, submission_path, cancellation_request, retry_after,
)

TABLE="myr_native.lhdn_submission_intents"
STATES={"accepted":{"Submitted":"accepted","Valid":"valid","Invalid":"invalid","Cancelled":"cancelled"},
        "valid":{"Valid":"valid","Cancelled":"cancelled"},
        "invalid":{"Invalid":"invalid"},"cancelled":{"Cancelled":"cancelled"}}

def scoped(company_id,invoice_id,environment):
    require(environment=="sandbox","Only sandbox lifecycle candidate is enabled")
    require(isinstance(company_id,(str,UUID)),"Company UUID required")
    company_id=UUID(str(company_id))
    require(isinstance(invoice_id,str) and 1<=len(invoice_id)<=128,"Invoice ID required")
    return company_id,invoice_id,environment

def row(conn,key,lock=True):
    # Every operation is scoped to exact tenant, invoice and environment.
    value=conn.execute(f"""SELECT company_version,code_number,issuer_tin,document_hash,
        document_bytes,state,submission_uid,provider_uuid,long_id,validated_at,
        dispatch_started_at,updated_at FROM {TABLE}
        WHERE company_id=%s AND invoice_id=%s AND environment=%s"""+(" FOR UPDATE" if lock else ""),key).fetchone()
    require(value is not None,"Intent unavailable")
    return dict(zip(("version","code","tin","hash","bytes","state","submission","uuid","long_id","validated_at","started","updated_at"),value))

def clock(value):
    require(isinstance(value,datetime) and value.tzinfo is not None,"Trusted UTC time required")
    return value.astimezone(timezone.utc)

def prepare(conn,company_id,invoice_id,environment,version,actor,confirmed_total_sen,now):
    """Load the stored company under a lock and generate exact document bytes.
    An already verified owner identity is required; never accept a client UBL.
    """
    from lhdn_saved_invoice_candidate import preview
    key=scoped(company_id,invoice_id,environment)
    require(type(version) is int and version>0,"Company revision required")
    require(isinstance(actor,UUID),"Verified actor UUID required")
    result=conn.execute("""SELECT c.version,c.data,c.tin FROM myr_native.companies c
        JOIN myr_native.users u ON u.id=%s
        JOIN myr_native.company_members m ON m.company_id=c.id AND m.email=u.email
        WHERE c.id=%s AND c.status='active' AND u.disabled=false
        AND u.email_verified_at IS NOT NULL AND NOT u.is_platform_admin
        AND m.status='active' AND m.role='Owner'
        AND c.data->>'vpsSyntheticWriteTest' IS DISTINCT FROM 'true'
        FOR UPDATE OF c FOR SHARE OF u,m""",(actor,key[0])).fetchone()
    require(result is not None and result[0]==version,"Company unavailable or revision changed")
    data=result[1]; tin=result[2]
    require(isinstance(tin,str) and tin==data.get("tin"),"Supplier identity mismatch")
    require(conn.execute("""SELECT 1 FROM myr_native.lhdn_documents
        WHERE company_id=%s AND invoice_id=%s""",key[:2]).fetchone() is None,"Existing official document")
    doc=preview(data,invoice_id,confirmed_total_sen,clock(now))
    raw=doc["document"]; item=doc["payload"]["documents"][0]
    digest=sha256(raw).hexdigest()
    require(item["documentHash"]==digest,"Document hash mismatch")
    inserted=conn.execute(f"""INSERT INTO {TABLE}
        (company_id,invoice_id,environment,company_version,code_number,issuer_tin,
         document_hash,document_bytes,created_by)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT(company_id,invoice_id,environment) DO NOTHING RETURNING state""",
        (*key,version,item["codeNumber"],tin,digest,raw,actor)).fetchone()
    require(inserted is not None,"Existing intent requires review; no replacement")
    return {"state":"prepared","document_hash":digest}

def reserve(conn,company_id,invoice_id,environment,version,now):
    """Private worker candidate. No dispatch is performed by this method.
    Company lock then intent lock is the required order for mutation guards.
    """
    key=scoped(company_id,invoice_id,environment)
    company=conn.execute("SELECT version,tin,status FROM myr_native.companies WHERE id=%s FOR UPDATE",(key[0],)).fetchone()
    require(company is not None and company[0]==version and company[2]=="active","Company changed")
    x=row(conn,key)
    require(x["state"]=="prepared" and x["version"]==version and x["tin"]==company[1],"Intent cannot be reserved")
    raw=bytes(x["bytes"])
    require(sha256(raw).hexdigest()==x["hash"],"Stored document damaged")
    payload=make_submission(raw,x["code"])
    conn.execute(f"""UPDATE {TABLE} SET state='dispatching',dispatch_started_at=%s,
        updated_at=%s WHERE company_id=%s AND invoice_id=%s AND environment=%s""",(clock(now),clock(now),*key))
    return payload  # Never send before the surrounding transaction commits.

def outcome_unknown(conn,company_id,invoice_id,environment,now):
    key=scoped(company_id,invoice_id,environment); x=row(conn,key)
    require(x["state"]=="dispatching","Only dispatched intents can become uncertain")
    conn.execute(f"""UPDATE {TABLE} SET state='outcome_unknown',updated_at=%s
        WHERE company_id=%s AND invoice_id=%s AND environment=%s""",(clock(now),*key))

def accept(conn,company_id,invoice_id,environment,http_status,response,now):
    """Only a response from the trusted submission operation may enter here.
    An unknown outcome must be reconciled separately, not blindly accepted.
    """
    key=scoped(company_id,invoice_id,environment); x=row(conn,key)
    require(x["state"]=="dispatching","No outstanding dispatch")
    receipt=parse_accepted(http_status,response,x["code"])
    conn.execute(f"""UPDATE {TABLE} SET state='accepted',submission_uid=%s,
        provider_uuid=%s,updated_at=%s WHERE company_id=%s AND invoice_id=%s
        AND environment=%s""",(receipt.submission_uid,receipt.uuid,clock(now),*key))
    return receipt

def status_change(x,response,environment,now):
    require(environment=="sandbox","Sandbox only")
    require(x["state"] in STATES,"No accepted receipt to poll")
    receipt=Receipt(x["submission"],x["uuid"],x["code"])
    parsed=parse_status(response,receipt,x["tin"],environment)
    state=STATES[x["state"]].get(parsed["status"])
    require(state is not None,"Stale or invalid provider status transition")
    validated=parse_time(parsed["validated_at"]) if parsed["validated_at"] else x["validated_at"]
    if validated is not None:
        require(validated<=clock(now)+timedelta(seconds=60),"Future validation timestamp")
        if x.get("validated_at") is not None:require(validated==x["validated_at"],"Validation timestamp changed")
    return {"state":state,"long_id":parsed["long_id"],"validated_at":validated,
            "verification_url":parsed["verification_url"]}

def sync(conn,company_id,invoice_id,environment,response,now):
    """Save only trusted provider status in sandbox intent table.
    Deliberately does not alter production official-document records.
    """
    key=scoped(company_id,invoice_id,environment); x=row(conn,key)
    change=status_change(x,response,environment,now)
    conn.execute(f"""UPDATE {TABLE} SET state=%s,long_id=%s,validated_at=%s,
        updated_at=%s WHERE company_id=%s AND invoice_id=%s AND environment=%s""",
        (change["state"],change["long_id"],change["validated_at"],clock(now),*key))
    return change

def poll_plan(x,now,retry_header=None):
    require(x["state"] in ("accepted","valid"),"No active polling")
    seconds=5 if retry_header is None else retry_after(retry_header,clock(now))
    due=clock(x["updated_at"])+timedelta(seconds=seconds)
    require(clock(now)>=due,"Polling interval or provider backoff not elapsed")
    return submission_path(Receipt(x["submission"],x["uuid"],x["code"]))

def cancel_plan(x,now,reason):
    require(x["state"]=="valid" and x["validated_at"] is not None,"Validated issuer document required")
    return cancellation_request(Receipt(x["submission"],x["uuid"],x["code"]),
        "Valid",x["validated_at"].isoformat(),clock(now),reason)

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,27,3,tzinfo=timezone.utc)
        self.x={"state":"accepted","submission":"SUB123","uuid":"DOC123","code":"INV1","tin":"C1234567890",
            "validated_at":None,"updated_at":self.now-timedelta(seconds=10)}
        self.response={"submissionUid":"SUB123","documentSummary":[{"uuid":"DOC123","submissionUid":"SUB123",
            "internalId":"INV1","issuerTin":"C1234567890","status":"Valid","longId":"LONG123",
            "dateTimeValidated":self.now.isoformat()}]}
    def test_validation(self):
        result=status_change(self.x,self.response,"sandbox",self.now)
        self.assertEqual(result["state"],"valid")
        self.assertEqual(result["verification_url"],"https://preprod.myinvois.hasil.gov.my/DOC123/share/LONG123")
    def test_mismatch(self):
        self.response["documentSummary"][0]["issuerTin"]="C9999999999"
        with self.assertRaises(ValueError):status_change(self.x,self.response,"sandbox",self.now)
    def test_no_regression(self):
        self.x["state"]="valid";self.response["documentSummary"][0]["status"]="Submitted"
        with self.assertRaises(ValueError):status_change(self.x,self.response,"sandbox",self.now)
    def test_cancel(self):
        self.x.update(state="valid",validated_at=self.now)
        self.assertEqual(cancel_plan(self.x,self.now,"Incorrect invoice")[1]["status"],"cancelled")
        with self.assertRaises(ValueError):cancel_plan(self.x,self.now+timedelta(hours=72),"Incorrect invoice")
    def test_poll_backoff(self):
        self.assertIn("SUB123",poll_plan(self.x,self.now))
        with self.assertRaises(ValueError):poll_plan(self.x,self.now,"60")
        self.x["state"]="outcome_unknown"
        with self.assertRaises(ValueError):poll_plan(self.x,self.now)
    def test_production_blocked(self):
        with self.assertRaises(ValueError):scoped(UUID(int=1),"INV1","production")
        with self.assertRaises(ValueError):status_change(self.x,self.response,"production",self.now)

if __name__=="__main__":
    unittest.main()
