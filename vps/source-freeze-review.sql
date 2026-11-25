-- MANUAL CUTOVER ONLY. Do not execute from CI or while old app must accept saves.
-- Review latest source schema, stop LHDN/payment jobs, backup and confirm approved release first.
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE FUNCTION myr_internal.myr_cutover_reject_write() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
  RAISE EXCEPTION 'MYR Invoice business database is read-only during migration' USING ERRCODE='55000';
END;
$$;
REVOKE ALL ON FUNCTION myr_internal.myr_cutover_reject_write() FROM PUBLIC;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.audit_logs
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.audit_logs ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.companies
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.companies ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.company_members
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.company_members ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.customer_records
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.customer_records ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.invoice_line_records
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.invoice_line_records ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.invoice_number_reservations
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.invoice_number_reservations ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.invoice_records
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.invoice_records ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.lhdn_documents
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.lhdn_documents ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.lhdn_events
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.lhdn_events ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.lhdn_tenant_approvals
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.lhdn_tenant_approvals ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.payment_records
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.payment_records ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.product_records
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.product_records ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.public_links
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE public.public_links ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON myr_internal.company_revisions
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE myr_internal.company_revisions ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
CREATE TRIGGER myr_cutover_write_guard BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON myr_internal.company_snapshots
FOR EACH STATEMENT EXECUTE FUNCTION myr_internal.myr_cutover_reject_write();
ALTER TABLE myr_internal.company_snapshots ENABLE ALWAYS TRIGGER myr_cutover_write_guard;
COMMIT;
-- Authentication and profiles are not frozen. Any signup hook touching a frozen business
-- table must be separately reviewed; do not promise signup continuity until tested.
