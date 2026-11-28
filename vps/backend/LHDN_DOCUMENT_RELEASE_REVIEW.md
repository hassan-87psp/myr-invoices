# LHDN document generation and durable dispatch — review candidate

Staged only. Live release remains connection-only. Do not enable production submission or run the review SQL on the production database.

## Current components

- lhdn_ubl_candidate.py: offline UBL JSON generator for domestic business invoices (01), credit/debit/refund notes (02/03/04) with trusted valid original reference, selected currencies, line discounts/fees and rounding; v1.0, explicit sales/service/no-tax treatment, exact decimal arithmetic and independent total check. No signing or actual provider validation yet.
- lhdn_saved_invoice_candidate.py: offline mapping of persisted ordinary invoice/customer/company snapshots, integer sen reconciliation with existing UI, explicit foreign exchange rate, approval and no-prior-attempt checks. No DB endpoint or actual authorization lookup; adjustment mapping remains disabled.
- lhdn_protocol_candidate.py: byte-level hash, single-document envelope, acceptance and status parsing, verification link, cancellation and retry decisions.
- lhdn_lifecycle_candidate.py: sandbox-only transaction helpers for preparing/reserving an immutable snapshot, uncertain outcomes, acceptance, guarded status synchronization, cancellation planning and polling intervals. No HTTP transport or deployed worker. The caller must enforce transaction commit, trusted response provenance and authorization; imported accounts with disabled native credentials are intentionally excluded until identity review.
- lhdn_readiness_candidate.py: owner-scoped read-only readiness helper; returns only a safe status and byte count, not document content or provider credentials. No public route yet; SQL/ASGI authorization rehearsal remains required.
- lhdn_signing_candidate.py: offline X.509 Malaysian organization profile checks, SHA-256 digest material and RSA primitive verified against its own synthetic public key. Not complete XAdES signing; no CA chain/revocation validation or actual credentials.
- ../lhdn-submission-intents.review.sql: proposed durable tenant-scoped intent storage and database trigger protecting invoice changes/deletion through JSON updates. Not applied; no worker consumes it.

## Private integration rehearsal (not a release)

- `bash vps/check-lhdn-disposable-db.sh` starts an isolated temporary Unix-socket-only PostgreSQL cluster and checks synthetic schema, readiness, intent reservation, snapshot trigger, membership revocation, mock receipts and status transitions. It does not use `app.connect()`, production credentials or real records. Full production-schema compatibility, true concurrent race tests, least-privilege grants and restore tests remain separate.
- `~/myr-venv/bin/python -B vps/backend/lhdn_readiness_route_candidate.py` runs isolated ASGI fixtures with mocked identity and readiness dependencies; not mounted in the live API.
- `~/myr-venv/bin/python -B vps/backend/build_native_auth_candidate.py` followed by `~/myr-venv/bin/python -B vps/backend/build_lhdn_readiness_candidate.py` generates a private UI candidate and checks JavaScript syntax. The readiness route must be mounted on a separate authenticated test API before browser acceptance testing; do not publish the candidate HTML.
- Offline suite at fb08b8e: 41 tests passed on the VPS (including 5 synthetic signing tests), per operator terminal. New integration tests have not been executed yet.

## Latest integration evidence

- At f683eaf, operator VPS output confirmed 65/65 unit/mock/ASGI tests and both disposable database and private UI syntax rehearsals passed. No full production-schema or browser acceptance test has occurred.
- The worker rehearsal remains mock-only. The new `supabase/functions/myr-lhdn-intermediary/sandbox_transport_candidate.ts` implements fixed-host HTTP submit and poll calls for an explicitly granted single v1.0 ordinary invoice. It is **not imported by the existing deployed connector**, and no transport flags or grants have been configured. The caller must bind a committed reservation to the trusted grant and token, enforce distributed rate limits and revocation, and persist poll receipts. Never accept grant fields from the browser. No automatic write retry after HTTP 422 or uncertainty.
- Test the transport with `~/.deno/bin/deno test supabase/functions/myr-lhdn-intermediary/sandbox_transport_candidate_test.ts`. Tests use mocked fetch only. 
- Official SDK confirms HTTP 202 is initial acceptance, not final Valid status; Get Submission should be polled at 3–5 second intervals subject to provider throttling. Existing conservative single-document pilot uses a 250 KB bound below the provider 300 KB maximum.
- Official login and environment references: https://sdk.myinvois.hasil.gov.my/api/08-login-as-intermediary-system/ and https://sdk.myinvois.hasil.gov.my/faq/

