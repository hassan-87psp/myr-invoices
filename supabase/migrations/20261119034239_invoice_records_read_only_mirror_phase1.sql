-- Phase 1: additive invoice record mirror; no cutover from companies.data yet.
-- Applied to MYR INVOICES Supabase as migration 20261119034239.
create schema if not exists myr_internal;
revoke all on schema myr_internal from public, anon, authenticated;

create table if not exists public.invoice_records (
  company_id uuid not null references public.companies(id) on delete cascade,
  invoice_id text not null check (length(invoice_id) between 1 and 128),
  invoice_number text not null default '',
  doc_type text not null default '01',
  customer_id text,
  issue_date text,
  due_date text,
  currency text not null default 'MYR',
  application_status text not null default 'Draft',
  invoice_data jsonb not null default '{}'::jsonb,
  source_company_version integer not null,
  synced_at timestamptz not null default now(),
  primary key(company_id, invoice_id)
);
create index if not exists invoice_records_company_issue_idx
  on public.invoice_records(company_id, issue_date desc);
create index if not exists invoice_records_company_number_idx
  on public.invoice_records(company_id, invoice_number);
alter table public.invoice_records enable row level security;
revoke all on public.invoice_records from public, anon, authenticated;
grant select on public.invoice_records to authenticated;

drop policy if exists invoice_records_member_read on public.invoice_records;
create policy invoice_records_member_read on public.invoice_records
  for select to authenticated
  using (
    auth.uid() is not null
    and public.is_member(company_id)
    and exists (
      select 1 from public.companies c
      where c.id=company_id and c.status='active'
    )
  );

create or replace function myr_internal.mirror_company_invoices()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, myr_internal
as $fn$
declare items jsonb;
begin
  if tg_op='UPDATE' and (new.data->'invoices') is not distinct from (old.data->'invoices') then
    return new;
  end if;
  items := case when jsonb_typeof(new.data->'invoices')='array'
    then new.data->'invoices' else '[]'::jsonb end;

  insert into public.invoice_records (
      company_id, invoice_id, invoice_number, doc_type, customer_id,
      issue_date, due_date, currency, application_status, invoice_data,
      source_company_version, synced_at
  )
  select distinct on (entry->>'id')
      new.id, entry->>'id', coalesce(entry->>'number',''),
      coalesce(entry->>'docType','01'), entry->>'customerId',
      entry->>'issueDate', entry->>'dueDate',
      coalesce(entry->>'currency','MYR'), coalesce(entry->>'appStatus','Draft'),
      entry-'lhdn', new.version, now()
  from jsonb_array_elements(items) entry
  where jsonb_typeof(entry)='object'
    and length(coalesce(entry->>'id','')) between 1 and 128
  order by entry->>'id'
  on conflict (company_id, invoice_id) do update set
      invoice_number=excluded.invoice_number,
      doc_type=excluded.doc_type,
      customer_id=excluded.customer_id,
      issue_date=excluded.issue_date,
      due_date=excluded.due_date,
      currency=excluded.currency,
      application_status=excluded.application_status,
      invoice_data=excluded.invoice_data,
      source_company_version=excluded.source_company_version,
      synced_at=now()
  where public.invoice_records.invoice_data is distinct from excluded.invoice_data
     or public.invoice_records.invoice_number is distinct from excluded.invoice_number
     or public.invoice_records.application_status is distinct from excluded.application_status;

  delete from public.invoice_records r
  where r.company_id=new.id and not exists (
    select 1 from jsonb_array_elements(items) entry
    where entry->>'id'=r.invoice_id
  );
  return new;
end
$fn$;
revoke all on function myr_internal.mirror_company_invoices()
  from public, anon, authenticated;
drop trigger if exists companies_invoice_records_mirror on public.companies;
create trigger companies_invoice_records_mirror
  after insert or update of data on public.companies
  for each row execute function myr_internal.mirror_company_invoices();

-- Backfill any preexisting invoice snapshots. No original row is removed.
insert into public.invoice_records (
  company_id, invoice_id, invoice_number, doc_type, customer_id,
  issue_date, due_date, currency, application_status, invoice_data,
  source_company_version
)
select distinct on (c.id,entry->>'id')
  c.id, entry->>'id', coalesce(entry->>'number',''),
  coalesce(entry->>'docType','01'), entry->>'customerId',
  entry->>'issueDate', entry->>'dueDate',
  coalesce(entry->>'currency','MYR'), coalesce(entry->>'appStatus','Draft'),
  entry-'lhdn', c.version
from public.companies c
cross join lateral jsonb_array_elements(
  case when jsonb_typeof(c.data->'invoices')='array'
    then c.data->'invoices' else '[]'::jsonb end
) entry
where jsonb_typeof(entry)='object'
  and length(coalesce(entry->>'id','')) between 1 and 128
order by c.id, entry->>'id'
on conflict (company_id,invoice_id) do nothing;
