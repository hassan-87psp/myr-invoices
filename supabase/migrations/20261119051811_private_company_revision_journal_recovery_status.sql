-- Private per-update company recovery journal.
-- This is a same-database safety history, NOT an offsite disaster-recovery backup.
create table if not exists myr_internal.company_revisions (
 id bigint generated always as identity primary key,
 company_id uuid not null,
 company_version integer not null,
 company_name text not null,
 company_tin text not null,
 company_plan text not null,
 company_status text not null,
 company_data jsonb not null,
 saved_at timestamptz not null default now()
);
alter table myr_internal.company_revisions enable row level security;
revoke all on myr_internal.company_revisions from public,anon,authenticated;
create index if not exists company_revisions_company_time_idx
 on myr_internal.company_revisions(company_id,saved_at desc);

create or replace function myr_internal.record_company_previous_version()
returns trigger language plpgsql security definer set search_path=''
as $body$
begin
 if new.data is distinct from old.data
     or new.name is distinct from old.name
     or new.tin is distinct from old.tin then
  insert into myr_internal.company_revisions
   (company_id,company_version,company_name,company_tin,company_plan,company_status,company_data)
  values
   (old.id,old.version,old.name,old.tin,old.plan,old.status,old.data);
 end if;
 return new;
end
$body$;
revoke all on function myr_internal.record_company_previous_version() from public,anon,authenticated;
drop trigger if exists companies_version_journal on public.companies;
create trigger companies_version_journal
 before update on public.companies
 for each row execute function myr_internal.record_company_previous_version();

-- Read-only administrator view for recovery readiness. No customer fields.
create or replace function public.admin_recovery_status()
returns jsonb language plpgsql stable security definer set search_path=''
as $body$
begin
 if auth.uid() is null or not public.is_platform_admin() then
  raise exception 'Not authorized' using errcode='42501';
 end if;
 return (
  select coalesce(jsonb_agg(jsonb_build_object(
   'company_id',c.id,
   'company_version',c.version,
   'revisions',coalesce((select count(*) from myr_internal.company_revisions r where r.company_id=c.id),0),
   'last_revision',(select max(saved_at) from myr_internal.company_revisions r where r.company_id=c.id),
   'precutover_snapshots',(select count(*) from myr_internal.company_snapshots s where s.company_id=c.id)
  ) order by c.id),'[]'::jsonb)
  from public.companies c
 );
end
$body$;
revoke all on function public.admin_recovery_status() from public,anon,authenticated;
grant execute on function public.admin_recovery_status() to authenticated;