## Sandbox dispatch wiring (staged)

- Legacy Supabase proxy `lhdn` retired at deployed version 12, exact old version 11 source archived; central connection-only connector remains active at version 4. No production database migration or invoice submission enabled.
- VPS `lhdn_sandbox_dispatch_candidate.py` now connects a committed isolated sandbox intent to a separate fixed Edge endpoint, rechecks local database identity, owner and revision, and requires an expiring operator grant bound to exact tenant, issuer, code and document SHA-256. No browser/public dispatch route.
- `sandbox_dispatch_bridge_candidate.ts` and its candidate entrypoint require a distinct private bridge secret, explicit sandbox-only release gate, matching exact grant, fresh provider login, and durable one-shot fence. `vps/lhdn-edge-dispatch-fence.review.sql` is NOT applied. No new Edge dispatch function deployed; no secrets or grants configured. A failed or ambiguous write cannot automatically retry.
- Run the consolidated private integration suite to test the new Python/TypeScript fixtures, typecheck the candidate entrypoint, and repeat existing disposable database/UI tests. These additional tests have not yet been run. Before real dispatch: rehearse actual fence grants and concurrency, create a separate sandbox database/least-privilege worker role, verify authorization and real schema, configure sandbox credentials and exact pilot grant, and review isolated deployment. Polling/receipt persistence and reconciliation still require end-to-end worker integration; no production status writes.
- The first real provider submission is blocked on actual authorized sandbox taxpayer and credential setup. A synthetic test pass does not satisfy these gates.

## Required before any submission

The current review code is not an approved release. Database integration tests must use a separate disposable database, including concurrent prepare/edit, duplicate reservation, revocation, rollback, crash recovery and cross-company checks. Do not connect a browser route to any transaction or send request yet. Sandbox-only intent results must not appear as production UUIDs or QR codes.

1. Map the persisted company, buyer and invoice snapshot to the normalized generator contract on the server, using an authenticated owner, company revision and approved invoice. Never accept client-supplied UBL, issuer identity, provider UUID or totals as authoritative. Reconcile against existing UI discount, fee, rounding and payment calculations. Unsupported cases stay blocked.
2. Verify code lists, complete document schema and provider examples against the current MyInvois SDK. Test dates, tax groups and mandatory field combinations in sandbox. Generator now supports line-level discounts/fees and explicit rounding plus selected FX and adjustment references. Persisted mapper only covers ordinary invoices and existing line discounts, not fees/rounding fields or adjustment records. Prepayments, exemptions, self-billing, invoice-level adjustments and special TIN workflows remain excluded. Verify original reference ownership and adjustment eligibility in a server-side transaction before enabling notes.
3. Add a separate v1.1 signer and certificate readiness check based on the official signing instructions. A valid authorized Malaysian digital certificate is required; keep its private key outside browser, source repository, and logs. Never invent a signature or send v1.1 without validating it. Confirm v1.0 remains available before any pilot.
4. Rehearse intent table schema and role privileges on an isolated database. Protect intent bytes, hashes and identifiers; verify encrypted backup/restore and tenant isolation. Before exposing a worker, extend all existing invoice mutation/delete guards to check active intents in the same transaction.
5. Atomically reserve a tenant/company/version-bound intent and commit its dispatching state BEFORE the external call. A crash/timeout/ambiguous response changes it to outcome_unknown, never back to prepared automatically. Reconcile provider results using the saved exact document identity and authorized issuer before any retry. No blind resubmission. Use bounded token renewal, distributed rate limiting and a revocation-aware authorization policy.
6. Persist a verified receipt and synchronize official status, UUID, long ID and validation timestamp with existing lhdn_documents in one transaction. Never set Valid from HTTP 202 alone. Generate QR only from verified valid document link. Sandbox must never update production official document records.
7. Require real sandbox intermediary credentials and authorized taxpayer. End-to-end provider acceptance, status polling, cancellation and adjustment reference verification must pass before any release review.

