# MYR Invoice — pre-pilot audit (2026-11-28)

**Decision: not ready to submit a real Sandbox invoice yet.** The connection-only connector is separate from the staged dispatch implementation. No production or Sandbox document submission was enabled during this review.

## Directly verified

- GitHub main before this audit: `127ab7c7380c67328cb6fc4c3490c680196d17b5`; PR 6's three CI jobs succeeded, including premium Settings and guided onboarding regression tests.
- Supabase project ACTIVE_HEALTHY, Singapore; deployed central intermediary v12 index.ts and handler.ts exactly match the GitHub main copies. The deployed handler supports configuration, login and Sandbox TIN validation, not document submission. Credentials and provider token validity were not inspected.
- Supabase PostgreSQL catalog: 16 public/private application tables inspected, all RLS-enabled. Three tables without policies have no anon/authenticated CRUD privileges. Public-link RPCs and authenticated SECURITY DEFINER RPCs have advisor warnings requiring review; RLS alone is not proof of full tenant isolation. Leaked-password protection is disabled in Supabase Auth. Two unindexed foreign keys and three unused-index notices are non-blocking performance review items. No schema or permission changes made without compatibility tests.
- Prior VPS evidence: encrypted local backup and timer configured; last operator Sandbox configuration probe returned bridge/credentials/check enabled and zero approved pilots. Neither that evidence nor source tests prove current live health, offsite restore, or actual provider authorization.
- External browser tool could not retrieve the public homepage; the latest release's actual served bytes and login/settings UX need verification on VPS/browser. User screenshots show both earlier and newer layouts, so a successful GitHub merge alone is not a deployment assertion.

## New read-only operator preflight

`python3 -B vps/backend/check_pilot_preflight.py` on the VPS as myradmin, after fetching the current reviewed checkout. It compares approved manifest digests with installed publisher state, served HTML with current webroot, expected UI markers, native auth guards, local encrypted backup checksum and bridge configuration in both environments. It counts matching locally approved Sandbox pilots but does not reveal any company identity, credentials, log contents or customer data. It never logs into LHDN, submits documents, writes the database or changes configuration. A successful check is only a prerequisite for a connection pilot; the report explicitly says actual login, TIN, dispatch and production readiness remain unverified.

Offline: `python3 -B vps/backend/check_pilot_preflight.py --selftest`, also part of GitHub release gate.

## Before requesting real company test

1. Run current VPS preflight; resolve missing/failed releases and prove actual browser login, registration, invoice calculations and settings save using synthetic data. Confirm existing VPS production backend deployment separately; the frontend timer cannot publish backend.
2. Review Supabase legacy RPC roles, security-definer definitions and actual privileges, especially public links and tenant authorization; test with synthetic principals before narrowing grants. Confirm current native auth password and session security independently. Do not disable valid public links blindly.
3. Run complete private LHDN offline suite, disposable database concurrency/restore rehearsal and transport/dispatch candidate tests. Confirm current supported MyInvois document version and validate actual schema. Separate Sandbox-only worker DB, dedicated role, durable one-shot fence, fixed environment, secrets, revocation checks and poll/receipt persistence are still required. See LHDN_DOCUMENT_RELEASE_REVIEW.md. Do not enable submission as part of preflight.
4. Verify encrypted restore and offsite backup independent of the VPS. Finish billing/email live acceptance separately before commercial launch.
5. Only after connection prerequisites are met, register a separate authorized real company; do not overwrite a fictional demo workspace. Obtain genuine MyInvois preproduction intermediary authorization and verify exact tenant/TIN/BRN. Perform login and TIN verification first, without documents. Only after isolated dispatch gates pass, permit a single explicitly approved Sandbox document; poll until official Valid/Invalid, verify UUID and verification URL, then rehearse reconciliation. Never copy Sandbox status into production.

Official SDK: https://sdk.myinvois.hasil.gov.my/api/08-login-as-intermediary-system/ and https://sdk.myinvois.hasil.gov.my/einvoicingapi/02-submit-documents/. HTTP 202 is initial acceptance, not final validation.

## Boundary

No direct VPS shell is available through current connected tools. Local VPS preflight, backend release, isolated database deployment and browser acceptance were not performed. An audit is not a security certification or an assurance that all work is complete. Do not claim that a real-company test is the only remaining task.
