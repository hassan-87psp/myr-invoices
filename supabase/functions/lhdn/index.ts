// =====================================================================
// MYR Invoice — LHDN MyInvois secure proxy (Supabase Edge Function)
// - Holds LHDN Client ID/Secret server-side (never in the browser)
// - Logs in as intermediary on behalf of the company's TIN
// - Checks the signed-in user's membership + role for the company
// - Forwards only allow-listed MyInvois API calls
// - Writes OFFICIAL results to public.lhdn_documents (service role)
// Deploy:  supabase functions deploy lhdn
// Secrets: supabase secrets set LHDN_SANDBOX_CLIENT_ID=... LHDN_SANDBOX_CLIENT_SECRET=...
// =====================================================================
import { createClient } from "npm:@supabase/supabase-js@2";

const ORIGIN = Deno.env.get("ALLOWED_ORIGIN") ?? "https://hassan-87psp.github.io";
const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-myr-environment, x-myr-onbehalfof, x-myr-company, x-myr-invoice",
  "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
  "Access-Control-Expose-Headers": "Retry-After",
};
const BASES: Record<string, string> = {
  sandbox: Deno.env.get("LHDN_SANDBOX_BASE") ?? "https://preprod-api.myinvois.hasil.gov.my",
  production: Deno.env.get("LHDN_PROD_BASE") ?? "https://api.myinvois.hasil.gov.my",
};
const MODE = (Deno.env.get("LHDN_MODE") ?? "intermediary").toLowerCase(); // "intermediary" | "taxpayer"

const SUBMIT = ["Owner", "Admin", "Accountant", "Approver"];
const CANCEL = ["Owner", "Admin", "Approver"];
const ANY = ["Owner", "Admin", "Accountant", "Invoice Staff", "Approver", "Read-Only"];
const ROUTES: { m: string; re: RegExp; roles: string[]; op: string }[] = [
  { m: "POST", re: /^\/api\/v1\.0\/documentsubmissions\/?$/, roles: SUBMIT, op: "submit" },
  { m: "GET", re: /^\/api\/v1\.0\/documentsubmissions\/[\w-]+$/, roles: ANY, op: "status" },
  { m: "GET", re: /^\/api\/v1\.0\/documents\/[\w-]+\/details$/, roles: ANY, op: "details" },
  { m: "PUT", re: /^\/api\/v1\.0\/documents\/state\/[\w-]+\/state$/, roles: CANCEL, op: "cancel" },
  { m: "GET", re: /^\/api\/v1\.0\/taxpayer\/validate\/[\w-]+$/, roles: ANY, op: "tin" },
];

const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false },
});

