"""Offline selection rules; never mutates active provider routing.

A customer's preferred setup method is separate from the active verified
submission route. No automatic fallback or direct production activation.
"""
import unittest

def selection(preferred,active,direct_status,central_verified,pending_documents):
    if preferred not in ("easy","direct") or active not in (None,"easy","direct"):
        raise ValueError("Invalid connection method")
    if type(central_verified) is not bool or type(pending_documents) is not bool:
        raise ValueError("Invalid server state")
    if not isinstance(direct_status,dict):
        raise ValueError("Invalid direct status")
    # These are safe UI decisions only. Even an existing route needs its
    # independent server authorization checked at every submission.
    if preferred=="direct":
        reason="direct_release_required"
        if direct_status.get("status")=="expired":reason="renew_credentials"
        elif direct_status.get("status")=="pending_identity_review":reason="issuer_review_required"
        return {"preferred":preferred,"active_unchanged":active,"switch_allowed":False,"reason":reason}
    if pending_documents:
        reason="reconcile_pending_documents"
    elif not central_verified:
        reason="authorize_easy_connect"
    else:
        reason="review_explicit_switch"
    return {"preferred":preferred,"active_unchanged":active,"switch_allowed":False,"reason":reason}

class Tests(unittest.TestCase):
    def test_direct_never_routes(self):
        for status in ({},{"status":"pending_identity_review"},{"status":"expired"},{"issuer_binding_verified":True,"submission_enabled":True}):
            result=selection("direct","easy",status,True,False)
            self.assertFalse(result["switch_allowed"])
            self.assertEqual(result["active_unchanged"],"easy")
    def test_no_silent_fallback(self):
        self.assertEqual(selection("easy","direct",{},True,True)["reason"],"reconcile_pending_documents")
        self.assertEqual(selection("easy",None,{},False,False)["reason"],"authorize_easy_connect")
    def test_renewal(self):
        self.assertEqual(selection("direct",None,{"status":"expired"},False,False)["reason"],"renew_credentials")
if __name__=="__main__":unittest.main()
