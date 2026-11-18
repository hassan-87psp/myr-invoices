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
