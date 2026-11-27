-- REVIEW ONLY. Sandbox/disposable database only, never production.
-- A sandbox settlement is not a real subscription payment.
CREATE TABLE myr_native.billing_gateway_sandbox (
    period_id uuid PRIMARY KEY REFERENCES myr_native.billing_periods(id),
    attempt_id uuid NOT NULL UNIQUE,
    collection_id text NOT NULL CHECK (length(collection_id) BETWEEN 1 AND 100),
    amount_sen integer NOT NULL CHECK (amount_sen IN (900,1900,3900)),
    state text NOT NULL CHECK (state IN ('reserved','unknown','due','paid','deleted')),
    bill_id text UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((state IN ('reserved','unknown') AND bill_id IS NULL)
        OR (state IN ('due','paid','deleted') AND bill_id IS NOT NULL))
);
REVOKE ALL ON myr_native.billing_gateway_sandbox FROM PUBLIC;
