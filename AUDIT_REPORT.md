# MYR Invoices — deployment and feature audit
Date: 18 November 2026

## Infrastructure status
- Frontend repository: https://github.com/hassan-87psp/myr-invoices (public).
- GitHub Pages configured by repository owner to deploy from main / (root).
- Expected Pages URL: https://hassan-87psp.github.io/myr-invoices/
- **Live HTTP status could not be independently confirmed** from audit environment. Confirm Pages status in GitHub Settings → Pages.
- Supabase project: nynghaleoaqilewmhbdi (Singapore), ACTIVE_HEALTHY.
- Database: 7 tables; Row Level Security enabled on all 7.
- LHDN Edge Function: ACTIVE, JWT verification enabled. LHDN credentials are not configured.
- Database user/company counts at audit: 0 registered users, 0 companies.

## Tests executed
- Browser smoke test: landing, signup, onboarding and 18 application/admin routes loaded without uncaught JavaScript exceptions in a controlled browser fixture.
- Draft invoice creation/save passed in local demo.
- Mock-cloud test: sign-up, company onboarding, company row insertion, invoice draft save, versioned Supabase update succeeded without uncaught JavaScript errors.
- Mobile 390 px viewport: dashboard, invoices, invoice editor, customers, QR requests, products, payments, import, reports, team, integrations, billing, settings, help and admin — no horizontal page overflow after CSS fix.
- JavaScript syntax parsed successfully (inline scripts).
- Database permission and security advisor checks run.

## Fixes applied
1. Prevent silent loss of unsaved cloud changes on optimistic-lock conflict.
2. Block logout when a cloud save is still pending or has failed.
3. Remember the selected company across browser refreshes.
4. Fix dashboard/payments page horizontal overflow on phones.
5. Start cloud accounts on the Starter plan in onboarding, matching server enforcement.
6. RLS: company readers must be active members or platform admins; historical creator alone no longer grants read access.
7. Restrict company profile/settings changes by staff-level roles at database trigger level.
8. Buyer QR/invoice submissions cannot proceed when the company is suspended.
9. GitHub validation workflow added; GitHub Pages publishing remains configured through main / (root).

## Not yet verified / production prerequisites
- Supabase Authentication → URL Configuration: set Site URL to https://hassan-87psp.github.io/myr-invoices/ and allow redirects to the deployed path.
- Test registration, email confirmation, login, password reset and admin access with a real verified account.
- Promote the intended real account to platform admin using an authorized Supabase SQL update; none has been registered yet.
- Add LHDN sandbox credentials via Supabase Edge Function secrets and confirm taxpayer/intermediary authorization. Production submission is disabled.
- Test actual MyInvois accepted, invalid, cancellation and retry flows; do not imply LHDN certification.
- Payment gateway checkout, automatic billing and transactional/reminder email delivery are not fully implemented; UI has future/planned sections.
- Test CSV/Excel import against real samples and PDF print on actual browsers.
- Perform independent authenticated multi-tenant/RLS end-to-end tests using several test accounts before commercial release.
- GitHub Pages is **not** intended/permitted by GitHub for running a commercial SaaS website; migrate production hosting before monetization.

## Operational notes
- Public repository means HTML, frontend JS and SQL/backend function *source* are visible. Only server-held credentials are secret.
- Existing PipSePaisa repository and Supabase project were left unchanged.

## 18 November 2026 — Super Admin / Demo Lab follow-up
- Enabled platform admin access for the existing authorized owner account. The app's standard company owner role remains intact.
- Rechecked Super Admin routes: Overview, Businesses, Subscriptions, LHDN API Monitor, Users, Security & Audit; added Demo Lab as an additional tab.
- Added admin-only fictional demo workspace creation/reopening with existing sample customers, products, seven invoices and payment examples. It is not provisioned automatically: the admin clicks Create fictional demo workspace.
- Added prominent DEMO LAB banner, disabled browser-level LHDN submission, connection configuration/health tests and public link synchronization for demo tenants.
- Deployed LHDN Supabase Edge Function version 2. It rejects all live LHDN API operations for a company whose stored data has demo=true, independently of frontend restrictions.
- Added sample accepted/rejected LHDN response previews to Demo Lab. These are visual mock responses only; no real records get an official Valid/Invalid status.
- Updated admin_companies SQL function to exclude fictional demo tenants from platform business and list-price recurring-revenue aggregates. Included corresponding SQL migration in repository.
- Hardened Super Admin data loader: errors from all four data sources are now surfaced rather than silently ignored.
- Database role tests: authorized platform admin can read company/user/monitor aggregates; synthetic unauthorised account is rejected; transaction-scoped demo insert is excluded from admin aggregate and rolled back.
- Inline JavaScript parsed without syntax errors after edits. GitHub commits made to main; independent external HTTP check of the GitHub Pages release was not possible from this environment.
- Still pending: real browser click-through, full demo invoice edit/print/payment end-to-end, SMTP delivery for business notifications, actual authorized LHDN sandbox transaction, payment gateway and independent production security review.

