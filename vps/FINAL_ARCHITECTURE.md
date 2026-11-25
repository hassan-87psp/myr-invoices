# Final MYR Invoice hosting architecture (revised)

## VPS owns all application state and authentication
- HTTPS website, backend, PostgreSQL business records, subscription state and audit logs.
- Native signup, email verification, password reset, Argon2id password hashes, expiring revocable native sessions, role and tenant authorization.
- Verification/reset tokens generated and consumed on VPS; store only token digests. Supabase must not be the identity or authorization authority after cutover.
- Existing Supabase user IDs, verified email addresses and company membership mappings are retained. No passwords or password hashes were imported. Existing users require a secure one-time activation/reset flow; do not automatically enable imported disabled accounts or grant admin access.
- Existing staging admin accounts must be reviewed independently before real admin activation.

## Supabase integration boundary
- Transactional email transport via authenticated server-to-server Edge Function, with custom branded email templates.
- LHDN/MyInvois and payment integrations via server-to-server Edge Functions; secrets remain server-side. The VPS authorizes requests, owns canonical business and subscription records, and verifies and reconciles external results.
- No browser access to Supabase Auth, direct business database, or service credentials after cutover.
- No destructive removal of old Supabase business data until rollback and retention are approved.

## Release gates
1. Native auth HTTP endpoints, account activation, rate limits, secure cookie/session handling and native UI.
2. Verified email delivery, single-use account links, and real browser tests for signup, reset, login, logout and existing account activation.
3. Complete native business workflows, team permissions, external API integration and independent backup.
4. Fresh source freeze and reconciliation. Switch frontend and backend atomically; old Supabase identity path stays in use until this gate is passed.
5. Test live native auth and invoice persistence; rollback plan must preserve any new VPS records.

Current private candidate remains read-only and uses Supabase Auth until replacement is verified. Do not open the production write gate or expose the candidate as a production service.
