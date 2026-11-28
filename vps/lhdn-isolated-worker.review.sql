-- Isolated Sandbox only. The worker may reserve and persist intent state,
-- but may not modify identities, invoices, memberships or official records.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'myr_lhdn_sandbox' OR current_user<>'myr_lhdn_sandbox_admin' OR inet_server_addr() IS NOT NULL THEN
   RAISE EXCEPTION 'Private Sandbox database and owner required';
 END IF;
END $$;
ALTER TABLE myr_native.lhdn_submission_intents ADD CONSTRAINT sandbox_only CHECK(environment='sandbox');
REVOKE ALL ON ALL TABLES IN SCHEMA myr_native FROM PUBLIC,myr_lhdn_sandbox_worker;
GRANT USAGE ON SCHEMA myr_native TO myr_lhdn_sandbox_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA myr_native TO myr_lhdn_sandbox_worker;
GRANT INSERT (company_id,invoice_id,environment,company_version,code_number,issuer_tin,document_hash,document_bytes,created_by)
 ON myr_native.lhdn_submission_intents TO myr_lhdn_sandbox_worker;
GRANT UPDATE (state,submission_uid,provider_uuid,long_id,validated_at,dispatch_started_at,updated_at,poll_claim,poll_not_before,poll_blocked)
 ON myr_native.lhdn_submission_intents TO myr_lhdn_sandbox_worker;
-- PostgreSQL locking clauses need UPDATE on at least one column.
-- Grant only a harmless column and reject actual worker updates via a trigger.
GRANT UPDATE (version) ON myr_native.companies TO myr_lhdn_sandbox_worker;
GRANT UPDATE (disabled) ON myr_native.users TO myr_lhdn_sandbox_worker;
GRANT UPDATE (status) ON myr_native.company_members TO myr_lhdn_sandbox_worker;
CREATE FUNCTION myr_native.reject_worker_identity_write() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
 IF current_user='myr_lhdn_sandbox_worker' THEN RAISE EXCEPTION 'Worker cannot mutate source identity' USING ERRCODE='insufficient_privilege'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER reject_worker_update BEFORE UPDATE ON myr_native.companies FOR EACH ROW EXECUTE FUNCTION myr_native.reject_worker_identity_write();
CREATE TRIGGER reject_worker_update BEFORE UPDATE ON myr_native.users FOR EACH ROW EXECUTE FUNCTION myr_native.reject_worker_identity_write();
CREATE TRIGGER reject_worker_update BEFORE UPDATE ON myr_native.company_members FOR EACH ROW EXECUTE FUNCTION myr_native.reject_worker_identity_write();
REVOKE ALL ON FUNCTION myr_native.reject_worker_identity_write() FROM PUBLIC;
COMMIT;
