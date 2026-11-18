-- MYR Invoice role and buyer-link protections. Already applied to project.
drop policy if exists companies_select on public.companies;
create policy companies_select on public.companies for select to authenticated
using (public.is_member(id) or public.is_platform_admin());

CREATE OR REPLACE FUNCTION public.company_before_write()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
declare
  editable text[];
begin
  if tg_op = 'INSERT' then
    if not public.is_platform_admin() then
      new.status := 'active';
      new.created_by := auth.uid();
      new.version := 1;
      new.plan := 'Starter';
    end if;
  else
    if not public.is_platform_admin()
      and coalesce(auth.jwt()->>'role', '') <> 'service_role' then
      new.plan := old.plan;
      new.status := old.status;
      new.created_by := old.created_by;

      if not public.is_member(old.id, array['Owner','Admin']) then
        if new.name is distinct from old.name or new.tin is distinct from old.tin then
          raise exception 'Only the company owner or admin can change supplier details';
        end if;

        if public.is_member(old.id, array['Accountant','Invoice Staff']) then
          editable := array['invoices','customers','products','requests','imports','audit','usage'];
        elsif public.is_member(old.id, array['Approver']) then
          editable := array['invoices','audit'];
        else
          raise exception 'Your role cannot change company data';
        end if;

        if (new.data - editable) is distinct from (old.data - editable) then
          raise exception 'Only the company owner or admin can change account settings';
        end if;
      end if;
    end if;
    new.updated_at := now();
  end if;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.submit_public_link(p_token text, p_payload jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare l public.public_links%rowtype;
begin
  select * into l from public.public_links where token = p_token for update;
  if not found or l.closed or l.expires_at < (now() at time zone 'Asia/Kuala_Lumpur')::date
    or not exists (select 1 from public.companies c where c.id = l.company_id and c.status = 'active') then
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
end $function$
;
