-- Exclude fictional demo tenants from Super Admin paid-business metrics.
-- Demo workspaces remain available only to their owning admin in the Demo Lab.
CREATE OR REPLACE FUNCTION public.admin_companies()
 RETURNS TABLE(id uuid, name text, tin text, plan text, status text, created_at timestamp with time zone, owner text, members bigint, invoices integer, valid bigint, invalid bigint, processing bigint, docs_month bigint, last_ok timestamp with time zone, rate_limits bigint)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
#variable_conflict use_column
begin
  if not public.is_platform_admin() then raise exception 'Not authorized'; end if;
  return query
  select c.id, c.name, c.tin, c.plan, c.status, c.created_at,
    (select m.email from public.company_members m where m.company_id = c.id and m.role = 'Owner' limit 1),
    (select count(*) from public.company_members m where m.company_id = c.id and m.status <> 'removed'),
    coalesce(jsonb_array_length(case when jsonb_typeof(c.data->'invoices') = 'array' then c.data->'invoices' end), 0),
    (select count(*) from public.lhdn_documents d where d.company_id = c.id and d.status = 'Valid'),
    (select count(*) from public.lhdn_documents d where d.company_id = c.id and d.status = 'Invalid'),
    (select count(*) from public.lhdn_documents d where d.company_id = c.id and d.status = 'Submitted'),
    (select count(*) from public.lhdn_documents d where d.company_id = c.id
       and d.accepted_at >= (date_trunc('month', now() at time zone 'Asia/Kuala_Lumpur') at time zone 'Asia/Kuala_Lumpur')),
    (select max(d.accepted_at) from public.lhdn_documents d where d.company_id = c.id),
    (select count(*) from public.lhdn_events e where e.company_id = c.id and e.kind = '429' and e.created_at > now() - interval '30 days')
  from public.companies c
  where coalesce(c.data->>'demo', 'false') <> 'true'
  order by c.created_at desc;
end $function$

