-- Atomic RPC needs to inspect reservations under invoker privileges.
grant select on public.invoice_number_reservations to authenticated;
drop policy if exists invoice_number_reservations_member_read on public.invoice_number_reservations;
create policy invoice_number_reservations_member_read on public.invoice_number_reservations
 for select to authenticated using (auth.uid() is not null and public.is_member(company_id));
