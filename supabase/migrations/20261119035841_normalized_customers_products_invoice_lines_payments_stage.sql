-- Installed as Supabase migration 20261119035841.
-- Normalized projections are READ-ONLY: companies.data remains authoritative.
-- This migration is non-destructive and keeps original company/customer/invoice data.
create table if not exists public.customer_records (
 company_id uuid not null references public.companies(id) on delete cascade,
 customer_id text not null check(length(customer_id) between 1 and 128),
 name text not null default '',tin text not null default '',
 archived boolean not null default false,
 customer_data jsonb not null,source_company_version integer not null,
 synced_at timestamptz not null default now(),primary key(company_id,customer_id)
);
create index if not exists customer_records_search_idx on public.customer_records(company_id,lower(name));

create table if not exists public.product_records (
 company_id uuid not null references public.companies(id) on delete cascade,
 product_id text not null check(length(product_id) between 1 and 128),
 name text not null default '',product_data jsonb not null,
 source_company_version integer not null,synced_at timestamptz not null default now(),
 primary key(company_id,product_id)
);
create table if not exists public.invoice_line_records (
 company_id uuid not null,invoice_id text not null,
 line_id text not null check(length(line_id) between 1 and 128),
 line_no integer not null,description text not null default '',
 quantity numeric not null default 0,unit_price_sen bigint not null default 0,
 line_data jsonb not null,source_company_version integer not null,
 synced_at timestamptz not null default now(),primary key(company_id,invoice_id,line_id),
 foreign key(company_id,invoice_id) references public.invoice_records(company_id,invoice_id) on delete cascade
);
create index if not exists invoice_line_records_order_idx on public.invoice_line_records(company_id,invoice_id,line_no);
create table if not exists public.payment_records (
 company_id uuid not null,invoice_id text not null,
 payment_id text not null check(length(payment_id) between 1 and 128),
 paid_on text,amount_sen bigint not null default 0 check(amount_sen>=0),
 method text not null default '',payment_data jsonb not null,
 source_company_version integer not null,synced_at timestamptz not null default now(),
 primary key(company_id,invoice_id,payment_id),
 foreign key(company_id,invoice_id) references public.invoice_records(company_id,invoice_id) on delete cascade
);
create index if not exists payment_records_date_idx on public.payment_records(company_id,paid_on desc);
alter table public.customer_records enable row level security;
alter table public.product_records enable row level security;
alter table public.invoice_line_records enable row level security;
alter table public.payment_records enable row level security;
revoke all on public.customer_records,public.product_records,public.invoice_line_records,public.payment_records from public,anon,authenticated;
grant select on public.customer_records,public.product_records,public.invoice_line_records,public.payment_records to authenticated;

drop policy if exists customer_records_member_select on public.customer_records;
create policy customer_records_member_select on public.customer_records for select to authenticated
 using(auth.uid() is not null and public.is_member(company_id));
drop policy if exists product_records_member_select on public.product_records;
create policy product_records_member_select on public.product_records for select to authenticated
 using(auth.uid() is not null and public.is_member(company_id));
drop policy if exists invoice_line_records_member_select on public.invoice_line_records;
create policy invoice_line_records_member_select on public.invoice_line_records for select to authenticated
 using(auth.uid() is not null and public.is_member(company_id));
drop policy if exists payment_records_member_select on public.payment_records;
create policy payment_records_member_select on public.payment_records for select to authenticated
 using(auth.uid() is not null and public.is_member(company_id));

CREATE OR REPLACE FUNCTION myr_internal.mirror_company_details()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'myr_internal'
AS $function$
declare
  customers jsonb;
  products jsonb;
  invoices jsonb;
