-- =====================================================================
-- MYR Invoice — initial database schema (Supabase / PostgreSQL)
-- Tenant isolation by company membership (email from verified JWT).
-- Official LHDN results are written ONLY by the server (Edge Function,
-- service role) so a browser can never fake a "Valid" status.
-- =====================================================================
-- gen_random_uuid() is built into PostgreSQL 13+

-- ---------- Tables ----------
create table if not exists public.profiles (
  id                uuid primary key references auth.users(id) on delete cascade,
  email             text not null,
  name              text,
  is_platform_admin boolean not null default false,
  created_at        timestamptz not null default now()
);

create table if not exists public.companies (
  id          uuid primary key default gen_random_uuid(),
  name        text not null default '',
  tin         text not null default '',
  plan        text not null default 'Pro' check (plan in ('Starter','Pro','Business','Accountant','Enterprise')),
  status      text not null default 'active' check (status in ('active','suspended')),
  version     integer not null default 1,
  data        jsonb not null default '{}'::jsonb,
  created_by  uuid not null default auth.uid() references auth.users(id),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index if not exists companies_created_by_idx on public.companies(created_by);

create table if not exists public.company_members (
  company_id  uuid not null references public.companies(id) on delete cascade,
  email       text not null check (email = lower(email)),
  name        text,
  role        text not null check (role in ('Owner','Admin','Accountant','Invoice Staff','Approver','Read-Only')),
  status      text not null default 'active' check (status in ('active','invited','removed')),
  created_at  timestamptz not null default now(),
  primary key (company_id, email)
);
create index if not exists company_members_email_idx on public.company_members(email);

create table if not exists public.lhdn_documents (
  company_id     uuid not null references public.companies(id) on delete cascade,
  invoice_id     text not null,
  environment    text not null check (environment in ('sandbox','production')),
  code_number    text,
  submission_uid text,
  uuid           text,
  long_id        text,
  status         text not null,
  validated_at   timestamptz,
  errors         jsonb not null default '[]'::jsonb,
  accepted_at    timestamptz,
  updated_at     timestamptz not null default now(),
  primary key (company_id, invoice_id)
);
create index if not exists lhdn_documents_uuid_idx on public.lhdn_documents(uuid);
create index if not exists lhdn_documents_accepted_idx on public.lhdn_documents(company_id, accepted_at);

create table if not exists public.lhdn_events (
  id          bigint generated always as identity primary key,
  company_id  uuid references public.companies(id) on delete cascade,
  kind        text not null,
  detail      text,
  created_at  timestamptz not null default now()
);
create index if not exists lhdn_events_created_idx on public.lhdn_events(created_at desc);

create table if not exists public.public_links (
  token       text primary key check (length(token) >= 20),
  company_id  uuid not null references public.companies(id) on delete cascade,
  kind        text not null check (kind in ('qr','invoice')),
  ref_id      text not null,
  expires_at  date not null,
  closed      boolean not null default false,
  meta        jsonb not null default '{}'::jsonb,
  data        jsonb,
  submits     integer not null default 0,
  created_at  timestamptz not null default now()
);
create index if not exists public_links_company_idx on public.public_links(company_id);

create table if not exists public.audit_logs (
  id          bigint generated always as identity primary key,
  company_id  uuid references public.companies(id) on delete set null,
  actor       uuid,
  actor_email text,
  action      text not null,
  detail      text,
  created_at  timestamptz not null default now()
);
create index if not exists audit_logs_company_idx on public.audit_logs(company_id, created_at desc);

-- ---------- Helper functions ----------
create or replace function public.jwt_email() returns text
language sql stable as $$ select lower(coalesce(auth.jwt()->>'email','')) $$;

create or replace function public.is_member(cid uuid, roles text[] default null) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.company_members m
    where m.company_id = cid and m.email = public.jwt_email() and m.email <> ''
      and m.status = 'active' and (roles is null or m.role = any(roles)))
$$;

create or replace function public.is_platform_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select p.is_platform_admin from public.profiles p where p.id = auth.uid()), false)
$$;

