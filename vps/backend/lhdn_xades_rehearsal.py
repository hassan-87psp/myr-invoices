"""MyInvois JSON v1.1 XAdES assembly rehearsal, synthetic certificates only.

SDK structure and signed-properties digest fixture are exercised offline.
Not a provider-certified signer: real certificate trust, revocation,
canonicalization interoperability and sandbox acceptance remain mandatory.
"""
from datetime import datetime,timezone
from decimal import Decimal
from hashlib import sha256
from base64 import b64encode,b64decode
import json
import unittest
from lhdn_protocol_candidate import require,_unique_object,_reject_constant
from lhdn_ubl_candidate import exact_json,leaf
from lhdn_signing_candidate import profile,digest_material,rsa_primitive

HASH="http://www.w3.org/2001/04/xmlenc#sha256"
RSA="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
METHOD="urn:oasis:names:specification:ubl:dsig:enveloped:xades"
SIG_ID="urn:oasis:names:specification:ubl:signature:Invoice"
PROPS_ID="id-xades-signed-props"

def digest(value):
    return b64encode(sha256(exact_json(value).encode("utf-8")).digest()).decode("ascii")

def props(time,cert_digest,issuer,serial):
    return {"Target":"signature","SignedProperties":[{"Id":PROPS_ID,"SignedSignatureProperties":[{
        "SigningTime":leaf(time),"SigningCertificate":[{"Cert":[{
            "CertDigest":[{"DigestMethod":leaf("",Algorithm=HASH),"DigestValue":leaf(cert_digest)}],
            "IssuerSerial":[{"X509IssuerName":leaf(issuer),"X509SerialNumber":leaf(serial)}]
        }]}]}]}]}

def parse_document(raw):
    require(type(raw) is bytes and 0<len(raw)<=250000,"Document bytes required")
    doc=json.loads(raw.decode("utf-8"),parse_float=Decimal,object_pairs_hook=_unique_object,parse_constant=_reject_constant)
    require(isinstance(doc,dict) and isinstance(doc.get("Invoice"),list) and len(doc["Invoice"])==1 and isinstance(doc["Invoice"][0],dict),"Single invoice required")
    return doc,doc["Invoice"][0]

def assemble_synthetic(raw,cert,key,now):
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    # Only a disposable self-signed test identity is supported here.
    require(cert.subject==cert.issuer,"Synthetic self-signed certificate only")
    cn=cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    require(len(cn)==1 and cn[0].value=="Synthetic signer","Synthetic fixture certificate only")
    profile(cert,"C1234567890","202001234567",now)
    cert.public_key().verify(cert.signature,cert.tbs_certificate_bytes,padding.PKCS1v15(),hashes.SHA256())
    doc,invoice=parse_document(raw)
    require("UBLExtensions" not in invoice and "Signature" not in invoice,"Unsigned invoice required")
    require(invoice.get("InvoiceTypeCode")==leaf("01",listVersionID="1.0"),"Ordinary unsigned v1.0 fixture required")
    # Update the version before hashing; never mutate content after signing.
    invoice["InvoiceTypeCode"]=leaf("01",listVersionID="1.1")
    material=digest_material(exact_json(doc).encode("utf-8"),cert)
    signature=rsa_primitive(key,cert,material["digest_bytes"])
    issuer=cert.issuer.rfc4514_string()
    serial=str(cert.serial_number)
    stamp=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p=props(stamp,material["certificate_digest"],issuer,serial)
    def ref(uri,typ,value):
        return {"Type":typ,"URI":uri,"DigestMethod":leaf("",Algorithm=HASH),"DigestValue":leaf(value)}
    sig={"Id":"signature",
         "Object":[{"QualifyingProperties":[p]}],
         "KeyInfo":[{"X509Data":[{"X509Certificate":leaf(b64encode(cert.public_bytes(Encoding.DER)).decode("ascii")),
             "X509SubjectName":leaf(cert.subject.rfc4514_string()),
             "X509IssuerSerial":[{"X509IssuerName":leaf(issuer),"X509SerialNumber":leaf(serial)}]}]}],
         "SignatureValue":leaf(signature),
         "SignedInfo":[{"SignatureMethod":leaf("",Algorithm=RSA),"Reference":[
             ref("#"+PROPS_ID,"http://uri.etsi.org/01903/v1.3.2#SignedProperties",digest(p)),
             ref("","",material["document_digest"])]}]}
    info={"ID":leaf("urn:oasis:names:specification:ubl:signature:1"),
          "ReferencedSignatureID":leaf(SIG_ID),"Signature":[sig]}
    invoice["UBLExtensions"]=[{"UBLExtension":[{"ExtensionURI":leaf(METHOD),
        "ExtensionContent":[{"UBLDocumentSignatures":[{"SignatureInformation":[info]}]}]}]}]
    invoice["Signature"]=[{"ID":leaf(SIG_ID),"SignatureMethod":leaf(METHOD)}]
    signed=exact_json(doc).encode("utf-8")
    require(len(signed)<=250000,"Signed fixture too large")
    return signed

