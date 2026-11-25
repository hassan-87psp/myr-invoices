import unittest
from unittest.mock import patch
import business_lhdn as L
class ConnectionTest(unittest.TestCase):
    def test_status(self):
        with patch.object(L,"bridge",return_value=(200,{"ok":True,"configured":True,"connection_check_enabled":False})):
            d=L.configuration_status()
            self.assertTrue(d["credentials_configured"])
            self.assertTrue(d["bridge_reachable"])
            self.assertFalse(d["provider_login_verified"])
            self.assertFalse(d["submission_enabled"])
    def test_unreviewed(self):
        with patch.object(L,"local_config",return_value={}),patch.object(L,"bridge") as bridge:
            self.assertEqual(L.check_connection("tenant","C1234567890","123456789012")["status"],"review_required")
            bridge.assert_not_called()
    def test_exact_binding(self):
        config={"approved_pilots":{"tenant":{"environment":"production","tin":"C1234567890","brn":"123456789012","identity_type":"TIN"}}}
        with patch.object(L,"local_config",return_value=config):
            self.assertEqual(L.approved_target("tenant","C1234567890","123456789012","production"),"C1234567890")
            self.assertIsNone(L.approved_target("other","C1234567890","123456789012","production"))
            self.assertIsNone(L.approved_target("tenant","C1234567891","123456789012","production"))
            self.assertIsNone(L.approved_target("tenant","C1234567890","123456789012","sandbox"))
    def test_cached(self):
        with patch.object(L,"approved_target",return_value="C1234567890"),patch.object(L,"claim_slot",return_value=True),patch.object(L,"bridge",return_value=(200,{"ok":True,"verification":"cached","expires_in":300})):
            self.assertEqual(L.check_connection("tenant","C1234567890","123456789012")["status"],"cached_login")
    def test_private(self):
        with patch.object(L,"local_config",return_value={"name":"Private","tin":"C1234567890","brn":"123456789012"}):
            self.assertIsNone(L.public_identity())
if __name__=="__main__":unittest.main()
