# MYR Invoices — incremental database upgrade

Status: **Phase 1A + Phase 1B staging deployed** (19 November 2026). This is deliberately non-destructive. **Full canonical per-record cutover is NOT complete.**

## What changed

- New `public.invoice_records` table with one row per legacy invoice ID and company, metadata and an invoice JSON snapshot.
- An internal database trigger mirrors `companies.data.invoices` on company creation and each invoice-array change. Deletes are reflected too.
- Existing `companies.data` remains the **authoritative source** for invoice creation/editing while this migration is staged.
- `invoice_records` has Row Level Security. An authenticated company member may SELECT that company's records. Browser users cannot directly INSERT/UPDATE/DELETE invoice mirror rows.
- A company-unique, case-insensitive nonempty invoice-number index prevents duplicates across invoice IDs.
- Server-owned LHDN statuses are not mirrored into invoice JSON: the `lhdn` property is stripped, and authoritative status remains `lhdn_documents`.
- Suspended-company members retain read-only access, not editing access.
- The existing LHDN backend, authentication, company records, invoice PDFs, and source-of-truth writes were not switched.

## How to verify

1. Sign in as the authorized Super Admin, open Demo Lab, create/open a fictional demo workspace, and save a draft.
2. Confirm `public.invoice_records` contains the matching company + invoice ID and document metadata.
3. Try modifying/deleting a draft (not submitted/paid) and confirm the mirror follows on successful cloud save.
4. Verify another tenant cannot read the first tenant's record under their authenticated JWT.
5. Confirm fake demo LHDN statuses are not stored in `invoice_records.invoice_data`.

Automated database tests on 19 Nov passed in rollback-only transactions: read permissions; tenant separation; mirror creation; sanitized official-status JSON; duplicate number enforcement. No test row remained afterward.

## Phase 1B staging — 19 November 2026

- Added four new RLS-protected read-only tables: customer_records, product_records, invoice_line_records and payment_records. With invoice_records, this provides separated indexed data for the five requested business entities.
- A private database trigger mirrors these records as part of the same database transaction when companies.data changes; no independent app writes are permitted to snapshots. Deletes cascade to associated line and payment rows.
- Historical customers/products were backfilled. Existing invoice lines/payments will also backfill when deploying the checked-in migration on another project; the active project had no existing invoices.
- Separate staff tenant memberships continue to enforce database isolation. Non-members see zero records in every new table.
- Invoice Staff and Accountant roles may advance the invoice counter only while creating new invoices. Unauthorized settings-only counter changes are rejected by the server.
- Browser cloud saves now use a **three-way record-ID merge** after an optimistic version conflict: independent invoice/customer/product updates can merge, edits to the same record are rejected with an explicit warning, and edits made during an in-flight reconciliation are retained.
- Automatically suggested invoice numbers can be re-sequenced if two devices created separate drafts with the same suggested number; manually duplicated numbers continue to be rejected. A unique per-company database index is the final safeguard.
- Invoice number changes caused by conflict resolution are written to company audit activity.
- GitHub Actions validates client script syntax and runs concurrency, financial and invoice-safety tests.

**Verified transaction tests:** new customer, product, invoice, line and payment snapshots; fake LHDN status excluded from invoice_records; deleted invoice snapshots cascade correctly; staff counter increments with actual new invoices but not as arbitrary settings; unauthorised tenant returns zero rows. All sample transactions rolled back.

**Important limitation:** customer_records, invoice_line_records and payment_records are **mirrors**, not yet the canonical source. Safe merge protects different record IDs but does not permit two users to edit the very same invoice simultaneously. Full per-record server-side APIs, atomic invoice allocation for all save paths, independent payments/customer writes, browser end-to-end testing with two real accounts, and tested data cutover remain next-stage work.

## Next stage (NOT YET complete)

**Phase 1B completion — canonical per-record writes**: Convert the read-only mirrors into authoritative tenant-safe record APIs with per-record revision checks, atomic server-side invoice-number allocation, independent payment/customer writes and real two-account concurrent-edit tests. Backfill/reconcile all historical data. Only after parity is proven should invoice reads/writes switch away from the `companies.data` blob.

**Phase 1C — final cutover**: Release behind a reversible feature flag, verify reconciliation/backup and multi-device regression, then remove the compatibility mirror. Do not delete `companies.data.invoices` before signed-off migration.

## Production restrictions

GitHub Pages and the public GitHub repository are a test deployment, not suitable for commercial SaaS with private code. Payment gateway, customer transactional email and real LHDN authorization/submission remain pending.