def verify_synthetic_document(raw,cert):
    """Verify own assembly fixture, not arbitrary external signed documents."""
    from cryptography.hazmat.primitives.asymmetric import padding,utils
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.serialization import Encoding
    doc,invoice=parse_document(raw)
    require(invoice.get("InvoiceTypeCode")==leaf("01",listVersionID="1.1"),"Expected signed version")
    ext=invoice.pop("UBLExtensions")
    require(invoice.pop("Signature")==[{"ID":leaf(SIG_ID),"SignatureMethod":leaf(METHOD)}],"Signature marker mismatch")
    sig=ext[0]["UBLExtension"][0]["ExtensionContent"][0]["UBLDocumentSignatures"][0]["SignatureInformation"][0]["Signature"][0]
    p=sig["Object"][0]["QualifyingProperties"][0]
    refs=sig["SignedInfo"][0]["Reference"]
    require(len(refs)==2 and refs[0]["URI"]=="#"+PROPS_ID and refs[1]["URI"]=="","Reference mismatch")
    m=digest_material(exact_json(doc).encode("utf-8"),cert)
    require(refs[0]["DigestValue"]==leaf(digest(p)) and refs[1]["DigestValue"]==leaf(m["document_digest"]),"Digest mismatch")
    cd=p["SignedProperties"][0]["SignedSignatureProperties"][0]["SigningCertificate"][0]["Cert"][0]["CertDigest"][0]["DigestValue"]
    require(cd==leaf(m["certificate_digest"]),"Certificate digest mismatch")
    embedded=sig["KeyInfo"][0]["X509Data"][0]["X509Certificate"][0]["_"]
    require(b64decode(embedded,validate=True)==cert.public_bytes(Encoding.DER),"Embedded certificate mismatch")
    cert.public_key().verify(b64decode(sig["SignatureValue"][0]["_"],validate=True),m["digest_bytes"],padding.PKCS1v15(),utils.Prehashed(hashes.SHA256()))
    return True

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lhdn_signing_candidate import SigningTests
        SigningTests.setUpClass()
        cls.cert,cls.key,cls.now=SigningTests.cert,SigningTests.key,SigningTests.now
        from lhdn_ubl_candidate import GeneratorTests,generate
        f=GeneratorTests();f.setUp()
        cls.raw=generate(f.s,f.now)
    def test_sdk_properties_vector(self):
        p=props("2024-07-23T15:14:54Z","KKBSTyiPKGkGl1AFqcPziKCEIDYGtnYUTQN4ukO7G40=",
            "CN=Trial LHDNM Sub CA V1, OU=Terms of use at http://www.posdigicert.com.my, O=LHDNM, C=MY",
            "162880276254639189035871514749820882117")
        self.assertEqual(digest(p),"Rzuzz+70GSnGBF1YxhHnjSzFpQ1MW4vyX/Q9bTHkE2c=")
    def test_signed_fixture(self):
        signed=assemble_synthetic(self.raw,self.cert,self.key,self.now)
        self.assertTrue(verify_synthetic_document(signed,self.cert))
    def test_modified_document(self):
        signed=assemble_synthetic(self.raw,self.cert,self.key,self.now)
        doc,invoice=parse_document(signed)
        invoice["ID"]=leaf("TAMPERED")
        with self.assertRaises(ValueError):verify_synthetic_document(exact_json(doc).encode(),self.cert)
    def test_double_sign_blocked(self):
        signed=assemble_synthetic(self.raw,self.cert,self.key,self.now)
        with self.assertRaises(ValueError):assemble_synthetic(signed,self.cert,self.key,self.now)

if __name__=="__main__":
    unittest.main()