begin
  if tg_op='UPDATE'
      and (new.data->'customers') is not distinct from (old.data->'customers')
      and (new.data->'products') is not distinct from (old.data->'products')
      and (new.data->'invoices') is not distinct from (old.data->'invoices') then
    return new;
  end if;
  customers:=case when jsonb_typeof(new.data->'customers')='array' then new.data->'customers' else '[]'::jsonb end;
  products:=case when jsonb_typeof(new.data->'products')='array' then new.data->'products' else '[]'::jsonb end;
  invoices:=case when jsonb_typeof(new.data->'invoices')='array' then new.data->'invoices' else '[]'::jsonb end;

  -- Customer and product IDs are stable. Source JSON retained for rollback.
  insert into public.customer_records(company_id,customer_id,name,tin,archived,customer_data,source_company_version)
  select distinct on (entry->>'id') new.id,entry->>'id',coalesce(entry->>'name',''),
    coalesce(entry->>'tin',''),coalesce(entry->>'archived','false')='true',entry,new.version
  from jsonb_array_elements(customers) entry
  where jsonb_typeof(entry)='object' and length(coalesce(entry->>'id','')) between 1 and 128
  order by entry->>'id'
  on conflict(company_id,customer_id) do update set
    name=excluded.name,tin=excluded.tin,archived=excluded.archived,
    customer_data=excluded.customer_data,source_company_version=excluded.source_company_version,
    synced_at=now()
  where public.customer_records.customer_data is distinct from excluded.customer_data;

  delete from public.customer_records r where r.company_id=new.id and not exists
    (select 1 from jsonb_array_elements(customers) entry where entry->>'id'=r.customer_id);

  insert into public.product_records(company_id,product_id,name,product_data,source_company_version)
  select distinct on (entry->>'id') new.id,entry->>'id',coalesce(entry->>'name',''),
    entry,new.version
  from jsonb_array_elements(products) entry
  where jsonb_typeof(entry)='object' and length(coalesce(entry->>'id','')) between 1 and 128
  order by entry->>'id'
  on conflict(company_id,product_id) do update set
    name=excluded.name,product_data=excluded.product_data,
    source_company_version=excluded.source_company_version,synced_at=now()
  where public.product_records.product_data is distinct from excluded.product_data;

  delete from public.product_records r where r.company_id=new.id and not exists
    (select 1 from jsonb_array_elements(products) entry where entry->>'id'=r.product_id);

  -- Invoice-record trigger executes first by name; FK keys already exist.
  insert into public.invoice_line_records(
    company_id,invoice_id,line_id,line_no,description,quantity,unit_price_sen,line_data,source_company_version
  )
  select distinct on (inv->>'id',item->>'id')
    new.id,inv->>'id',item->>'id',ord::integer,
    coalesce(item->>'desc',''),
    case when (item->>'qty') ~ '^-?[0-9]+(\.[0-9]+)?$' then (item->>'qty')::numeric else 0 end,
    case when (item->>'price') ~ '^-?[0-9]{1,15}$' then (item->>'price')::bigint else 0 end,
    item,new.version
  from jsonb_array_elements(invoices) inv
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(inv->'items')='array' then inv->'items' else '[]'::jsonb end
  ) with ordinality as line(item,ord)
  where length(coalesce(inv->>'id','')) between 1 and 128
    and length(coalesce(item->>'id','')) between 1 and 128
  order by inv->>'id',item->>'id',ord
  on conflict(company_id,invoice_id,line_id) do update set
    line_no=excluded.line_no,description=excluded.description,
    quantity=excluded.quantity,unit_price_sen=excluded.unit_price_sen,
    line_data=excluded.line_data,source_company_version=excluded.source_company_version,
    synced_at=now()
  where public.invoice_line_records.line_data is distinct from excluded.line_data
    or public.invoice_line_records.line_no is distinct from excluded.line_no;

  delete from public.invoice_line_records r where r.company_id=new.id and not exists (
    select 1 from jsonb_array_elements(invoices) inv
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(inv->'items')='array' then inv->'items' else '[]'::jsonb end
    ) item
    where inv->>'id'=r.invoice_id and item->>'id'=r.line_id
  );

  insert into public.payment_records(company_id,invoice_id,payment_id,paid_on,amount_sen,method,payment_data,source_company_version)
  select distinct on (inv->>'id',item->>'id')
    new.id,inv->>'id',item->>'id',
    item->>'date',
    case when (item->>'amount') ~ '^[0-9]{1,15}$' then (item->>'amount')::bigint else 0 end,
    coalesce(item->>'method',''),item,new.version
  from jsonb_array_elements(invoices) inv
  cross join lateral jsonb_array_elements(
    case when jsonb_typeof(inv->'payments')='array' then inv->'payments' else '[]'::jsonb end
  ) item
  where length(coalesce(inv->>'id','')) between 1 and 128
    and length(coalesce(item->>'id','')) between 1 and 128
  order by inv->>'id',item->>'id'
  on conflict(company_id,invoice_id,payment_id) do update set
    paid_on=excluded.paid_on,amount_sen=excluded.amount_sen,
    method=excluded.method,payment_data=excluded.payment_data,
    source_company_version=excluded.source_company_version,synced_at=now()
  where public.payment_records.payment_data is distinct from excluded.payment_data;

  delete from public.payment_records r where r.company_id=new.id and not exists (
    select 1 from jsonb_array_elements(invoices) inv
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(inv->'payments')='array' then inv->'payments' else '[]'::jsonb end
    ) item
    where inv->>'id'=r.invoice_id and item->>'id'=r.payment_id
  );
  return new;
