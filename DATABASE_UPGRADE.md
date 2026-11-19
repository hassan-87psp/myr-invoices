# MYR Invoices — incremental database upgrade

Status: **Phase 1A deployed** (19 November 2026). This is deliberately non-destructive.

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

## Next stage (NOT YET complete)

**Phase 1B — canonical per-record writes**: Normalize invoice line items, customers and payments with row-level revision checks; assign invoice numbers atomically on the server. Run two-account concurrent-edit tests and backfill/verify all historical data. Only after parity is proven should invoice reads/writes switch away from the `companies.data` blob.

**Phase 1C — final cutover**: Release behind a reversible feature flag, verify reconciliation/backup and multi-device regression, then remove the compatibility mirror. Do not delete `companies.data.invoices` before signed-off migration.

## Production restrictions

GitHub Pages and the public GitHub repository are a test deployment, not suitable for commercial SaaS with private code. Payment gateway, customer transactional email and real LHDN authorization/submission remain pending.
