-- REVIEW ONLY: isolated sandbox ledger; never updates subscription plans.
CREATE TABLE myr_native.chip_test_intents (
 id uuid PRIMARY KEY,
 company_id uuid NOT NULL REFERENCES myr_native.companies(id),
 created_by uuid NOT NULL REFERENCES myr_native.users(id),
 plan text NOT NULL,
 amount_sen integer NOT NULL CHECK (
 (plan='Starter' AND amount_sen=900) OR
 (plan='Pro' AND amount_sen=1900) OR
 (plan='Business' AND amount_sen=3900)),
 currency text NOT NULL DEFAULT 'MYR' CHECK (currency='MYR'),
 mode text NOT NULL DEFAULT 'test' CHECK(mode='test'),
 state text NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved','dispatching','created','outcome_unknown','verified_test_paid','closed_unpaid')),
 provider_id uuid UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now(),
 verified_at timestamptz,
 CHECK (state NOT IN ('created','verified_test_paid') OR provider_id IS NOT NULL),
 CHECK ((state='verified_test_paid') = (verified_at IS NOT NULL)),
 UNIQUE(id,provider_id,amount_sen,currency)
);
-- Unknown dispatch outcomes block retries until reconciliation.
CREATE UNIQUE INDEX chip_test_one_open_intent ON myr_native.chip_test_intents(company_id)
 WHERE state IN ('reserved','dispatching','created','outcome_unknown');
CREATE TABLE myr_native.chip_test_receipts (
 intent_id uuid PRIMARY KEY,
 provider_id uuid NOT NULL UNIQUE,
 amount_sen integer NOT NULL,
 currency text NOT NULL CHECK(currency='MYR'),
 verified_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY (intent_id,provider_id,amount_sen,currency)
 REFERENCES myr_native.chip_test_intents(id,provider_id,amount_sen,currency)
);
REVOKE ALL ON myr_native.chip_test_intents,myr_native.chip_test_receipts FROM PUBLIC;
-- No grants, migrations, real receipts, triggers or entitlement changes in this review file.