## 19 November 2026 — Phase 1 financial/data integrity pass

### Improvements deployed to source
- Dashboard, Payments and Reports aggregate foreign-currency invoices into MYR-equivalent sen using each document's own recorded exchange rate. A warning identifies foreign-currency records missing an exchange rate; these are not silently treated as MYR.
- Dashboard's invoice-vs-collection history, overdue and outstanding KPIs were updated to use matching MYR units.
- Invoice save, approval and mark-ready confirmation now waits for the Supabase cloud save to return success. Payment recording also confirms cloud save, and locks against double click during the operation.
- Unsaved cloud changes are tracked explicitly. A retry control and before-unload confirmation help prevent reloading and losing pending edits. Concurrent changes arriving during an in-flight sync are detected and queued again.
- Payment entry validates numeric positive two-decimal amounts, no overpayment, date not in the future, role access and cancellation status.
- Suspended tenants operate in read-only mode in the UI; the cloud save layer now rejects unsaved changes for suspended accounts rather than silently skipping them. Server/database restrictions continue to apply.
- The manual payment reminder action now says "Prepare email". It only opens an email draft, never logs or claims delivery. Automatic reminder preferences are explicitly labeled as not yet implemented.
- GitHub Actions validates frontend JavaScript syntax and executes tests/financial.test.cjs for totals, FX conversion, date/amount checks and suspended role access.

### Verification and limitations
- Isolated financial/payment regression checks performed against extracted live frontend functions passed.
- Repository validation workflow succeeded on 19 November 2026 (runs listed in GitHub Actions). Each future push reruns the suite; check most recent Actions run for final status.
- No real payment gateway, mail transport or real MyInvois submission was invoked.
- Full browser end-to-end run (create/edit/print/payment across real user sessions), concurrency under several actual users, normalized per-record database permissions, formal tax/FX treatment, security penetration testing and commercial hosting remain pending.

## 19 November 2026 — Database upgrade (Phase 1A) and invoice safety

- Created `public.invoice_records`, a read-only RLS-protected per-invoice mirror synchronized automatically from the existing `companies.data.invoices` array using an internal trigger. Source-of-truth invoice writes remain unchanged during safe migration.
- Backfilled pre-existing JSON invoice records without deleting or editing the source. Current production data initially has one company and zero invoice records.
- Applied per-company, case-insensitive invoice-number uniqueness and allowed suspended tenants to read but not modify their invoice snapshots.
- Mirror strips the JSON `lhdn` sub-object to avoid presenting client-supplied statuses as official LHDN results. Official records remain in `lhdn_documents`.
- Hardened invoice editing against decreasing totals below recorded payments and against changing locked official/submitted documents.
- Blocked deleting paid or previously submitted/attempted e-Invoices even when calling the handler directly; successful deletes now require confirmed cloud persistence.
- Disabled demo public-sharing link generation to match the earlier server-side public-link restriction.
- Added `tests/invoice-safety.test.cjs` and GitHub validation workflow runs both finance and invoice integrity regression tests.
- Database verification passed: authenticated tenant read isolation, owner invoice mirror creation within a rolled-back transaction, no fake official status copied, unique number index case-insensitive collision check, and authenticated direct write privileges denied.
- All transactional probes rolled back. Existing company/customer data retained.
- **Not yet complete:** canonical per-invoice write migration, multi-user true row-level editing, data normalization for customers/payments/line items, actual browser PDF test, and cross-user concurrency.
- Full migration rationale and next stages: `DATABASE_UPGRADE.md`.

