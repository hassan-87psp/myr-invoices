# Native migration checklist — staging only

The current application uses Supabase Auth, six direct data tables, twelve RPCs and an LHDN Edge Function. The new native schema is a foundation, not a drop-in replacement.

| Source | Destination / action |
|---|---|
| auth.users + profiles | myr_native.users, preserve UUIDs, verification state and admin status; imported accounts disabled until reviewed; require a secure activation/reset workflow |
| companies | preserve UUID, creator, plan, version, timestamps and complete JSON data |
| company_members | preserve roles and membership status |
| lhdn_documents / lhdn_events | preserve authoritative records, no new submission |
| public_links | preserve privately; reopen only after expiry and permission review |
| audit_logs / revision history | preserve source history and reconcile coverage |
| normalized mirrors | reconcile against company JSON; do not assume all tables are migrated |
| files and external services | inventory storage, mail settings, LHDN credentials and dependencies separately |

Before import: independent encrypted backup, counts and integrity checks, review data handling and ownership, implement missing API operations. Never commit database exports, credentials or customer records to GitHub. Export/import tooling and activation are pending. Do not change production DNS or disconnect Supabase until full end-to-end tests and rollback are verified.
