create or replace function public.atomic_save_record(
 p_company_id uuid,p_kind text,p_record jsonb,p_expected jsonb default null
) returns jsonb
language plpgsql security invoker set search_path=''
as $body$
declare
 co public.companies%rowtype;
 kind text;
 actor_role text[];
 base_rows jsonb;
 old_rec jsonb;
 safe_rec jsonb;
 revised jsonb;
 updated jsonb;
 rid text;
 n text;
 res public.invoice_number_reservations%rowtype;
 no_counter bigint;
begin
 kind:=p_kind;
 if kind not in ('customers','products','invoices') then
  raise exception 'Invalid record type' using errcode='22023';
 end if;
 if auth.uid() is null then raise exception 'Sign in required' using errcode='42501';end if;
 if kind='invoices' then
  actor_role:=array['Owner','Admin','Accountant','Invoice Staff'];
 else
  actor_role:=array['Owner','Admin','Accountant','Invoice Staff'];
 end if;
 if not public.is_member(p_company_id,actor_role) then
  raise exception 'Not authorized to edit %',kind using errcode='42501';
 end if;
 if jsonb_typeof(p_record)<>'object' then
  raise exception 'Record must be an object' using errcode='22023';
 end if;
 rid:=p_record->>'id';
 if rid is null or length(rid) not between 1 and 128 or
    octet_length(p_record::text)>500000 then
  raise exception 'Invalid record ID or payload size' using errcode='22023';
 end if;
 select * into co from public.companies where id=p_company_id for update;
 if not found or co.status<>'active' then
  raise exception 'Company not active or unavailable' using errcode='42501';
 end if;
 base_rows:=case when jsonb_typeof(co.data->kind)='array'
  then co.data->kind else '[]'::jsonb end;
 select elem.value into old_rec from jsonb_array_elements(base_rows) elem
  where elem.value->>'id'=rid limit 1;
 if (
   (kind='invoices' and (old_rec - 'lhdn' - 'timeline') is distinct from (p_expected - 'lhdn' - 'timeline'))
   or (kind<>'invoices' and old_rec is distinct from p_expected)
  ) then
  raise exception 'Record changed in another session; reload before editing'
   using errcode='40001';
 end if;
 safe_rec:=p_record;
 if kind='invoices' then
  n:=btrim(coalesce(p_record->>'number',''));
  if length(n) not between 1 and 80 then
   raise exception 'Invoice number missing or too long' using errcode='22023';
  end if;
  if exists (select 1 from jsonb_array_elements(base_rows) item
   where item->>'id'<>rid and
      lower(btrim(item->>'number'))=lower(n)) then
   raise exception 'Invoice number already in use' using errcode='23505';
  end if;
  if exists(select 1 from public.invoice_number_reservations x
     where x.company_id=p_company_id and lower(btrim(x.invoice_number))=lower(n)
      and x.invoice_id<>rid) then
   raise exception 'Invoice number reserved for another invoice' using errcode='23505';
  end if;
  if exists(select 1 from public.lhdn_documents d where d.company_id=p_company_id
   and d.invoice_id=rid and d.status in ('Submitted','Valid','Cancelled')) then
   raise exception 'Official e-Invoice is locked' using errcode='42501';
  end if;
  if old_rec is not null then
   if coalesce(old_rec->'payments','[]'::jsonb) is distinct from
      coalesce(p_record->'payments','[]'::jsonb) then
    raise exception 'Payments must be recorded using the payments action' using errcode='42501';
   end if;
   if coalesce(old_rec->'payments','[]'::jsonb) <> '[]'::jsonb
      and (old_rec->'items') is distinct from (p_record->'items') then
    raise exception 'Invoice items with recorded payments cannot be changed' using errcode='42501';
   end if;
   safe_rec:=jsonb_set(safe_rec,'{lhdn}',
     coalesce(old_rec->'lhdn','{"status":"Not Submitted"}'::jsonb),true);
  else
   if coalesce(p_record->'payments','[]'::jsonb)<>'[]'::jsonb then
    raise exception 'New invoices cannot contain prefilled payments' using errcode='42501';
   end if;
   safe_rec:=jsonb_set(safe_rec,'{lhdn}',
     '{"status":"Not Submitted","submissionUid":"","uuid":"","longId":"","validatedAt":"","errors":[],"attempts":[]}'::jsonb,true);
  end if;
  -- The first reservation is assigned under a tenant lock by reserve_invoice_number.
  select * into res from public.invoice_number_reservations
   where company_id=p_company_id and invoice_id=rid;
  if found and lower(btrim(res.invoice_number))<>lower(n) then
   raise exception 'Invoice number differs from its reservation' using errcode='23505';
  end if;
 end if;
 if old_rec is null then
  revised:=base_rows||jsonb_build_array(safe_rec);
 else
  select coalesce(jsonb_agg(case when elem.value->>'id'=rid
      then safe_rec else elem.value end order by elem.ord),'[]'::jsonb)
  into revised from jsonb_array_elements(base_rows) with ordinality as elem(value,ord);
 end if;
 updated:=jsonb_set(co.data,array[kind],revised,true);
 if kind='invoices' and old_rec is null then
  select * into res from public.invoice_number_reservations
   where company_id=p_company_id and invoice_id=rid;
  if found then
   no_counter:=greatest(coalesce((co.data->>'nextNo')::bigint,1001),res.sequence_no+1);
   updated:=jsonb_set(updated,'{nextNo}',to_jsonb(no_counter),true);
  end if;
 end if;
 update public.companies set data=updated,version=co.version+1
 where id=p_company_id;
 return jsonb_build_object(
  'version',co.version+1,'company_data',updated,
  'record',safe_rec,'kind',kind,'operation',case when old_rec is null then 'created' else 'updated' end
 );
end
$body$;
