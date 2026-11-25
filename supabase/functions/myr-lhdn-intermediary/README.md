# Central MyInvois intermediary connector — staged connection foundation

Architecture: VPS remains authoritative for customer identity, ownership, company profile and invoice data. Supabase Edge Function holds the service provider's ERP credentials in Secrets. No customer API keys. The official intermediary login uses the taxpayer TIN (or TIN:BRN for an applicable ROB taxpayer) in the onbehalfof header. Credentials should be dedicated to intermediary use; production and sandbox must be distinct.

Required secrets (never put values in Git):
- MYR_LHDN_BRIDGE_SECRET: random 32 bytes, lowercase hex; unique to this integration, protected on VPS.
- MYR_LHDN_PROD_CLIENT_ID / MYR_LHDN_PROD_CLIENT_SECRET
- MYR_LHDN_SANDBOX_CLIENT_ID / MYR_LHDN_SANDBOX_CLIENT_SECRET
- MYR_LHDN_PROD_CONNECTION_CHECK_ENABLED and MYR_LHDN_SANDBOX_CONNECTION_CHECK_ENABLED: remain unset until eligibility/authorization is confirmed in the corresponding environment.

POST with Authorization: Bearer <bridge secret> and JSON. configuration_status accepts environment only; check_connection accepts environment, tenant_id, taxpayer. No browser calls, no CORS, no token or credential returned. The VPS must validate session and active owner membership and derive taxpayer identity from the stored company record. A successful cached login is not proof of current authorization. Fresh authorization validation, explicit permission scope, revocation handling, global distributed rate limiting/cache, owner-facing setup UI, secure VPS routing, and all document operations remain release gates. The in-memory token cache is a foundation, not a distributed production cache. Production submission is intentionally unavailable. Existing legacy function is not modified or used.

Official docs: https://sdk.myinvois.hasil.gov.my/api/08-login-as-intermediary-system/ and https://sdk.myinvois.hasil.gov.my/integration-practices/