## Offline tests (no network)

On the VPS run `bash vps/check-lhdn-offline-suite.sh` after updating the checkout. It stops on failure and does not modify the live database, install dependencies or deploy services. The signing dependency check is explicit.

    python -B vps/backend/lhdn_protocol_candidate.py
    python -B vps/backend/lhdn_ubl_candidate.py
    python -B vps/backend/lhdn_saved_invoice_candidate.py
    python -B vps/backend/lhdn_lifecycle_candidate.py
    python -B vps/backend/lhdn_signing_candidate.py  # requires compatible cryptography (>=42); verify dependency before installation
    deno test supabase/functions/myr-lhdn-intermediary/index_test.ts

SDK references:
- https://sdk.myinvois.hasil.gov.my/documents/invoice-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/invoice-v1-1/
- https://sdk.myinvois.hasil.gov.my/signature-creation-json/
- https://sdk.myinvois.hasil.gov.my/signature/
- https://sdk.myinvois.hasil.gov.my/einvoicingapi/06-get-submission/
- https://sdk.myinvois.hasil.gov.my/integration-practices/
- https://sdk.myinvois.hasil.gov.my/faq/
- https://sdk.myinvois.hasil.gov.my/mathematical-mappings/
- https://sdk.myinvois.hasil.gov.my/documents/credit-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/debit-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/refund-v1-0/


## Status polling candidate — 28 November 2026

- `lhdn_sandbox_poll_candidate.py` now stages an operator-only polling adapter: an exact, expiring grant binds tenant, issuer, immutable document hash, invoice code, submission UID and UUID. A committed database reservation and active owner check precede the read; response persistence rechecks the grant and reservation. Only the isolated Sandbox intent table receives verified status changes. An accepted submission is not considered Valid until a matching provider status and verification identifier arrive.
- `lhdn-sandbox-poll.review.sql` adds a durable poll claim, retry deadline and manual-review flag, and refuses other database names. No SQL applied. Actual least-privilege worker and concurrency tests remain necessary.
- `sandbox_poll_bridge_candidate.ts` is a private, fixed preproduction-host, receipt-bound status bridge, with separate secret, disabled-by-default gate and exact expiring grant. No submission method is exposed. A deployment entrypoint is intentionally not provided. Mock tests are included in the existing edge gate.
- The private pilot conservatively waits at least 60 seconds following unavailability, honors longer Retry-After, and blocks on excessive backoff instead of retrying early. Normal pending status uses a five-second minimum. Fresh login per short operator poll is only a pilot design; before scaling, rehearse distributed rate limits and revocation-aware token reuse.
- No external MyInvois request, credentials, schema migration, worker deployment, live acceptance, cancellation or automatic recurring poll was performed. Real provider document identifiers and authorization remain to be verified. Source reference: https://sdk.myinvois.hasil.gov.my/einvoicingapi/06-get-submission/ and https://sdk.myinvois.hasil.gov.my/integration-practices/.


## Isolated preparation and operator handoff — 28 November 2026

- `vps/prepare-lhdn-isolated-sandbox.sh --rehearse` creates a temporary Unix-socket-only PostgreSQL cluster, loads synthetic company/invoice snapshots, exercises the restricted worker role, verifies actual concurrent reservation, mocked dispatch/poll persistence, rejected revocation and ambiguous outcomes, and rehearses logical backup/restore. It deletes the temporary cluster after stopping it. The new GitHub job executes this rehearsal on an isolated CI runner; no production credentials or provider calls.
- `vps/prepare-lhdn-isolated-sandbox.sh --install` creates a **new empty** socket-only, stopped cluster at `~/.local/share/myrinvoice/lhdn-sandbox` (refuses existing directory). It never imports real records, installs a running worker, changes Nginx/systemd, applies migrations to the production database, or sends documents. PostgreSQL trust is limited to a private 0700 operator socket; this separates databases and roles but is not isolation from the VPS OS account itself. Full production-schema compatibility and operator authorization are still required.
- `vps/check-lhdn-pilot-preparation.sh` runs the complete offline/mock tests, the prior disposable DB rehearsal, the new restricted worker/restore rehearsal and the read-only live preflight. Run only after reviewing the merged commit; no root or credential disclosure needed. The two operator commands are preparation/testing, then optional empty cluster installation. They do not publish the backend or deploy provider endpoints.
- Official SDK version policy checked at https://sdk.myinvois.hasil.gov.my/documents/invoice-v1-0/ and https://sdk.myinvois.hasil.gov.my/faq/: v1.0 remains documented for unsigned testing; signed v1.1 is a separate interoperability and valid organization certificate gate. Do not claim v1.1 complete or enabled based on synthetic certificate primitive tests. Reconfirm availability and authorization before actual provider submission.
- A synthetic logical restore is not proof of encrypted production or offsite restoration. The production backup, current live frontend/backend, real Sandbox TIN/BRN/authorization, dispatch fence service, provider submission and polling remain separate release gates.

