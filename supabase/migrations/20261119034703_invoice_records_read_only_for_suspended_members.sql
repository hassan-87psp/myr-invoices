-- Suspended tenants can still read their data; only edits are blocked.
-- Applied to Supabase as migration 20261119034703.
drop policy if exists invoice_records_member_read on public.invoice_records;
create policy invoice_records_member_read on public.invoice_records
  for select to authenticated
  using (auth.uid() is not null and public.is_member(company_id));
