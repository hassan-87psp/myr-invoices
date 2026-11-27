"""Offline v1.1 certificate profile check and RSA digest primitive.
No certificate discovery, secret storage, network or submission.
Passing these checks is NOT MyInvois signature approval.
Complete XAdES JSON assembly, canonicalization vectors, approved CA chain,
revocation verification and taxpayer authorization remain separate gates.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from base64 import b64encode
from lhdn_protocol_candidate import require
import re
import unittest

def profile(cert,expected_tin,expected_brn,now):
    from cryptography import x509
    from cryptography.x509.oid import NameOID,ObjectIdentifier,ExtensionOID
    from cryptography.hazmat.primitives.asymmetric import rsa
    require(isinstance(cert,x509.Certificate),"X.509 certificate required")
    require(isinstance(now,datetime) and now.tzinfo is not None,"Trusted clock required")
    require(isinstance(expected_tin,str) and re.fullmatch(r"[A-Z]{1,3}[0-9]{1,13}",expected_tin),"Registered signer TIN required")
    require(isinstance(expected_brn,str) and re.fullmatch(r"[A-Z0-9-]{1,20}",expected_brn),"Registered signer BRN required")
    def one(oid):
        attrs=cert.subject.get_attributes_for_oid(oid)
        require(len(attrs)==1 and isinstance(attrs[0].value,str) and bool(attrs[0].value.strip()),"Missing or ambiguous certificate identity")
        return attrs[0].value
    one(NameOID.COMMON_NAME);one(NameOID.ORGANIZATION_NAME)
    require(one(NameOID.COUNTRY_NAME)=="MY","Malaysian signer profile required")
    require(one(ObjectIdentifier("2.5.4.97"))==expected_tin,"Signer TIN mismatch")
    require(one(NameOID.SERIAL_NUMBER)==expected_brn,"Signer BRN mismatch")
    require(cert.not_valid_before_utc<=now<=cert.not_valid_after_utc,"Certificate expired or not active")
    try:
        ku=cert.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        eku=cert.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
        bc=cert.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value
    except x509.ExtensionNotFound:
        raise ValueError("Certificate usage extensions missing") from None
    require(ku.content_commitment and ObjectIdentifier("1.3.6.1.4.1.311.10.3.12") in eku and not bc.ca,"Document-signing certificate required")
    key=cert.public_key()
    require(isinstance(key,rsa.RSAPublicKey) and key.key_size>=2048,"RSA key of at least 2048 bits required")
    return {"profile_ok":True,"trust_chain_verified":False,"revocation_verified":False,
            "submission_enabled":False}

def digest_material(canonical_document,cert):
    """Input must be already canonicalized by a separately verified SDK routine."""
    from cryptography.hazmat.primitives.serialization import Encoding
    require(type(canonical_document) is bytes and 0<len(canonical_document)<=250000,"Canonical document bytes required")
    digest=sha256(canonical_document).digest()
    cert_digest=sha256(cert.public_bytes(Encoding.DER)).digest()
    return {"digest_bytes":digest,"document_digest":b64encode(digest).decode("ascii"),
            "certificate_digest":b64encode(cert_digest).decode("ascii")}

def rsa_primitive(private_key,cert,digest):
    """Low-level PKCS#1 v1.5 prehashed SHA-256 primitive, not a full XAdES signer.
    Only for synthetic/offline interoperability testing until SDK vectors pass.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa,padding,utils
    require(isinstance(private_key,rsa.RSAPrivateKey) and private_key.key_size>=2048,"RSA key required")
    public=cert.public_key()
    require(isinstance(public,rsa.RSAPublicKey) and private_key.public_key().public_numbers()==public.public_numbers(),"Certificate/key mismatch")
    require(type(digest) is bytes and len(digest)==32,"SHA-256 digest required")
    signature=private_key.sign(digest,padding.PKCS1v15(),utils.Prehashed(hashes.SHA256()))
    public.verify(signature,digest,padding.PKCS1v15(),utils.Prehashed(hashes.SHA256()))
    return b64encode(signature).decode("ascii")

class SigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.x509.oid import NameOID,ObjectIdentifier
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import hashes
        cls.now=datetime(2026,11,27,3,tzinfo=timezone.utc)
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Synthetic signer"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME,"Synthetic signer"),
            x509.NameAttribute(NameOID.COUNTRY_NAME,"MY"),
            x509.NameAttribute(ObjectIdentifier("2.5.4.97"),"C1234567890"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER,"202001234567")])
        cls.cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(cls.key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(cls.now-timedelta(days=1)).not_valid_after(cls.now+timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
            .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=True,
                key_encipherment=False,data_encipherment=False,key_agreement=False,
                key_cert_sign=False,crl_sign=False,encipher_only=False,decipher_only=False),True)
            .add_extension(x509.ExtendedKeyUsage([ObjectIdentifier("1.3.6.1.4.1.311.10.3.12")]),False)
            .sign(cls.key,hashes.SHA256()))
    def test_profile(self):
        result=profile(self.cert,"C1234567890","202001234567",self.now)
        self.assertTrue(result["profile_ok"])
        self.assertFalse(result["trust_chain_verified"])
        self.assertFalse(result["submission_enabled"])
    def test_identity(self):
        with self.assertRaises(ValueError):profile(self.cert,"C9876543210","202001234567",self.now)
        with self.assertRaises(ValueError):profile(self.cert,"C1234567890","OTHER",self.now)
    def test_expiry(self):
        with self.assertRaises(ValueError):profile(self.cert,"C1234567890","202001234567",self.now+timedelta(days=2))
    def test_primitive(self):
        from base64 import b64decode
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding,utils
        d=digest_material(b'{"synthetic":true}',self.cert)
        sig=rsa_primitive(self.key,self.cert,d["digest_bytes"])
        self.cert.public_key().verify(b64decode(sig),d["digest_bytes"],padding.PKCS1v15(),utils.Prehashed(hashes.SHA256()))
    def test_wrong_key(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(ValueError):rsa_primitive(wrong,self.cert,b"x"*32)

if __name__=="__main__":
    unittest.main()
