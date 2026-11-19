# MYR Invoices — safe rollout, recovery and cutover checklist

## Current state (19 Nov 2026)

**Atomic writes enabled**, using `config.js → atomicRecordWrites: true`. Invoice, customer and product Save operations use a tenant-locked database RPC with record revision checks. Payments use a separate idempotent, transaction-locked append RPC. Both update the current `companies.data` source and its normalized tables in the same database transaction.

**Not a final canonical normalized-table cutover.** `companies.data` remains authoritative while normalized tables are synchronized mirrors. Old app functionality that saves company settings, approvals, bulk imports and some deletions still uses compatibility sync. Do not delete the legacy data.

## Quick rollback if there is an issue

1. In `config.js`, change `atomicRecordWrites: true` to `false` and commit.
2. Wait for GitHub Pages deployment to complete and reload the application.
3. Existing invoice/customer/payment data stays in `companies.data`; the legacy save path becomes active without a database restore.
4. Before changing any production data, review the Super Admin Data Integrity page and investigate mismatched counts/values.
5. If a record needs restoration, first export a separate offline database backup; select the correct timestamp/version from the private recovery journal; restore only through a reviewed, transaction-protected admin SQL operation after verifying the target company/version. Do **not** automate overwrites.

## Current backup protections

- `myr_internal.company_snapshots`: one pre-cutover snapshot of existing companies.
- `myr_internal.company_revisions`: records previous company JSON when a company record changes, before the update commits.
- Both are private Supabase tables, not available from the browser. The app's Super Admin Data Integrity page provides counts only.
- GitHub stores migration/code history, **not customer database backups**.
- Database-internal history is **not** protection against catastrophic Supabase/database loss. An independent encrypted, tested offsite export and documented restoration procedure must be arranged before commercial launch.
- Revision history retention/cleanup and independent backup scheduling are not yet configured; monitor database size.

## Test evidence

- Rollback-only SQL tests passed: owner writes, Invoice Staff/Accountant stale edit rejection, customer create/update, invoice numbering reservation, invoice creation, line-item mirroring, payment and its retry, overpayment block and server audit-log insert.
- Browser-side GitHub CI passed: frontend JS validation; financial totals; duplicate and automatic numbering; printable invoice watermark and QR behavior; concurrency merge; invoice safety; atomic Save handler tests.
- Current source-to-mirror parity: zero mismatch across 1 existing company; original data unchanged by rollback-only tests.

## Remaining sign-off requirements

- **Two actual signed-in users in separate browser sessions:** edit different records, edit same record, simultaneous payment, expired session, interrupted network and refresh.
- **Actual PDF print/download:** page break, Chrome/Edge/mobile, tax totals, QR scan, multi-page items, real printer output.
- **Canonical migration:** independent read/write APIs for every remaining workflow including delete, approval, import and adjustments, per-record versioning and reconciliation; then gradual gated switch to normalized tables with verified offline backup.
- **External services:** transactional email provider, MyInvois intermediary authorization and LHDN sandbox/production credentials, subscription billing/payment gateway, commercial hosting and private repository.
- **Security hardening:** public-link RPC review, Auth leaked-password protection, performance/load and penetration testing.

No production LHDN submission, payment charge or email delivery is triggered by the above development changes.
