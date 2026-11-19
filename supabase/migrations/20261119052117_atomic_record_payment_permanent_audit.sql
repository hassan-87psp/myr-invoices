-- Atomic operations append an immutable audit_logs row in the same tenant transaction.
CREATE OR REPLACE FUNCTION public.atomic_add_payment(p_company_id uuid, p_invoice_id text, p_payment jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
 co public.companies%rowtype;
 invoices jsonb;old_invoice jsonb;new_invoice jsonb;
 revised jsonb;updated jsonb;
 prev_payment jsonb;
 amount bigint;total bigint;paid bigint;
 pid text;
begin
 if auth.uid() is null or not public.is_member(p_company_id,array['Owner','Admin','Accountant','Invoice Staff']) then
  raise exception 'Not authorized to record payments' using errcode='42501';
 end if;
 if jsonb_typeof(p_payment)<>'object' then
  raise exception 'Invalid payment record' using errcode='22023';
 end if;
 pid:=p_payment->>'id';
 if pid is null or length(pid) not between 1 and 128 then
  raise exception 'Invalid payment ID' using errcode='22023';
 end if;
 if (p_payment->>'amount') !~ '^[0-9]{1,15}$' then
  raise exception 'Payment amount must be positive integer sen' using errcode='22023';
 end if;
 amount:=(p_payment->>'amount')::bigint;
 if amount<=0 then raise exception 'Payment must be positive' using errcode='22023';end if;
 if (p_payment->>'date') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  or (p_payment->>'date')::date>(now() at time zone 'Asia/Kuala_Lumpur')::date then
  raise exception 'Invalid or future payment date' using errcode='22023';
 end if;
 select * into co from public.companies where id=p_company_id for update;
 if not found or co.status<>'active' then
  raise exception 'Company unavailable' using errcode='42501';
 end if;
 invoices:=case when jsonb_typeof(co.data->'invoices')='array'
    then co.data->'invoices' else '[]'::jsonb end;
 select entry.value into old_invoice
 from jsonb_array_elements(invoices) entry where entry.value->>'id'=p_invoice_id limit 1;
 if old_invoice is null then
  raise exception 'Invoice not found' using errcode='22023';
 end if;
 if coalesce(old_invoice->'lhdn'->>'status','')='Cancelled' or
   exists(select 1 from public.lhdn_documents d
    where d.company_id=p_company_id and d.invoice_id=p_invoice_id and d.status='Cancelled') then
  raise exception 'Cancelled invoice cannot accept payments' using errcode='42501';
 end if;
 select entry.value into prev_payment from jsonb_array_elements(
   case when jsonb_typeof(old_invoice->'payments')='array'
    then old_invoice->'payments' else '[]'::jsonb end
 ) entry where entry.value->>'id'=pid limit 1;
 if prev_payment is not null then
  if (prev_payment - 'at') is distinct from (p_payment - 'at') then
   raise exception 'Payment ID already used for different details' using errcode='23505';
  end if;
  return jsonb_build_object('version',co.version,'company_data',co.data,
    'invoice',old_invoice,'existing',true);
 end if;
 total:=public.invoice_total_sen(old_invoice);
 select coalesce(sum((entry.value->>'amount')::bigint),0)::bigint into paid
 from jsonb_array_elements(
  case when jsonb_typeof(old_invoice->'payments')='array'
   then old_invoice->'payments' else '[]'::jsonb end
 ) entry;
 if paid+amount>total then
  raise exception 'Payment exceeds remaining invoice balance' using errcode='23514';
 end if;
 new_invoice:=jsonb_set(old_invoice,'{payments}',
  coalesce(old_invoice->'payments','[]'::jsonb)||jsonb_build_array(p_payment),true);
 select coalesce(jsonb_agg(
  case when entry.value->>'id'=p_invoice_id then new_invoice else entry.value end
  order by entry.ord),'[]'::jsonb)
 into revised from jsonb_array_elements(invoices) with ordinality as entry(value,ord);
 updated:=jsonb_set(co.data,'{invoices}',revised,true);
 update public.companies set data=updated,version=co.version+1
 where id=p_company_id;
 insert into public.audit_logs(company_id,actor,actor_email,action,detail)
 values(p_company_id,auth.uid(),public.jwt_email(),'payment.record',
 left('Invoice '||p_invoice_id||' payment '||pid||' amount_sen '||amount::text,500));
 return jsonb_build_object('version',co.version+1,'company_data',updated,
  'invoice',new_invoice,'existing',false);
end
$function$;

CREATE OR REPLACE FUNCTION public.atomic_save_record(p_company_id uuid, p_kind text, p_record jsonb, p_expected jsonb DEFAULT NULL::jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
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
 insert into public.audit_logs(company_id,actor,actor_email,action,detail)
 values(p_company_id,auth.uid(),public.jwt_email(),
 kind||case when old_rec is null then '.create' else '.update' end,
 left(kind||' record '||rid,500));
 return jsonb_build_object(
  'version',co.version+1,'company_data',updated,
  'record',safe_rec,'kind',kind,'operation',case when old_rec is null then 'created' else 'updated' end
 );
end
$function$;
