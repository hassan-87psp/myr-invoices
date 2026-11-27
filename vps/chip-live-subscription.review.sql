-- REVIEW ONLY. Not applied to production. No client grants.
CREATE TABLE myr_native.chip_live_intents (
 id uuid PRIMARY KEY,
 company_id uuid NOT NULL REFERENCES myr_native.companies(id),
 provider_id uuid NOT NULL UNIQUE,
 brand_id uuid NOT NULL,
 plan text NOT NULL,
 amount_sen integer NOT NULL CHECK((plan='Starter' AND amount_sen=900) OR
 (plan='Pro' AND amount_sen=1900) OR (plan='Business' AND amount_sen=3900)),
 currency text NOT NULL DEFAULT 'MYR' CHECK(currency='MYR'),
 period_start date NOT NULL,
 period_end date NOT NULL CHECK(period_end>period_start),
 anchor_day integer NOT NULL CHECK(anchor_day BETWEEN 1 AND 31),
 state text NOT NULL DEFAULT 'created' CHECK(state IN ('created','paid')),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(id,provider_id,amount_sen,currency),
 UNIQUE(company_id,period_start)
);
CREATE TABLE myr_native.chip_live_receipts (
 intent_id uuid PRIMARY KEY,
 provider_id uuid NOT NULL UNIQUE,
 amount_sen integer NOT NULL,
 currency text NOT NULL CHECK(currency='MYR'),
 recorded_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(intent_id,provider_id,amount_sen,currency)
 REFERENCES myr_native.chip_live_intents(id,provider_id,amount_sen,currency)
);
CREATE TABLE myr_native.chip_subscriptions (
 company_id uuid PRIMARY KEY REFERENCES myr_native.companies(id),
 plan text NOT NULL CHECK(plan IN ('Starter','Pro','Business')),
 period_start date NOT NULL,
 period_end date NOT NULL CHECK(period_end>period_start),
 anchor_day integer NOT NULL CHECK(anchor_day BETWEEN 1 AND 31),
 latest_intent uuid NOT NULL UNIQUE REFERENCES myr_native.chip_live_receipts(intent_id),
 updated_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON myr_native.chip_live_intents,myr_native.chip_live_receipts,myr_native.chip_subscriptions FROM PUBLIC;
-- Automatic card charging and access expiry enforcement require separate reviewed release.
