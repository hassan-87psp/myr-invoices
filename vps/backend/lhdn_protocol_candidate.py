"""Offline MyInvois protocol foundation. No network, DB mutations or production route.
Input documents must be server-generated, schema-validated and approved before use.
This is not a UBL generator or a signing implementation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from base64 import b64encode
from urllib.parse import quote, urlencode
import json
import re
import unittest

API={"sandbox":"https://preprod-api.myinvois.hasil.gov.my","production":"https://api.myinvois.hasil.gov.my"}
PORTAL={"sandbox":"https://preprod.myinvois.hasil.gov.my","production":"https://myinvois.hasil.gov.my"}
STATES={"Submitted","Valid","Invalid","Cancelled"}
# Conservative single-document pilot; provider size and current version must be reviewed at release.
MAX_DOCUMENT=250_000

def require(condition, message):
    if not condition: raise ValueError(message)

def identifier(value):
    require(isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}",value),"Invalid provider identifier")
    return value

def environment(value):
    require(isinstance(value,str) and value in API,"Invalid environment")
    return value

def text_value(value, maximum):
    require(isinstance(value,str) and 0<len(value)<=maximum and value==value.strip() and not any(ord(c)<32 for c in value),"Invalid text")
    return value

def tin_validation_path(tin,id_type,id_value):
    require(isinstance(tin,str) and re.fullmatch(r"[A-Z]{1,3}[0-9]{1,20}",tin),"Invalid TIN format")
    require(isinstance(id_type,str) and id_type in ("BRN","NRIC","PASSPORT","ARMY"),"Unsupported identity type")
    require(isinstance(id_value,str) and re.fullmatch(r"[A-Z0-9-]{1,40}",id_value),"Invalid identity value")
    return "/api/v1.0/taxpayer/validate/"+quote(tin,safe="")+"?"+urlencode({"idType":id_type,"idValue":id_value})

def validation_result(http_status):
    return {200:"validated",400:"invalid_input",404:"identity_not_matched",401:"authentication_required",403:"permission_denied",429:"rate_limited"}.get(http_status,"unavailable")

def _unique_object(items):
    result={}
    for key,value in items:
        require(key not in result,"Duplicate JSON property")
        result[key]=value
    return result

def _reject_constant(value):
    raise ValueError("Nonfinite JSON number")

def make_submission(document:bytes,code_number:str):
    """Prepare exact UTF-8 UBL JSON bytes; do not transform or sign here."""
    text_value(code_number,100)
    require(type(document) is bytes and 0<len(document)<=MAX_DOCUMENT,"Invalid document size")
    parsed=json.loads(document.decode("utf-8"),object_pairs_hook=_unique_object,parse_constant=_reject_constant)
    require(isinstance(parsed,dict),"Document must be a JSON object")
    # Verify that the local code number matches the UBL internal ID.
    # Structural validation and financial totals are separate mandatory gates.
    try:
        inv=parsed["Invoice"]
        require(isinstance(inv,list) and len(inv)==1,"Expected one invoice")
        ids=inv[0]["ID"]
        require(isinstance(ids,list) and len(ids)==1 and ids[0]["_"]==code_number,"Invoice code mismatch")
    except (KeyError,IndexError,TypeError):
        raise ValueError("Missing UBL invoice identifier") from None
    return {"documents":[{"format":"JSON","document":b64encode(document).decode("ascii"),"documentHash":sha256(document).hexdigest(),"codeNumber":code_number}]}

@dataclass(frozen=True)
class Receipt:
    submission_uid:str
    uuid:str
    code_number:str

def parse_accepted(http_status,data,code_number):
    """Only an unambiguous single acceptance yields a receipt. Never infer Valid."""
    require(http_status==202 and isinstance(data,dict),"Submission outcome requires reconciliation")
    accepted=data.get("acceptedDocuments")
    rejected=data.get("rejectedDocuments")
    require(isinstance(accepted,list) and len(accepted)==1 and rejected==[],"Submission not uniquely accepted")
    item=accepted[0]
    require(isinstance(item,dict) and item.get("invoiceCodeNumber")==code_number,"Accepted code mismatch")
    uid=data.get("submissionUid",data.get("submissionUID"))
    require("submissionUid" not in data or "submissionUID" not in data or data["submissionUid"]==data["submissionUID"],"Conflicting submission identifiers")
    return Receipt(identifier(uid),identifier(item.get("uuid")),text_value(code_number,100))

def submission_path(receipt):
    return "/api/v1.0/documentsubmissions/"+identifier(receipt.submission_uid)+"?pageNo=1&pageSize=10"

def validation_link(env,uuid,long_id,status):
    environment(env)
    if status!="Valid" or not long_id:return None
    return PORTAL[env]+"/"+identifier(uuid)+"/share/"+identifier(long_id)

def parse_status(data,receipt,issuer_tin,env):
    """Poll only a stored tenant-bound receipt; reject mismatched provider response."""
    environment(env)
    require(isinstance(data,dict) and data.get("submissionUid")==receipt.submission_uid,"Submission mismatch")
    summaries=data.get("documentSummary")
    require(isinstance(summaries,list),"Missing summary")
    items=[x for x in summaries if isinstance(x,dict) and x.get("uuid")==receipt.uuid]
    require(len(items)==1,"Document not uniquely found")
    row=items[0]
    require(row.get("submissionUid")==receipt.submission_uid and row.get("internalId")==receipt.code_number and row.get("issuerTin")==issuer_tin,"Document ownership mismatch")
    status=row.get("status")
    require(isinstance(status,str) and status in STATES,"Unknown provider status")
    long_id=row.get("longId")
    if status=="Valid":
        require(bool(long_id),"Valid document missing verification ID")
        require(isinstance(row.get("dateTimeValidated"),str),"Missing validation timestamp")
        parse_time(row["dateTimeValidated"])
    return {"status":status,"uuid":receipt.uuid,"submission_uid":receipt.submission_uid,
            "long_id":identifier(long_id) if status=="Valid" else None,
            "validated_at":row.get("dateTimeValidated") if status=="Valid" else None,
            "verification_url":validation_link(env,receipt.uuid,long_id,status)}

def parse_time(value):
    require(isinstance(value,str),"Missing time")
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    require(result.tzinfo is not None,"Timezone required")
    return result.astimezone(timezone.utc)

def cancellation_request(receipt,status,validated_at,now,reason,window_hours=72):
    """Conservative issuer-only candidate; provider workflow rules still authoritative."""
    require(status=="Valid","Only a validated issued document is eligible in this pilot")
    require(type(window_hours) is int and 0<window_hours<=72,"Invalid cancellation window")
    require(isinstance(now,datetime) and now.tzinfo is not None,"Timezone required")
    validated=parse_time(validated_at)
    require(validated<=now<validated+timedelta(hours=window_hours),"Cancellation window closed")
    text_value(reason,300)
    return "/api/v1.0/documents/state/"+identifier(receipt.uuid)+"/state",{"status":"cancelled","reason":reason}

def retry_after(header,now=None):
    """Never shorten provider wait; conservative fallback for missing/invalid headers."""
    now=now or datetime.now(timezone.utc)
    try:
        if isinstance(header,str) and re.fullmatch(r"\d{1,12}",header):
            return max(5,int(header))
        value=parsedate_to_datetime(header)
        require(value.tzinfo is not None,"Timezone required")
        import math
        return max(5,math.ceil((value-now).total_seconds()))
    except (TypeError,ValueError,OverflowError):
        return 60

def next_action(operation,http_status=None,transport_failed=False):
    """No automatic resubmission after an uncertain write result."""
    require(operation in ("validate","poll","submit","cancel"),"Unknown operation")
    require(type(transport_failed) is bool,"Invalid transport state")
    if operation in ("submit","cancel"):
        if transport_failed or http_status is None or http_status>=500 or http_status==429 or (operation=="submit" and http_status==422):
            return "reconcile_before_retry"
        if (operation=="submit" and http_status==202) or (operation=="cancel" and http_status==200):
            return "parse_provider_response"
        return "operator_review"
    if transport_failed or http_status is None or http_status>=500 or http_status==429:
        return "retry_with_backoff"
    if http_status==401:return "renew_token_once"
    return "parse_provider_response" if http_status==200 else "operator_review"

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.receipt=Receipt("SUB123","UUID123","INV-1")
        self.row={"uuid":"UUID123","submissionUid":"SUB123","internalId":"INV-1","issuerTin":"C1234567890","status":"Valid","longId":"LONG123","dateTimeValidated":"2026-11-26T00:00:00Z"}
    def test_tin(self):
        self.assertEqual(tin_validation_path("C1234567890","BRN","123456789012"),"/api/v1.0/taxpayer/validate/C1234567890?idType=BRN&idValue=123456789012")
        self.assertEqual(validation_result(404),"identity_not_matched")
        self.assertEqual(validation_result(403),"permission_denied")
        with self.assertRaises(ValueError):tin_validation_path("C1/2","BRN","123")
    def test_exact_hash(self):
        from base64 import b64decode
        d=b'{"Invoice":[{"ID":[{"_":"INV-1"}]}]}'
        packet=make_submission(d,"INV-1")["documents"][0]
        self.assertEqual(b64decode(packet["document"]),d)
        self.assertEqual(packet["documentHash"],sha256(d).hexdigest())
        with self.assertRaises(ValueError):make_submission(d,"INV-2")
        with self.assertRaises(ValueError):make_submission(b'{"Invoice":[],"Invoice":[]}',"INV-1")
    def test_receipt(self):
        data={"submissionUid":"SUB123","acceptedDocuments":[{"uuid":"UUID123","invoiceCodeNumber":"INV-1"}],"rejectedDocuments":[]}
        self.assertEqual(parse_accepted(202,data,"INV-1"),self.receipt)
        with self.assertRaises(ValueError):parse_accepted(202,data,"INV-2")
        with self.assertRaises(ValueError):parse_accepted(200,data,"INV-1")
    def test_status_and_qr(self):
        data={"submissionUid":"SUB123","documentSummary":[self.row]}
        self.assertEqual(parse_status(data,self.receipt,"C1234567890","sandbox")["verification_url"],"https://preprod.myinvois.hasil.gov.my/UUID123/share/LONG123")
        with self.assertRaises(ValueError):parse_status(data,self.receipt,"C0000000000","sandbox")
        self.row["status"]="Submitted"
        self.assertIsNone(parse_status(data,self.receipt,"C1234567890","sandbox")["verification_url"])
    def test_cancel(self):
        now=parse_time("2026-11-28T23:59:59Z")
        self.assertEqual(cancellation_request(self.receipt,"Valid","2026-11-26T00:00:00Z",now,"Wrong details")[1]["status"],"cancelled")
        with self.assertRaises(ValueError):cancellation_request(self.receipt,"Valid","2026-11-26T00:00:00Z",now+timedelta(seconds=1),"Wrong details")
        with self.assertRaises(ValueError):cancellation_request(self.receipt,"Valid","2026-11-26T00:00:00Z",now,"x"*301)
    def test_retries(self):
        self.assertEqual(retry_after("90"),90)
        self.assertEqual(retry_after(None),60)
        self.assertEqual(next_action("submit",503),"reconcile_before_retry")
        self.assertEqual(next_action("submit",422),"reconcile_before_retry")
        self.assertEqual(next_action("submit",transport_failed=True),"reconcile_before_retry")
        self.assertEqual(next_action("poll",429),"retry_with_backoff")
        self.assertEqual(next_action("validate",401),"renew_token_once")

if __name__=="__main__":
    unittest.main()