## 19 November 2026 — Phase 1B normalized records and multi-user merge
- Added customer_records, product_records, invoice_line_records and payment_records with RLS, member-only SELECT and no direct browser write grants.
- Internal SQL trigger mirrors company JSON changes transactionally into normalized read-only tables. Company JSON remains the source of truth and existing data was not deleted.
- Added concurrency.js with three-way, record-ID-based merging on company-version conflicts. Different invoice/customer edits can merge; concurrent same-record edits are refused instead of silently overwritten.
- Added best-effort automatic re-sequencing for concurrent default invoice number collisions. Manually duplicated numbers remain forbidden; DB invoice number unique index is the final safeguard.
- Invoice Staff/Accountant may increment nextNo only when adding invoice records; supplier and account settings stay protected. SQL tests confirmed staff create permitted and counter-only settings update denied.
- Rollback-only database tests confirmed customer/product/invoice/line/payment mirroring, deletion propagation, isolation of non-member accounts and prevention of forged LHDN status in invoice snapshots.
- GitHub CI runs frontend validation plus financial, invoice-safety and concurrency regression tests.
- Still pending: canonical per-record write APIs, fully atomic server-side number allocation, two real-user browser E2E/concurrency testing, payment writes independent of invoice data, and complete verified cutover.
- Supabase advisory still warns about intentional public-link SECURITY DEFINER functions and leaked-password protection; assess before commercial launch.

## 19 November 2026 — Phase 1C atomic invoice numbering and integrity audit
- Applied database migration for invoice_number_reservations, indexed unique numbers and an authenticated, role-checked reserve_invoice_number RPC. A company row-level lock serializes reservations and the same invoice ID returns its original allocation.
- Added server trigger that refuses a different invoice ID claiming an already reserved number. Anonymous execution/table access is not granted.
- Connected the ordinary new-invoice editor Save action to the new RPC; failures leave the invoice unsaved. This flow uses the reservation only for automatically suggested numbers (manual numbers, imports and other paths remain subject to existing constraints).
- Added private, RLS-blocked pre-cutover company snapshots within Supabase. One existing company has one snapshot. These are same-database copies, not independent backups or a tested restoration workflow.
- Added internal exact JSON parity checks for customers, products, invoices, invoice lines and payments. Created Super Admin-only admin_mirror_parity RPC and Data Integrity page at #/admin/integrity (aggregate counts only).
- Verified idempotent first/second number reservation (INV-1001, INV-1002), denied unrelated authenticated users, denied a different invoice taking a reserved number, and rollback-only new invoice/customer/item/payment mirror parity (all 5 matches).
- After all rollback tests: one company, one safety snapshot, zero persisted reservations and zero mirror mismatches. Existing users, companies and invoice data unchanged.
- Added tests/numbering.test.cjs and tests/pdf-markup.test.cjs to CI. Print markup tests cover draft watermark, sample watermark, totals, QR gating and HTML-escaping including logo attributes; they are not a real physical print/PDF browser test.
- GitHub static validation and Pages publication latest workflows succeeded.
- Supabase advisory still lists intentionally restricted no-policy tables, protected SECURITY DEFINER RPCs, and Auth leaked-password protection warning. Review Auth password security and public buyer-link access before commercial launch.
- Phase 1C canonical database cutover deliberately remains OFF: individual invoice/customer/payment writes still use companies.data JSON and synced mirrors. Full per-record canonical writes, real two-account browser tests, offsite backup/restore, bulk-import number allocation and formal production sign-off remain pending.

## 19 November 2026 — Transactional per-record rollout

- Added and enabled guarded Supabase record-save RPC for invoices/customers/products and idempotent per-invoice payment RPC. Every save locks the tenant, checks allowed roles, validates expected versions where relevant, and updates `companies.data` plus protected mirrors in one transaction.
- Added automatic payment amount and overpayment checks on the server and rejected stale customer updates. Simulated Invoice Staff/Accountant edits of one record reject stale overwrites.
- Added private per-change company revision journal with recovery status counts. Pre-cutover snapshot still exists. All test changes rolled back, leaving existing data unchanged.
- Added permanent append-only database audit entries for atomic records and payments; rollback-only SQL tests recorded exactly three expected audit actions.
- GitHub tests include atomic invoice/payment Save handlers, frontend syntax, financial calculations, invoice protection, numbering, HTML print markup and concurrency merges. GitHub Pages static publishing succeeded after the feature flag was enabled.
- **Still not production sign-off:** normalized tables are mirrors, not canonical; two actual browser sessions, actual PDF print, independent encrypted offsite backup/restore, remaining workflow cutover, external transactional email/MyInvois gateway/billing and commercial hosting remain pending.
