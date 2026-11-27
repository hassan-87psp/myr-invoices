# LHDN document generation and durable dispatch — review candidate

Staged only. Live release remains connection-only. Do not enable production submission or run the review SQL on the production database.

## Current components

- lhdn_ubl_candidate.py: offline UBL JSON generator for domestic business invoices (01), credit/debit/refund notes (02/03/04) with trusted valid original reference, selected currencies, line discounts/fees and rounding; v1.0, explicit sales/service/no-tax treatment, exact decimal arithmetic and independent total check. No signing or actual provider validation yet.
- lhdn_saved_invoice_candidate.py: offline mapping of persisted ordinary invoice/customer/company snapshots, integer sen reconciliation with existing UI, explicit foreign exchange rate, approval and no-prior-attempt checks. No DB endpoint or actual authorization lookup; adjustment mapping remains disabled.
- lhdn_protocol_candidate.py: byte-level hash, single-document envelope, acceptance and status parsing, verification link, cancellation and retry decisions.
- ../lhdn-submission-intents.review.sql: proposed durable tenant-scoped intent storage; not applied, no worker consumes it.

## Required before any submission

1. Map the persisted company, buyer and invoice snapshot to the normalized generator contract on the server, using an authenticated owner, company revision and approved invoice. Never accept client-supplied UBL, issuer identity, provider UUID or totals as authoritative. Reconcile against existing UI discount, fee, rounding and payment calculations. Unsupported cases stay blocked.
2. Verify code lists, complete document schema and provider examples against the current MyInvois SDK. Test dates, tax groups and mandatory field combinations in sandbox. Generator now supports line-level discounts/fees and explicit rounding plus selected FX and adjustment references. Persisted mapper only covers ordinary invoices and existing line discounts, not fees/rounding fields or adjustment records. Prepayments, exemptions, self-billing, invoice-level adjustments and special TIN workflows remain excluded. Verify original reference ownership and adjustment eligibility in a server-side transaction before enabling notes.
3. Add a separate v1.1 signer and certificate readiness check based on the official signing instructions. A valid authorized Malaysian digital certificate is required; keep its private key outside browser, source repository, and logs. Never invent a signature or send v1.1 without validating it. Confirm v1.0 remains available before any pilot.
4. Rehearse intent table schema and role privileges on an isolated database. Protect intent bytes, hashes and identifiers; verify encrypted backup/restore and tenant isolation. Before exposing a worker, extend all existing invoice mutation/delete guards to check active intents in the same transaction.
5. Atomically reserve a tenant/company/version-bound intent and commit its dispatching state BEFORE the external call. A crash/timeout/ambiguous response changes it to outcome_unknown, never back to prepared automatically. Reconcile provider results using the saved exact document identity and authorized issuer before any retry. No blind resubmission. Use bounded token renewal, distributed rate limiting and a revocation-aware authorization policy.
6. Persist a verified receipt and synchronize official status, UUID, long ID and validation timestamp with existing lhdn_documents in one transaction. Never set Valid from HTTP 202 alone. Generate QR only from verified valid document link. Sandbox must never update production official document records.
7. Require real sandbox intermediary credentials and authorized taxpayer. End-to-end provider acceptance, status polling, cancellation and adjustment reference verification must pass before any release review.

## Offline tests (no network)

    python -B vps/backend/lhdn_protocol_candidate.py
    python -B vps/backend/lhdn_ubl_candidate.py
    python -B vps/backend/lhdn_saved_invoice_candidate.py
    deno test supabase/functions/myr-lhdn-intermediary/index_test.ts

SDK references:
- https://sdk.myinvois.hasil.gov.my/documents/invoice-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/invoice-v1-1/
- https://sdk.myinvois.hasil.gov.my/signature-creation-json/
- https://sdk.myinvois.hasil.gov.my/faq/
- https://sdk.myinvois.hasil.gov.my/mathematical-mappings/
- https://sdk.myinvois.hasil.gov.my/documents/credit-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/debit-v1-0/
- https://sdk.myinvois.hasil.gov.my/documents/refund-v1-0/
