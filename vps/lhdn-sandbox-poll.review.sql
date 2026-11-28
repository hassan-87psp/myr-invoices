-- REVIEW ONLY. Apply ONLY to isolated myr_lhdn_sandbox, never production.
BEGIN;
DO $$ BEGIN
  IF current_database()<>'myr_lhdn_sandbox' THEN
    RAISE EXCEPTION 'Isolated Sandbox database required';
  END IF;
END $$;
ALTER TABLE myr_native.lhdn_submission_intents
  ADD COLUMN poll_claim uuid,
  ADD COLUMN poll_not_before timestamptz,
  ADD COLUMN poll_blocked boolean NOT NULL DEFAULT false,
  ADD CONSTRAINT sandbox_poll_scope CHECK (
    environment='sandbox' OR (poll_claim IS NULL AND poll_not_before IS NULL AND NOT poll_blocked)
  ),
  ADD CONSTRAINT poll_claim_deadline CHECK (poll_claim IS NULL OR poll_not_before IS NOT NULL);
COMMIT;