end
$function$
;
revoke all on function myr_internal.mirror_company_details() from public,anon,authenticated;
drop trigger if exists companies_normalized_details_mirror on public.companies;
create trigger companies_normalized_details_mirror
 after insert or update of data on public.companies
 for each row execute function myr_internal.mirror_company_details();

-- Non-destructive initial backfill from legacy JSON.
insert into public.customer_records(company_id,customer_id,name,tin,archived,customer_data,source_company_version)
select distinct on (c.id,entry->>'id') c.id,entry->>'id',coalesce(entry->>'name',''),
 coalesce(entry->>'tin',''),coalesce(entry->>'archived','false')='true',entry,c.version
from public.companies c cross join lateral jsonb_array_elements(
 case when jsonb_typeof(c.data->'customers')='array' then c.data->'customers' else '[]'::jsonb end
) entry where length(coalesce(entry->>'id','')) between 1 and 128
order by c.id,entry->>'id' on conflict(company_id,customer_id) do nothing;
insert into public.product_records(company_id,product_id,name,product_data,source_company_version)
select distinct on (c.id,entry->>'id') c.id,entry->>'id',coalesce(entry->>'name',''),entry,c.version
from public.companies c cross join lateral jsonb_array_elements(
 case when jsonb_typeof(c.data->'products')='array' then c.data->'products' else '[]'::jsonb end
) entry where length(coalesce(entry->>'id','')) between 1 and 128
order by c.id,entry->>'id' on conflict(company_id,product_id) do nothing;
insert into public.invoice_line_records(company_id,invoice_id,line_id,line_no,description,quantity,unit_price_sen,line_data,source_company_version)
select distinct on (c.id,inv->>'id',item->>'id')
 c.id,inv->>'id',item->>'id',ord::integer,coalesce(item->>'desc',''),
 case when (item->>'qty')~'^-?[0-9]+(\.[0-9]+)?$' then (item->>'qty')::numeric else 0 end,
 case when (item->>'price')~'^-?[0-9]{1,15}$' then (item->>'price')::bigint else 0 end,
 item,c.version
from public.companies c cross join lateral jsonb_array_elements(
 case when jsonb_typeof(c.data->'invoices')='array' then c.data->'invoices' else '[]'::jsonb end
) inv cross join lateral jsonb_array_elements(
 case when jsonb_typeof(inv->'items')='array' then inv->'items' else '[]'::jsonb end
) with ordinality as lines(item,ord)
where length(coalesce(inv->>'id','')) between 1 and 128 and length(coalesce(item->>'id','')) between 1 and 128
order by c.id,inv->>'id',item->>'id',ord
on conflict(company_id,invoice_id,line_id) do nothing;
insert into public.payment_records(company_id,invoice_id,payment_id,paid_on,amount_sen,method,payment_data,source_company_version)
select distinct on (c.id,inv->>'id',item->>'id')
 c.id,inv->>'id',item->>'id',item->>'date',
 case when (item->>'amount')~'^[0-9]{1,15}$' then (item->>'amount')::bigint else 0 end,
 coalesce(item->>'method',''),item,c.version
from public.companies c cross join lateral jsonb_array_elements(
 case when jsonb_typeof(c.data->'invoices')='array' then c.data->'invoices' else '[]'::jsonb end
) inv cross join lateral jsonb_array_elements(
 case when jsonb_typeof(inv->'payments')='array' then inv->'payments' else '[]'::jsonb end
) item
where length(coalesce(inv->>'id','')) between 1 and 128 and length(coalesce(item->>'id','')) between 1 and 128
order by c.id,inv->>'id',item->>'id'
on conflict(company_id,invoice_id,payment_id) do nothing;
