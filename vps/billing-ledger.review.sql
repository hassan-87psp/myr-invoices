-- REVIEW ONLY. Do not apply to production. No automatic plan changes.
CREATE TABLE myr_native.billing_periods (
    id uuid PRIMARY KEY,
    company_id uuid NOT NULL REFERENCES myr_native.companies(id),
    period_start date NOT NULL CHECK (EXTRACT(DAY FROM period_start)=1),
    plan text NOT NULL CHECK (plan IN ('Starter','Pro','Business')),
    amount_sen integer NOT NULL CHECK (
      (plan='Starter' AND amount_sen=900) OR (plan='Pro' AND amount_sen=1900)
      OR (plan='Business' AND amount_sen=3900)),
    currency text NOT NULL DEFAULT 'MYR' CHECK (currency='MYR'),
    created_by uuid NOT NULL REFERENCES myr_native.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (company_id,period_start),
    UNIQUE (id,amount_sen,currency)
);
CREATE TABLE myr_native.billing_receipts (
    period_id uuid PRIMARY KEY,
    amount_sen integer NOT NULL,
    currency text NOT NULL CHECK (currency='MYR'),
    method text NOT NULL CHECK (method IN ('bank_transfer','duitnow','other_manual')),
    reference text NOT NULL UNIQUE CHECK (length(reference) BETWEEN 1 AND 100),
    recorded_by uuid NOT NULL REFERENCES myr_native.users(id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (period_id,amount_sen,currency)
      REFERENCES myr_native.billing_periods(id,amount_sen,currency)
);
-- Deployment must explicitly grant only necessary SELECT/INSERT permissions
-- to the application role, never UPDATE/DELETE or DDL.
REVOKE ALL ON myr_native.billing_periods,myr_native.billing_receipts FROM PUBLIC;