-- ---------- Triggers ----------
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles(id, email, name)
  values (new.id, lower(new.email), coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

create or replace function public.company_before_write() returns trigger
language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    if not public.is_platform_admin() then
      new.status := 'active';
      new.created_by := auth.uid();
      new.version := 1;
      new.plan := 'Starter'; -- free plan only; billing/admin must approve upgrades
    end if;
  else
    if not public.is_platform_admin() and coalesce(auth.jwt()->>'role', '') <> 'service_role' then
      new.plan := old.plan;            -- plan changes only via billing / admin
      new.status := old.status;        -- suspension only via admin
      new.created_by := old.created_by;
    end if;
    new.updated_at := now();
  end if;
  return new;
end $$;
drop trigger if exists companies_before_write on public.companies;
create trigger companies_before_write before insert or update on public.companies
  for each row execute function public.company_before_write();

create or replace function public.company_after_insert() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.company_members(company_id, email, name, role, status)
  values (new.id, public.jwt_email(), (select p.name from public.profiles p where p.id = auth.uid()), 'Owner', 'active')
  on conflict do nothing;
  insert into public.audit_logs(company_id, actor, actor_email, action, detail)
  values (new.id, auth.uid(), public.jwt_email(), 'company.create', new.name);
  return new;
end $$;
drop trigger if exists companies_after_insert on public.companies;
create trigger companies_after_insert after insert on public.companies
  for each row execute function public.company_after_insert();

-- ---------- Row Level Security ----------
alter table public.profiles        enable row level security;
alter table public.companies       enable row level security;
alter table public.company_members enable row level security;
alter table public.lhdn_documents  enable row level security;
alter table public.lhdn_events     enable row level security;
alter table public.public_links    enable row level security;
alter table public.audit_logs      enable row level security;

-- profiles: read own (admins read all). No update policy: is_platform_admin cannot be self-assigned.
drop policy if exists profiles_select on public.profiles;
create policy profiles_select on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_platform_admin());

-- companies
drop policy if exists companies_select on public.companies;
create policy companies_select on public.companies for select to authenticated
  using (public.is_member(id) or created_by = auth.uid() or public.is_platform_admin());
drop policy if exists companies_insert on public.companies;
create policy companies_insert on public.companies for insert to authenticated
  with check (created_by = auth.uid());
drop policy if exists companies_update on public.companies;
create policy companies_update on public.companies for update to authenticated
  using (status = 'active' and public.is_member(id, array['Owner','Admin','Accountant','Invoice Staff','Approver']))
  with check (public.is_member(id, array['Owner','Admin','Accountant','Invoice Staff','Approver']));
drop policy if exists companies_delete on public.companies;
create policy companies_delete on public.companies for delete to authenticated
  using (public.is_member(id, array['Owner']));

-- company_members
drop policy if exists members_select on public.company_members;
create policy members_select on public.company_members for select to authenticated
  using (public.is_member(company_id));
drop policy if exists members_insert on public.company_members;
create policy members_insert on public.company_members for insert to authenticated
  with check (role <> 'Owner' and public.is_member(company_id, array['Owner','Admin']));
drop policy if exists members_update on public.company_members;
create policy members_update on public.company_members for update to authenticated
  using (role <> 'Owner' and public.is_member(company_id, array['Owner','Admin']))
  with check (role <> 'Owner' and public.is_member(company_id, array['Owner','Admin']));
drop policy if exists members_delete on public.company_members;
create policy members_delete on public.company_members for delete to authenticated
  using (role <> 'Owner' and public.is_member(company_id, array['Owner','Admin']));

-- lhdn_documents: read-only for members. Writes only by service role (Edge Function).
drop policy if exists lhdn_docs_select on public.lhdn_documents;
create policy lhdn_docs_select on public.lhdn_documents for select to authenticated
  using (public.is_member(company_id));

drop policy if exists lhdn_events_select on public.lhdn_events;
create policy lhdn_events_select on public.lhdn_events for select to authenticated
  using (public.is_member(company_id) or public.is_platform_admin());

-- public_links: members manage their own company's links. Buyers use RPCs below.
drop policy if exists links_select on public.public_links;
create policy links_select on public.public_links for select to authenticated
  using (public.is_member(company_id));
drop policy if exists links_insert on public.public_links;
create policy links_insert on public.public_links for insert to authenticated
  with check (public.is_member(company_id, array['Owner','Admin','Accountant','Invoice Staff','Approver']));
drop policy if exists links_update on public.public_links;
create policy links_update on public.public_links for update to authenticated
  using (public.is_member(company_id, array['Owner','Admin','Accountant','Invoice Staff','Approver']))
  with check (public.is_member(company_id, array['Owner','Admin','Accountant','Invoice Staff','Approver']));
drop policy if exists links_delete on public.public_links;
create policy links_delete on public.public_links for delete to authenticated
  using (public.is_member(company_id, array['Owner','Admin','Accountant','Invoice Staff','Approver']));

-- audit_logs: append-only (no update/delete policies)
drop policy if exists audit_select on public.audit_logs;
create policy audit_select on public.audit_logs for select to authenticated
  using (public.is_member(company_id, array['Owner','Admin','Accountant']) or public.is_platform_admin());
drop policy if exists audit_insert on public.audit_logs;
create policy audit_insert on public.audit_logs for insert to authenticated
  with check (actor = auth.uid() and public.is_member(company_id));

-- ---------- RPCs ----------
create or replace function public.accept_invites() returns void
language sql security definer set search_path = public as $$
  update public.company_members set status = 'active'
  where email = public.jwt_email() and email <> '' and status = 'invited';
$$;

