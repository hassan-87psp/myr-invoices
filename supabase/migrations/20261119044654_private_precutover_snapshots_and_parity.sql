-- Phase 1C: private pre-cutover snapshots and exact normalized-vs-JSON parity.
-- All reads remain read-only; this migration performs no canonical data cutover.
create table if not exists myr_internal.company_snapshots (
 snapshot_id uuid primary key default gen_random_uuid(),
 company_id uuid not null,
 source_version integer not null,
 company_name text not null,
 company_tin text not null,
 company_plan text not null,
 company_status text not null,
 company_data jsonb not null,
 tag text not null default 'phase1c-precutover',
 created_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '30 days'
);
alter table myr_internal.company_snapshots enable row level security;
revoke all on myr_internal.company_snapshots from public,anon,authenticated;
create index if not exists company_snapshots_company_date_idx
 on myr_internal.company_snapshots(company_id,created_at desc);

-- One snapshot per company for the current staging cutover point.
insert into myr_internal.company_snapshots (
 company_id,source_version,company_name,company_tin,
 company_plan,company_status,company_data,tag
)
select c.id,c.version,c.name,c.tin,c.plan,c.status,c.data,'phase1c-precutover'
from public.companies c
where not exists (
 select 1 from myr_internal.company_snapshots s
 where s.company_id=c.id and s.tag='phase1c-precutover'
);

-- Use a private, invoker-only view for parity checks.
create or replace view myr_internal.mirror_parity
with (security_invoker=true)
as
select
 c.id as company_id,
 c.version as company_version,
 jsonb_array_length(src.customers) as source_customers,
 (select count(*) from public.customer_records r where r.company_id=c.id) as mirror_customers,
 jsonb_array_length(src.products) as source_products,
 (select count(*) from public.product_records r where r.company_id=c.id) as mirror_products,
 jsonb_array_length(src.invoices) as source_invoices,
 (select count(*) from public.invoice_records r where r.company_id=c.id) as mirror_invoices,
 (select count(*) from jsonb_array_elements(src.invoices) inv
  cross join lateral jsonb_array_elements(
   case when jsonb_typeof(inv->'items')='array' then inv->'items' else '[]'::jsonb end
  ) item) as source_lines,
 (select count(*) from public.invoice_line_records r where r.company_id=c.id) as mirror_lines,
 (select count(*) from jsonb_array_elements(src.invoices) inv
  cross join lateral jsonb_array_elements(
   case when jsonb_typeof(inv->'payments')='array' then inv->'payments' else '[]'::jsonb end
  ) item) as source_payments,
 (select count(*) from public.payment_records r where r.company_id=c.id) as mirror_payments,
 (select coalesce(jsonb_agg(entry order by entry->>'id'),'[]'::jsonb)
  from jsonb_array_elements(src.customers) entry)
 =
 (select coalesce(jsonb_agg(r.customer_data order by r.customer_id),'[]'::jsonb)
  from public.customer_records r where r.company_id=c.id) as customers_match,
 (select coalesce(jsonb_agg(entry order by entry->>'id'),'[]'::jsonb)
  from jsonb_array_elements(src.products) entry)
 =
 (select coalesce(jsonb_agg(r.product_data order by r.product_id),'[]'::jsonb)
  from public.product_records r where r.company_id=c.id) as products_match,
 (select coalesce(jsonb_agg(entry-'lhdn' order by entry->>'id'),'[]'::jsonb)
  from jsonb_array_elements(src.invoices) entry)
 =
 (select coalesce(jsonb_agg(r.invoice_data order by r.invoice_id),'[]'::jsonb)
  from public.invoice_records r where r.company_id=c.id) as invoices_match,
 (select coalesce(jsonb_agg(item order by inv->>'id',item->>'id'),'[]'::jsonb)
  from jsonb_array_elements(src.invoices) inv
  cross join lateral jsonb_array_elements(
   case when jsonb_typeof(inv->'items')='array' then inv->'items' else '[]'::jsonb end
  ) item)
 =
 (select coalesce(jsonb_agg(r.line_data order by r.invoice_id,r.line_id),'[]'::jsonb)
  from public.invoice_line_records r where r.company_id=c.id) as lines_match,
 (select coalesce(jsonb_agg(item order by inv->>'id',item->>'id'),'[]'::jsonb)
  from jsonb_array_elements(src.invoices) inv
  cross join lateral jsonb_array_elements(
   case when jsonb_typeof(inv->'payments')='array' then inv->'payments' else '[]'::jsonb end
  ) item)
 =
 (select coalesce(jsonb_agg(r.payment_data order by r.invoice_id,r.payment_id),'[]'::jsonb)
  from public.payment_records r where r.company_id=c.id) as payments_match
from public.companies c
cross join lateral (
 select
 case when jsonb_typeof(c.data->'customers')='array' then c.data->'customers' else '[]'::jsonb end as customers,
 case when jsonb_typeof(c.data->'products')='array' then c.data->'products' else '[]'::jsonb end as products,
 case when jsonb_typeof(c.data->'invoices')='array' then c.data->'invoices' else '[]'::jsonb end as invoices
) src;
revoke all on myr_internal.mirror_parity from public,anon,authenticated;
