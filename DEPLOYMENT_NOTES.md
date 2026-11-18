# MYR Invoices — deployment handoff (18 November 2026)

## What is pre-configured
- Supabase project: `nynghaleoaqilewmhbdi` (Singapore; free-tier project).
- Frontend `config.js` uses the **publishable** API key. This is public by design; do not add a service-role/secret key to any public file.
- Demo mode is disabled. Real signup/login now requires a working Supabase schema.
- Initial SQL migration was adjusted: invited members cannot read tenant data before activation, newly created companies start on Starter regardless of client input, admin RPC privileges restricted, expired/closed public links do not expose data.
- LHDN Edge Function now checks `status = active` for company members.

## Steps after GitHub upload
1. Put the contents of this folder in repository root (not a nested `myrinvoice/` folder).
2. Apply `supabase/migrations/20261114000000_myrinvoice_init.sql` to the connected Supabase project, and verify RLS/advisors before inviting anyone.
3. In Supabase Auth, enable email confirmation and set Site URL / redirect URLs to the *actual* HTTPS deployment origin.
4. Deploy `supabase/functions/lhdn/index.ts` as Edge Function `lhdn` with JWT verification **enabled** and add `ALLOWED_ORIGIN` secret for your exact frontend origin.
5. Keep LHDN credentials on server only; sandbox test before enabling production. The LHDN sandbox/production credentials are **not** in this package.
6. Deploy static files `index.html` and `config.js` at site root. Public domain and Vercel/Netlify are not connected by this ZIP.

## Requires additional production work
- Invoice/business data is stored as a large JSON object; per-role write permissions are not isolated at a database field/record level. Not suitable as-is for high-trust multi-tenant production with staff accounts.
- Pricing/subscription payment gateway, transactional emails, LHDN credentials, legal/privacy review, backups and real end-to-end tests remain pending.
- The ZIP can be run locally for a **cloud-connected** login flow only after schema migration, not as a complete deployed production service.
