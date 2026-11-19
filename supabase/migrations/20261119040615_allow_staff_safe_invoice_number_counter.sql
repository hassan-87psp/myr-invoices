-- Staff invoice counter updates require actually created invoices; no privileges broadened for other settings.

create or replace function public.company_before_write()
returns trigger
language plpgsql
set search_path=public
as $fn$
declare
 editable text[];
 old_no bigint;
 new_no bigint;
 new_docs bigint;
 old_invoices jsonb;
 new_invoices jsonb;
begin
 if tg_op='INSERT' then
  if not public.is_platform_admin() then
   new.status:='active';
   new.created_by:=auth.uid();
   new.version:=1;
   new.plan:='Starter';
  end if;
 else
  if not public.is_platform_admin()
     and coalesce(auth.jwt()->>'role','') <> 'service_role' then
   new.plan:=old.plan;
   new.status:=old.status;
   new.created_by:=old.created_by;
   if new.version<>old.version+1 then
    raise exception 'Company version must increment by exactly one';
   end if;

   if not public.is_member(old.id,array['Owner','Admin']) then
    if new.name is distinct from old.name or new.tin is distinct from old.tin then
     raise exception 'Only the company owner or admin can change supplier details';
    end if;

    if public.is_member(old.id,array['Accountant','Invoice Staff']) then
     editable:=array['invoices','customers','products','requests','imports','audit','usage'];

     -- The shared invoice counter is a derived operational field. Staff may
     -- advance it only while actually creating draft invoice records, never
     -- as an account-settings edit.
     if new.data->'nextNo' is distinct from old.data->'nextNo' then
      if (old.data->>'nextNo') !~ '^[0-9]{1,10}$'
         or (new.data->>'nextNo') !~ '^[0-9]{1,10}$' then
       raise exception 'Invalid invoice counter';
      end if;
      old_no:=(old.data->>'nextNo')::bigint;
      new_no:=(new.data->>'nextNo')::bigint;
      old_invoices:=case when jsonb_typeof(old.data->'invoices')='array'
        then old.data->'invoices' else '[]'::jsonb end;
      new_invoices:=case when jsonb_typeof(new.data->'invoices')='array'
        then new.data->'invoices' else '[]'::jsonb end;
      select count(*) into new_docs
        from jsonb_array_elements(new_invoices) entry
        where length(coalesce(entry->>'id',''))>0
          and not exists (
            select 1 from jsonb_array_elements(old_invoices) prior
            where prior->>'id'=entry->>'id'
          );
      if new_no<=old_no or new_docs=0 or new_no-old_no > new_docs * 1000 then
       raise exception 'Invoice counter may advance only for newly created invoices';
      end if;
      editable:=array_append(editable,'nextNo');
     end if;
    elsif public.is_member(old.id,array['Approver']) then
     editable:=array['invoices','audit'];
    else
     raise exception 'Your role cannot change company data';
    end if;
    if (new.data - editable) is distinct from (old.data - editable) then
     raise exception 'Only the company owner or admin can change account settings';
    end if;
   end if;
  end if;
  new.updated_at:=now();
 end if;
 return new;
end
$fn$;
