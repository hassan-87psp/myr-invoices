-- MANUAL ONLY: safe to restore old source writes only if no new VPS writes were
-- accepted OR all native writes have been reconciled back to source.
BEGIN;
SET LOCAL lock_timeout='5s';
DROP TRIGGER myr_cutover_write_guard ON public.audit_logs;
DROP TRIGGER myr_cutover_write_guard ON public.companies;
DROP TRIGGER myr_cutover_write_guard ON public.company_members;
DROP TRIGGER myr_cutover_write_guard ON public.customer_records;
DROP TRIGGER myr_cutover_write_guard ON public.invoice_line_records;
DROP TRIGGER myr_cutover_write_guard ON public.invoice_number_reservations;
DROP TRIGGER myr_cutover_write_guard ON public.invoice_records;
DROP TRIGGER myr_cutover_write_guard ON public.lhdn_documents;
DROP TRIGGER myr_cutover_write_guard ON public.lhdn_events;
DROP TRIGGER myr_cutover_write_guard ON public.lhdn_tenant_approvals;
DROP TRIGGER myr_cutover_write_guard ON public.payment_records;
DROP TRIGGER myr_cutover_write_guard ON public.product_records;
DROP TRIGGER myr_cutover_write_guard ON public.public_links;
DROP TRIGGER myr_cutover_write_guard ON myr_internal.company_revisions;
DROP TRIGGER myr_cutover_write_guard ON myr_internal.company_snapshots;
DROP FUNCTION myr_internal.myr_cutover_reject_write();
COMMIT;
