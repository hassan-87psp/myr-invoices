-- REVIEW ONLY. Do not execute on production. No worker or API is enabled.
-- Native VPS PostgreSQL, not Supabase. First rehearse on an isolated database.
BEGIN;
CREATE TABLE myr_native.lhdn_submission_intents (
  company_id uuid NOT NULL REFERENCES myr_native.companies(id) ON DELETE RESTRICT,
  invoice_id text NOT NULL CHECK(length(invoice_id) BETWEEN 1 AND 128),
  environment text NOT NULL CHECK(environment IN ('sandbox','production')),
  company_version bigint NOT NULL CHECK(company_version > 0),
  code_number text NOT NULL CHECK(length(code_number) BETWEEN 1 AND 80),
  issuer_tin text NOT NULL CHECK(issuer_tin ~ '^[A-Z]{1,3}[0-9]{1,13}$'),
  document_hash text NOT NULL CHECK(document_hash ~ '^[0-9a-f]{64}$'),
  document_bytes bytea NOT NULL CHECK(octet_length(document_bytes) BETWEEN 1 AND 250000),
  created_by uuid NOT NULL REFERENCES myr_native.users(id) ON DELETE RESTRICT,
  state text NOT NULL DEFAULT 'prepared'
    CHECK(state IN ('prepared','dispatching','outcome_unknown','accepted','valid','invalid','cancelled','abandoned')),
  submission_uid text,
  provider_uuid text,
  long_id text,
  validated_at timestamptz,
  dispatch_started_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(company_id,invoice_id,environment),
  UNIQUE(company_id,environment,code_number),
  UNIQUE(environment,provider_uuid),
  CHECK((submission_uid IS NULL)=(provider_uuid IS NULL)),
  CHECK(state NOT IN ('accepted','valid','invalid','cancelled') OR provider_uuid IS NOT NULL),
  CHECK(state <> 'valid' OR (long_id IS NOT NULL AND validated_at IS NOT NULL)),
  CHECK(state NOT IN ('dispatching','outcome_unknown','accepted','valid','invalid','cancelled') OR dispatch_started_at IS NOT NULL)
);
CREATE INDEX lhdn_intent_pending_idx ON myr_native.lhdn_submission_intents(environment,state,updated_at);
REVOKE ALL ON myr_native.lhdn_submission_intents FROM PUBLIC;
-- Existing app role ownership/grants and encrypted backup coverage require
-- operator review before applying this candidate to a real database.
-- No code may assume the table exists yet.
COMMIT;
