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

## Phase 1C staging — 19 November 2026

- Added a private, durable invoice-number reservation table with one reservation per company/invoice ID and a case-insensitive unique invoice-number index.
- Added authenticated `reserve_invoice_number` RPC. It takes a transaction-level row lock on the company, verifies the signed-in user's active Owner/Admin/Accountant/Invoice Staff membership, checks existing invoices/reservations and assigns the next unique number. Repeating the same invoice ID returns the same reservation.
- Added database trigger to reject invoice saves that attempt to claim another invoice's reserved number. Disabled anonymous browser access to both the reservation table and the RPC.
- Connected the invoice editor's new automatic-number flow to this RPC. The client reserves only during Save, not during preview. A failure does not insert the new invoice. Manually entered custom numbers still use existing validation and database uniqueness; bulk import/other document paths do not yet use this RPC.
- Created a protected internal `company_snapshots` table and captured a pre-cutover company-data snapshot. This is a **same-database safety snapshot**, not an offsite backup or automatic restoration service. Snapshots carry a 30-day expiry timestamp; deletion scheduling is not implemented.
- Created an internal exact JSON `mirror_parity` view comparing customers, products, invoices, line items and payments between existing company data and normalized tables. Official LHDN statuses are excluded from invoice snapshots.
- Added restricted `admin_mirror_parity` aggregate RPC and a Super Admin **Data Integrity** page (`#/admin/integrity`) showing source/mirror counts, match status and a refresh action. Platform admins see counts only, never invoice contents.
- Added `tests/numbering.test.cjs` to the GitHub Actions suite to verify the new-invoice save path uses the server number, does not mutate data after a failed reservation, and respects manually entered numbers.

**Verified without affecting existing records:** SQL rollback tests showed idempotent INV-1001 allocation, next unique INV-1002, nonmember access denied, another invoice cannot reuse a reserved number, and all five source/mirror groups exactly match in a simulated invoice/customer/payment transaction. Existing live business data has 1 company, 1 customer and no invoices; current parity reports 5/5 matching record groups.

**Important limitations:** The existing `companies.data` JSON remains authoritative. This is **not the completed canonical database cutover**. The new number reservation is transactional, but creating/saving an invoice is still a subsequent database operation, so uncommitted reservations may leave harmless number gaps. Real browser PDF printing, two-account end-to-end testing, per-record invoice/payment write APIs, independent offsite backups, automatic snapshot retention cleanup and a reversible production cutover feature flag still need implementation and sign-off.

## Next stage (NOT YET complete)

**Phase 1B completion — canonical per-record writes**: Convert the read-only mirrors into authoritative tenant-safe record APIs with per-record revision checks, atomic server-side invoice-number allocation, independent payment/customer writes and real two-account concurrent-edit tests. Backfill/reconcile all historical data. Only after parity is proven should invoice reads/writes switch away from the `companies.data` blob.

**Phase 1C — final cutover**: Release behind a reversible feature flag, verify reconciliation/backup and multi-device regression, then remove the compatibility mirror. Do not delete `companies.data.invoices` before signed-off migration.

## Production restrictions

GitHub Pages and the public GitHub repository are a test deployment, not suitable for commercial SaaS with private code. Payment gateway, customer transactional email and real LHDN authorization/submission remain pending.

## 19 November 2026 — staged transactional record writes enabled

- **Enabled** `atomicRecordWrites: true` in `config.js`. Owner/Admin/Accountant/Invoice Staff invoice, customer and product create/edit operations now call `atomic_save_record`, using company row locks, tenant membership authorization and per-record expected snapshots. Customer archiving also uses the new RPC.
- Payment recording calls `atomic_add_payment` with amount/date checks, server-side outstanding balance enforcement, and stable idempotent payment IDs. Repeated requests with changed client timestamps do not duplicate a payment.
- Existing `companies.data` is updated transactionally and its protected invoice/customer/product/line/payment mirrors update automatically; **canonical normalized-only cutover remains OFF**.
- Database writes capture private previous company revisions. Atomic record and payment actions also insert RLS-protected, append-only `audit_logs` entries.
- Data Integrity admin view reports private revision counts and clearly labels offsite backup as unverified.
- Source code, deployment and automated tests verified; transactional SQL tests covered multi-role stale edit conflicts, wrong-role access, overpayment, payment idempotence, audit events and mirror parity.
- The reversible feature toggle, backup limits and remaining E2E/cutover requirements are documented in `RECOVERY_AND_CUTOVER.md`.
- Limitation: the browser still uses compatibility JSON for other workflows (approval, import, some deletes/settings). Actual two-user browser testing, PDF printing and a full restore from an **independent** offsite backup remain unverified.