class HttpErr extends Error {
  constructor(public status: number, message: string, public retryAfter?: string | null) { super(message); }
}
const json = (body: unknown, status = 200, extra: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json", ...extra } });
const errBody = (message: string) => ({ error: { message } });

// ---------- Token cache (per environment + taxpayer TIN) ----------
const tokens = new Map<string, { t: string; exp: number }>();
function creds(env: string) {
  const p = env === "production" ? "LHDN_PROD_" : "LHDN_SANDBOX_";
  return { id: Deno.env.get(p + "CLIENT_ID"), secret: Deno.env.get(p + "CLIENT_SECRET") };
}
async function getToken(env: string, tin: string, force = false): Promise<string> {
  const key = env + "|" + tin;
  const c = tokens.get(key);
  if (!force && c && c.exp > Date.now()) return c.t;
  const { id, secret } = creds(env);
  if (!id || !secret) throw new HttpErr(503, `LHDN ${env} credentials are not configured on the server`);
  const headers: Record<string, string> = { "Content-Type": "application/x-www-form-urlencoded" };
  if (MODE === "intermediary") headers["onbehalfof"] = tin;
  const r = await fetch(BASES[env] + "/connect/token", {
    method: "POST",
    headers,
    body: new URLSearchParams({ client_id: id, client_secret: secret, grant_type: "client_credentials", scope: "InvoicingAPI" }),
  });
  const d = await r.json().catch(() => ({}));
  if (r.status === 429) throw new HttpErr(429, "LHDN login rate limited", r.headers.get("Retry-After"));
  if (!r.ok || !d.access_token) {
    throw new HttpErr(r.status >= 500 ? 502 : 403,
      d.error_description || d.error || "LHDN login failed — check credentials and intermediary authorization for TIN " + tin);
  }
  tokens.set(key, { t: d.access_token, exp: Date.now() + ((d.expires_in ?? 3600) - 120) * 1000 });
  return d.access_token;
}
async function callLhdn(env: string, tin: string, method: string, pathAndQuery: string, body?: string) {
  const go = async (force: boolean) => {
    const token = await getToken(env, tin, force);
    return fetch(BASES[env] + pathAndQuery, {
      method,
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json", Accept: "application/json", "Accept-Language": "en" },
      body,
    });
  };
  let r = await go(false);
  if (r.status === 401) r = await go(true); // token expired or revoked: retry once with a fresh token
  return r;
}

// ---------- Helpers ----------
type Err = { code: string; message: string; path: string; step: string };
function flatten(e: any, step = ""): Err[] {
  const out: Err[] = [];
  const walk = (x: any) => {
    if (!x || typeof x !== "object") return;
    const m = x.error || x.message;
    if (m && typeof m === "string") out.push({ code: x.errorCode || x.code || "", message: m, path: x.propertyPath || x.target || x.propertyName || "", step });
    (x.innerError || x.details || []).forEach(walk);
  };
  walk(e);
  return out.length ? out : e ? [{ code: "", message: JSON.stringify(e).slice(0, 300), path: "", step }] : [];
}
async function logEvent(companyId: string, kind: string, detail: string) {
  await admin.from("lhdn_events").insert({ company_id: companyId, kind, detail: detail.slice(0, 500) });
}
async function audit(companyId: string, user: any, action: string, detail: string) {
  await admin.from("audit_logs").insert({ company_id: companyId, actor: user.id, actor_email: user.email, action, detail: detail.slice(0, 500) });
}

async function record(op: string, ctx: { companyId: string; invoiceId: string; env: string; api: string; data: any; body?: string; user: any }) {
  const { companyId, invoiceId, env, api, data, user } = ctx;
  const now = new Date().toISOString();
  if (op === "submit") {
    let code = "";
    try { code = JSON.parse(ctx.body || "{}").documents?.[0]?.codeNumber ?? ""; } catch { /* ignore */ }
    const acc = (data?.acceptedDocuments ?? []).find((a: any) => a.invoiceCodeNumber === code) ?? data?.acceptedDocuments?.[0];
    const rej = (data?.rejectedDocuments ?? []).find((a: any) => a.invoiceCodeNumber === code) ?? data?.rejectedDocuments?.[0];
    if (!invoiceId) return;
    if (acc) {
      await admin.from("lhdn_documents").upsert({
        company_id: companyId, invoice_id: invoiceId, environment: env, code_number: code,
        submission_uid: data.submissionUid, uuid: acc.uuid, long_id: null, status: "Submitted",
        validated_at: null, errors: [], accepted_at: now, updated_at: now,
      });
      await audit(companyId, user, "lhdn.submit", `${code} accepted · ${data.submissionUid}`);
    } else if (rej) {
      await admin.from("lhdn_documents").upsert({
        company_id: companyId, invoice_id: invoiceId, environment: env, code_number: code,
        submission_uid: data?.submissionUid ?? null, uuid: null, status: "Invalid",
        errors: flatten(rej.error, "Submission"), updated_at: now,
      });
      await audit(companyId, user, "lhdn.submit", `${code} rejected`);
    }
  } else if (op === "status") {
    for (const d of data?.documentSummary ?? []) {
      if (!d.uuid) continue;
      const patch: Record<string, unknown> = { status: d.status, updated_at: now };
      if (d.longId) patch.long_id = d.longId;
      if (d.dateTimeValidated) patch.validated_at = d.dateTimeValidated;
      if (d.status === "Valid") patch.errors = [];
      await admin.from("lhdn_documents").update(patch).eq("company_id", companyId).eq("uuid", d.uuid);
    }
  } else if (op === "details") {
    const uuid = api.split("/")[3];
    const patch: Record<string, unknown> = { updated_at: now };
    if (data?.status) patch.status = data.status;
    if (data?.longId) patch.long_id = data.longId;
    if (data?.dateTimeValidated) patch.validated_at = data.dateTimeValidated;
    if (data?.status === "Invalid") {
      patch.errors = (data?.validationResults?.validationSteps ?? [])
        .filter((s: any) => s.status === "Invalid").flatMap((s: any) => flatten(s.error, s.name));
    }
    await admin.from("lhdn_documents").update(patch).eq("company_id", companyId).eq("uuid", uuid);
  } else if (op === "cancel") {
    const uuid = api.split("/")[4];
    await admin.from("lhdn_documents").update({ status: "Cancelled", updated_at: now }).eq("company_id", companyId).eq("uuid", uuid);
    let reason = "";
    try { reason = JSON.parse(ctx.body || "{}").reason ?? ""; } catch { /* ignore */ }
    await audit(companyId, user, "lhdn.cancel", `${uuid} · ${reason}`);
  }
}

// ---------- Handler ----------
Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  try {
    const url = new URL(req.url);
    const path = url.pathname.replace(/^\/(functions\/v1\/)?lhdn/, "") || "/";

    const jwt = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const { data: auth, error: authErr } = await admin.auth.getUser(jwt);
    const user = auth?.user;
    if (authErr || !user?.email) return json(errBody("Please sign in again."), 401);

    const companyId = req.headers.get("x-myr-company") ?? "";
    const env = req.headers.get("x-myr-environment") === "production" ? "production" : "sandbox";
    if (env === "production" && Deno.env.get("LHDN_PRODUCTION_ENABLED") !== "true") {
      return json(errBody("Production submission is not enabled on this server yet."), 403);
    }

    const { data: co } = await admin.from("companies").select("id,tin,status,data").eq("id", companyId).maybeSingle();
    if (!co) return json(errBody("Company not found."), 404);
    // Fictional demo tenants must never send real MyInvois requests, even if a client bypasses the UI.
    if (co.data?.demo === true) return json(errBody("Demo workspace: live LHDN API requests are disabled. No real documents are submitted."), 403);
    if (co.status !== "active") return json(errBody("This company account is suspended."), 403);
    const { data: mem } = await admin.from("company_members").select("role,status")
      .eq("company_id", companyId).eq("email", user.email.toLowerCase()).eq("status", "active").maybeSingle();
    if (!mem) return json(errBody("You do not have access to this company."), 403);
    const tin = String(co.tin ?? "").toUpperCase();
    if (!/^[A-Z]{1,2}\d{8,12}$/.test(tin)) return json(errBody("Company TIN is missing or invalid in Settings."), 400);

    if (path === "/" || path === "/health") {
      let authorized: boolean | null = null;
      let message = "";
      try { await getToken(env, tin); authorized = true; }
      catch (e) { authorized = e instanceof HttpErr && e.status === 403 ? false : null; message = (e as Error).message; }
      return json({ ok: true, environment: env, mode: MODE, authorized, message });
    }

    if (!path.startsWith("/lhdn/")) return json(errBody("Unknown route."), 404);
    const api = path.slice(5);
    const route = ROUTES.find((r) => r.m === req.method && r.re.test(api));
    if (!route) return json(errBody("This MyInvois operation is not allowed."), 404);
    if (!route.roles.includes(mem.role)) return json(errBody("Your role cannot perform this action."), 403);

    const body = req.method === "GET" ? undefined : await req.text();
    if (body && body.length > 5_000_000) return json(errBody("Payload too large (max 5 MB)."), 413);

    const r = await callLhdn(env, tin, req.method, api + url.search, body);
    const text = await r.text();
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }

    if (r.status === 429) await logEvent(companyId, "429", api);
    else if (r.status === 401 || r.status === 403) await logEvent(companyId, "auth", `${r.status} ${api}`);
    else if (r.status >= 500) await logEvent(companyId, "5xx", `${r.status} ${api}`);

    if (r.ok) await record(route.op, { companyId, invoiceId: req.headers.get("x-myr-invoice") ?? "", env, api, data, body, user });

    const headers: Record<string, string> = { ...CORS, "Content-Type": "application/json" };
    const ra = r.headers.get("Retry-After");
    if (ra) headers["Retry-After"] = ra;
    return new Response(text || "{}", { status: r.status, headers });
  } catch (e) {
    if (e instanceof HttpErr) {
      return json(errBody(e.message), e.status, e.retryAfter ? { "Retry-After": e.retryAfter } : {});
    }
    console.error(e);
    return json(errBody("Unexpected server error."), 500);
  }
});
