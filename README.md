> **2026-11-18 update:** This package has been configured for the dedicated MYR Invoices Supabase project. It is not deployed or production-certified. See [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md).

# MYR Invoice — Smart E-Invoicing for Malaysia

Complete package: public website, business app, accountant workspace, Super Admin panel, Supabase database, and the LHDN MyInvois backend function.

## Files in this package

```
myrinvoice/
├── index.html                      ← Poori app (website + business app + accountant + super admin)
├── config.js                       ← MYR Invoices Supabase URL + publishable key preconfigured
├── README.md
└── supabase/
    ├── migrations/20261114000000_myrinvoice_init.sql   ← Database tables + security (RLS)
    └── functions/lhdn/index.ts                         ← LHDN MyInvois secure backend (Edge Function)
```

## Do modes

| Mode | Kab | Data kahan |
|---|---|---|
| **Local demo** | `config.js` khali ho | Sirf usi browser mein (demo/testing ke liye) |
| **Cloud (live)** | `config.js` mein Supabase URL + anon key ho | Supabase database — har device se login |

Local demo chalane ke liye `index.html` browser mein kholein → Start free trial → "Use fictional demo company". Local mode mein pehla registered user Super Admin hota hai (`#/admin`).

---

## Deploy steps (Cloud mode)

### 1. Supabase project
1. https://supabase.com → **New project** → Region: **Southeast Asia (Singapore)**.
2. **Authentication → Providers → Email**: "Confirm email" **ON** rakhein (security ke liye zaroori).
3. **Authentication → URL Configuration**:
   - Site URL: `https://www.myrinvoice.com` (ya aapka Vercel/Netlify link)
   - Redirect URLs mein bhi wahi URL add karein.

### 2. Database
1. Supabase → **SQL Editor** → New query.
2. `supabase/migrations/20261114000000_myrinvoice_init.sql` ka poora content paste karein → **Run**.

### 3. LHDN backend function
**Option A — Dashboard (CLI ke baghair):**
1. Supabase → **Edge Functions** → **Deploy a new function** → naam: `lhdn`.
2. `supabase/functions/lhdn/index.ts` ka code paste karein → Deploy.

**Option B — CLI:**
```bash
npm i -g supabase
supabase login
supabase link --project-ref <your-project-ref>
supabase functions deploy lhdn
```

**Secrets** (Edge Functions → Secrets, ya `supabase secrets set ...`):

| Secret | Value |
|---|---|
| `LHDN_SANDBOX_CLIENT_ID` | MyInvois sandbox Client ID |
| `LHDN_SANDBOX_CLIENT_SECRET` | MyInvois sandbox Client Secret |
| `LHDN_MODE` | `intermediary` (default) ya `taxpayer` |
| `ALLOWED_ORIGIN` | `https://www.myrinvoice.com` |
| `LHDN_PROD_CLIENT_ID` / `LHDN_PROD_CLIENT_SECRET` | Sirf production ke waqt |
| `LHDN_PRODUCTION_ENABLED` | `true` — sirf jab production ready ho |

> ⚠️ Client Secret, `service_role` key aur database password **kabhi** `config.js`, chat ya code mein na daalein.

### 4. config.js
Supabase → **Project Settings → API**:
```js
supabaseUrl: 'https://xxxx.supabase.co',
supabaseAnonKey: 'eyJ...'   // "anon public" key
```

### 5. Hosting
`index.html` + `config.js` dono files Vercel / Netlify / GitHub Pages / cPanel par upload karein. Build ki zaroorat nahi.
- **Netlify**: app.netlify.com/drop par folder drag & drop.
- **Vercel**: New Project → upload.

### 6. Apne aap ko Super Admin banayein
Website par signup + email verify karein, phir SQL Editor mein:
```sql
update public.profiles set is_platform_admin = true where email = 'aapki@email.com';
```
Phir `https://aapki-site/#/admin` kholein.

### 7. LHDN sandbox test
1. MyInvois **sandbox** portal par intermediary system register karein → Client ID/Secret milega.
2. Test company (taxpayer) ko sandbox portal mein MYR Invoice ko **intermediary authorize** karna hoga.
3. App → Settings mein company TIN/BRN/MSIC sahi bharein.
4. App → **Integrations → Test connection** → "Connected to LHDN sandbox".
5. Invoice banayein → Mark ready → **Submit to LHDN** → status Processing → Valid / Invalid.

### 8. Production go-live checklist
- [ ] Sandbox mein invoice, credit note, cancel, invalid → fix → resubmit test ho chuke
- [ ] Production Client ID/Secret secrets mein, `LHDN_PRODUCTION_ENABLED=true`
- [ ] Integrations mein environment **Production** select
- [ ] Supabase backups (Pro plan) ON, custom domain + HTTPS
- [ ] Privacy Policy / Terms lawyer se final

---

## Kya kya included hai

**Public website:** homepage, features, pricing, eligibility checker, ROI calculator, sample invoice, MyInvois Portal comparison, FAQ, privacy/terms, login/signup/password reset.

**Business app:** dashboard, invoice builder (8 document types), Smart Compliance Checker, Invoice Rescue Centre, E-Invoice Centre (cancellation timer, submission log), customers + TIN verify, Customer QR request + buyer mobile form, products, payments + reminders, Bulk Excel/CSV import + Pre-Go-Live Scan, reports, team roles + approval workflow, accountant multi-company workspace, audit log, integrations, billing, settings, customer invoice portal.

**Super Admin (`#/admin`):** overview, businesses (suspend/reactivate, plan change), subscriptions/MRR, LHDN API monitor, users, security & audit. Admin sirf aggregates dekhta hai — invoice ka content nahi, impersonation nahi.

**Security:** company-level RLS, LHDN secrets sirf server par, official LHDN status sirf server likhta hai (browser "Valid" fake nahi kar sakta), append-only audit log, expiring public links.

## Abhi kya baaki hai (honest list)
- **Payment gateway** (FPX/DuitNow/cards) — integration nahi, payments manually record hote hain.
- **Emails** (reminder, daily digest, team invite email) — server email sender lagana baaki. Supabase auth emails (verify/reset) kaam karte hain.
- **Signed documents (v1.1)** — abhi version 1.0 (unsigned) bhejte hain.
- **REST API, webhooks, Shopify, WooCommerce, POS, AI extraction** — "Planned" dikhaye gaye hain, bane nahi.
- **Bahasa Melayu** — abhi sirf English.
- Company ka data ek JSON document mein save hota hai (fast MVP). Do log ek hi waqt edit karein to dusre ko "reloaded" message aata hai. Bade scale se pehle normalized tables par shift karna behtar hai.
- Role permissions: read-only users database level par block hain, aur LHDN submit/cancel roles server par check hote hain; baaki chhoti permissions app level par hain.
