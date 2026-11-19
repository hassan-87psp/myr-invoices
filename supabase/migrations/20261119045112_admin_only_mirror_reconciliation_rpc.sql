-- Super Admin read-only data integrity RPC; exposes aggregate counts only.
create or replace function public.admin_mirror_parity()
returns jsonb
language plpgsql
stable security definer
set search_path=''
as $$
begin
 if auth.uid() is null or not public.is_platform_admin() then
   raise exception 'Not authorized' using errcode='42501';
 end if;
 return (
  select coalesce(jsonb_agg(jsonb_build_object(
   'company_id',p.company_id,
   'source_customers',p.source_customers,
   'mirror_customers',p.mirror_customers,
   'source_products',p.source_products,
   'mirror_products',p.mirror_products,
   'source_invoices',p.source_invoices,
   'mirror_invoices',p.mirror_invoices,
   'source_lines',p.source_lines,
   'mirror_lines',p.mirror_lines,
   'source_payments',p.source_payments,
   'mirror_payments',p.mirror_payments,
   'customers_match',p.customers_match,
   'products_match',p.products_match,
   'invoices_match',p.invoices_match,
   'lines_match',p.lines_match,
   'payments_match',p.payments_match
  ) order by p.company_id),'[]'::jsonb)
  from myr_internal.mirror_parity p
 );
end;
$$;
revoke all on function public.admin_mirror_parity() from public,anon,authenticated;
grant execute on function public.admin_mirror_parity() to authenticated;