-- REVIEW ONLY: no migration has been applied.
-- Edge-only durable, one-shot fence for the explicitly approved Sandbox grant.
BEGIN;
CREATE TABLE public.myr_lhdn_sandbox_dispatch_fence (
  tenant_id uuid NOT NULL,
  taxpayer text NOT NULL CHECK (taxpayer ~ '^[A-Z]{1,3}[0-9]{1,13}$'),
  document_hash text PRIMARY KEY CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  code_number text NOT NULL CHECK (length(code_number) BETWEEN 1 AND 50),
  expires_at timestamptz NOT NULL,
  claimed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,code_number),
  CHECK(expires_at > claimed_at AND expires_at <= claimed_at + interval '15 minutes')
);
ALTER TABLE public.myr_lhdn_sandbox_dispatch_fence ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.myr_lhdn_sandbox_dispatch_fence FROM PUBLIC, anon, authenticated, service_role;
GRANT INSERT ON public.myr_lhdn_sandbox_dispatch_fence TO service_role;
-- No automatic expiry deletion, update, or re-arming. A claimed grant stays consumed.
COMMIT;