-- Public (buyer) access by unguessable token only — never lists other data.
create or replace function public.get_public_link(p_token text) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'kind', l.kind, 'meta', l.meta, 'expires_at', l.expires_at, 'closed', l.closed,
    'data', case when l.kind = 'qr' then l.data else null end,
    'company_name', c.name)
  from public.public_links l join public.companies c on c.id = l.company_id
  where l.token = p_token and c.status = 'active'
    and l.closed = false
    and l.expires_at >= (now() at time zone 'Asia/Kuala_Lumpur')::date;
$$;

create or replace function public.submit_public_link(p_token text, p_payload jsonb) returns jsonb
language plpgsql security definer set search_path = public as $$
declare l public.public_links%rowtype;
begin
  select * into l from public.public_links where token = p_token for update;
  if not found or l.closed or l.expires_at < (now() at time zone 'Asia/Kuala_Lumpur')::date then
    raise exception 'This link is not available';
  end if;
  if l.submits >= 10 then raise exception 'Too many submissions for this link'; end if;
  if pg_column_size(p_payload) > 8000 then raise exception 'Payload too large'; end if;
  if l.kind = 'qr' then
    update public.public_links
       set data = p_payload || jsonb_build_object('at', now()), submits = submits + 1
     where token = p_token;
  else
    update public.public_links
       set data = jsonb_build_object('corrections',
                  coalesce(l.data->'corrections', '[]'::jsonb) || jsonb_build_array(jsonb_build_object(
                    'id', gen_random_uuid(), 'at', now(),
                    'email', left(coalesce(p_payload->>'email',''), 200),
                    'message', left(coalesce(p_payload->>'message',''), 1000)))),
           submits = submits + 1
     where token = p_token;
  end if;
  return jsonb_build_object('ok', true);
end $$;
grant execute on function public.get_public_link(text) to anon, authenticated;
grant execute on function public.submit_public_link(text, jsonb) to anon, authenticated;

-- ---------- Super Admin RPCs (aggregates only; no invoice contents) ----------
create or replace function public.admin_companies()
returns table(id uuid, name text, tin text, plan text, status text, created_at timestamptz, owner text,
              members bigint, invoices integer, valid bigint, invalid bigint, processing bigint,
              docs_month bigint, last_ok timestamptz, rate_limits bigint)
language plpgsql stable security definer set search_path = public as $$
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
  order by c.created_at desc;
end $$;

create or replace function public.admin_events(p_limit integer default 100)
returns table(created_at timestamptz, company text, kind text, detail text)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
begin
  if not public.is_platform_admin() then raise exception 'Not authorized'; end if;
  return query
  select e.created_at, c.name, e.kind, e.detail
  from public.lhdn_events e left join public.companies c on c.id = e.company_id
  order by e.created_at desc limit least(greatest(p_limit, 1), 500);
end $$;

create or replace function public.admin_users()
returns table(email text, name text, created_at timestamptz, last_sign_in_at timestamptz, companies bigint, is_admin boolean)
language plpgsql stable security definer set search_path = public, auth as $$
#variable_conflict use_column
begin
  if not public.is_platform_admin() then raise exception 'Not authorized'; end if;
  return query
  select p.email, p.name, p.created_at, u.last_sign_in_at,
    (select count(*) from public.company_members m where m.email = p.email and m.status <> 'removed'),
    p.is_platform_admin
  from public.profiles p left join auth.users u on u.id = p.id
  order by p.created_at desc;
end $$;

create or replace function public.admin_set_company(p_id uuid, p_status text default null, p_plan text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_platform_admin() then raise exception 'Not authorized'; end if;
  update public.companies set status = coalesce(p_status, status), plan = coalesce(p_plan, plan) where id = p_id;
  insert into public.audit_logs(company_id, actor, actor_email, action, detail)
  values (p_id, auth.uid(), public.jwt_email(), 'admin.company',
          concat_ws(' ', 'status=' || p_status, 'plan=' || p_plan));
end $$;

revoke execute on function public.admin_companies() from anon;
revoke execute on function public.admin_events(integer) from anon;
revoke execute on function public.admin_users() from anon;
revoke execute on function public.admin_set_company(uuid, text, text) from anon;

-- ---------- Explicit execution privileges ----------
-- PostgreSQL grants EXECUTE to PUBLIC on newly created functions by default.
-- Limit privileged business functions to authenticated clients.
revoke execute on function public.is_member(uuid, text[]) from public, anon;
revoke execute on function public.is_platform_admin() from public, anon;
revoke execute on function public.accept_invites() from public, anon;
revoke execute on function public.admin_companies() from public, anon;
revoke execute on function public.admin_events(integer) from public, anon;
revoke execute on function public.admin_users() from public, anon;
revoke execute on function public.admin_set_company(uuid, text, text) from public, anon;
grant execute on function public.is_member(uuid, text[]) to authenticated;
grant execute on function public.is_platform_admin() to authenticated;
grant execute on function public.accept_invites() to authenticated;
grant execute on function public.admin_companies() to authenticated;
grant execute on function public.admin_events(integer) to authenticated;
grant execute on function public.admin_users() to authenticated;
grant execute on function public.admin_set_company(uuid, text, text) to authenticated;