## Dual connection options

- The approved frontend release adds Easy Connect (existing intermediary flow) and Direct Connect (own ERP credentials). No direct credential form is enabled; the existing intermediary handler remains unchanged. Choosing an option is presentation-only and never marks a company connected or switches its submission environment. The published intermediary identity is still controlled by the existing server policy and may be present in the existing workspace payload when publication is explicitly enabled; the Direct Connect screen itself does not display it.
- `lhdn_direct_candidate.py` implements a Sandbox-only taxpayer OAuth login without an onbehalfof header, bounded TLS transport, per-session in-memory token reuse, expiry renewal and rate-limit backoff, and a separate TIN/BRN lookup. The lookup alone cannot establish that the credentials belong to the selected taxpayer. The candidate deliberately returns issuer_binding_verified=false and submission_enabled=false, even after login and lookup success. No route, credential persistence, service or real provider call is released.
- Before enabling credential entry: implement a verified company/credential binding (actual provider token/identity contract, not an assumed claim), owner-only authenticated and redacted route, encrypted tenant/environment-scoped storage with private key management and backup/restore, distributed rate limiting, revocation and rotation, and review the migration and deployment. Automatic mode switching, expiry reminders and document submission remain separate release gates. Never accept credentials in chat, localStorage or invoice snapshots.
- Official SDK: https://sdk.myinvois.hasil.gov.my/api/07-login-as-taxpayer-system/ and https://sdk.myinvois.hasil.gov.my/einvoicingapi/01-validate-taxpayer-tin/ .

## Direct ERP encrypted vault and connection status candidate

- `lhdn_direct_vault_candidate.py` provides AES-256-GCM encrypted storage with a random 96-bit nonce per write; the authenticated scope includes tenant UUID, environment, TIN, BRN and format. Private owner-only filesystem checks, atomic fsync/rename, lock serialization and optimistic revisions prevent plaintext storage, tampering, cross-tenant ciphertext substitution and stale UI requests. Sandbox only. The encrypted record includes credentials and user-supplied expiry, not access tokens.
- Status is redacted, with pending identity review, expired and disconnected states, 30/7/1-day expiry stages, and explicit false issuer-binding/submission flags. Replacement and disconnect do not clear outstanding provider backoff; a disconnect writes a tombstone, not a revocation at LHDN, and cannot erase old backups. Expiry is conservatively blocked from the indicated Malaysia calendar date. No email schedule or notification delivery is implemented.
- The staged verification helper commits an encrypted claim before calling a supplied authorized adapter, then verifies revision and approval again. Unexpected failures, throttling and interrupted checks require operator review. Success of login and TIN/BRN lookup remains pending issuer binding, never Connected. The approval callback and adapter are test harness inputs, not a production authentication boundary. No web route, server-side key, or real credentials are installed.
- CI tests run with cryptography on the isolated rehearsal runner; the VPS offline suite also tests synthetic vault records. Before enabling live credential entry, review and implement key provisioning, secure backup/recovery/rotation, owner-only server route with CSRF/origin checks and current identity version, distributed per-client rate limiting, actual provider issuer proof, and verified credential expiry/rotation workflow. Do not expose the vault or token via a browser payload. Official SDK documents taxpayer information in access tokens but does not specify a verified claim mapping in the login reference: https://sdk.myinvois.hasil.gov.my/api/07-login-as-taxpayer-system/ . The general TIN lookup does not establish credential ownership.
