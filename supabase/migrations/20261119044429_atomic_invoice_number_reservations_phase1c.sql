-- Phase 1C: atomic, idempotent invoice-number reservation.
-- This is additive. companies.data remains the canonical invoice source until final cutover.
create table if not exists public.invoice_number_reservations (
 company_id uuid not null references public.companies(id) on delete cascade,
 invoice_id text not null check (length(invoice_id) between 1 and 128),
 invoice_number text not null check (length(invoice_number) between 1 and 80),
 prefix text not null,
 sequence_no bigint not null check(sequence_no > 0),
 reserved_by uuid not null,
 reserved_at timestamptz not null default now(),
 primary key(company_id,invoice_id)
);
create unique index if not exists invoice_number_reservations_unique_number
 on public.invoice_number_reservations(company_id,lower(btrim(invoice_number)));
create index if not exists invoice_number_reservations_prefix_sequence
 on public.invoice_number_reservations(company_id,prefix,sequence_no desc);
alter table public.invoice_number_reservations enable row level security;
revoke all on public.invoice_number_reservations from public,anon,authenticated;

create or replace function public.reserve_invoice_number(p_company_id uuid,p_invoice_id text)
returns jsonb
language plpgsql
security definer
set search_path=''
as $$
declare
 c record;
 existing public.invoice_number_reservations%rowtype;
 pre text;
 start_no bigint;
 counter bigint;
 proposal text;
 tries integer;
begin
 if auth.uid() is null
   or not public.is_member(p_company_id,array['Owner','Admin','Accountant','Invoice Staff']) then
   raise exception 'Not authorized to reserve invoice numbers' using errcode='42501';
 end if;
 if p_invoice_id is null or length(p_invoice_id) not between 1 and 128 then
   raise exception 'Invalid invoice ID' using errcode='22023';
 end if;
 -- A row lock serializes reservations for the same tenant even across devices.
 select id,status,data into c from public.companies where id=p_company_id for update;
 if not found or c.status<>'active' then
   raise exception 'Company not available' using errcode='42501';
 end if;
 select * into existing from public.invoice_number_reservations
 where company_id=p_company_id and invoice_id=p_invoice_id;
 if found then
   return jsonb_build_object('number',existing.invoice_number,'nextNo',existing.sequence_no+1,'existing',true);
 end if;
 if exists (select 1 from public.invoice_records where company_id=p_company_id and invoice_id=p_invoice_id) then
   raise exception 'Invoice ID already exists' using errcode='23505';
 end if;
 pre:=coalesce(nullif(c.data->>'prefix',''),'INV-');
 if length(pre)>32 then raise exception 'Invoice prefix too long' using errcode='22023'; end if;
 if coalesce(c.data->>'nextNo','') ~ '^[0-9]{1,10}$' then
   start_no:=greatest(1,(c.data->>'nextNo')::bigint);
 else
   start_no:=1001;
 end if;
 select greatest(start_no,coalesce(max(r.sequence_no)+1,start_no))
 into counter from public.invoice_number_reservations r
 where r.company_id=p_company_id and r.prefix=pre;
 for tries in 1..10000 loop
   proposal:=pre||counter::text;
   if length(proposal)>80 then raise exception 'Invoice number exceeds maximum length' using errcode='22023'; end if;
   if not exists (
     select 1 from public.invoice_number_reservations r
     where r.company_id=p_company_id and lower(btrim(r.invoice_number))=lower(btrim(proposal))
   ) and not exists (
     select 1 from public.invoice_records i
     where i.company_id=p_company_id and lower(btrim(i.invoice_number))=lower(btrim(proposal))
   ) and not exists (
     select 1 from jsonb_array_elements(
       case when jsonb_typeof(c.data->'invoices')='array' then c.data->'invoices' else '[]'::jsonb end
     ) entry where lower(btrim(entry->>'number'))=lower(btrim(proposal))
   ) then
     if (select count(*) from public.invoice_number_reservations
         where company_id=p_company_id and reserved_by=auth.uid()
         and reserved_at > now()-interval '1 hour')>=500 then
       raise exception 'Invoice reservation rate limit reached' using errcode='54000';
     end if;
     insert into public.invoice_number_reservations
      (company_id,invoice_id,invoice_number,prefix,sequence_no,reserved_by)
     values (p_company_id,p_invoice_id,proposal,pre,counter,auth.uid());
     return jsonb_build_object('number',proposal,'nextNo',counter+1,'existing',false);
   end if;
   counter:=counter+1;
 end loop;
 raise exception 'Unable to allocate invoice number; contact support' using errcode='54000';
end;
$$;
revoke all on function public.reserve_invoice_number(uuid,text) from public,anon,authenticated;
grant execute on function public.reserve_invoice_number(uuid,text) to authenticated;

-- Refuse a manual/other-invoice save that attempts to claim someone else's reservation.
create or replace function myr_internal.enforce_invoice_reservation()
returns trigger language plpgsql security definer
set search_path=''
as $$
begin
 if exists (
   select 1 from public.invoice_number_reservations r
   where r.company_id=new.company_id
     and lower(btrim(r.invoice_number))=lower(btrim(new.invoice_number))
     and r.invoice_id<>new.invoice_id
 ) then
   raise exception 'Invoice number already reserved for another invoice' using errcode='23505';
 end if;
 return new;
end;
$$;
revoke all on function myr_internal.enforce_invoice_reservation() from public,anon,authenticated;
drop trigger if exists enforce_invoice_reservation_before_write on public.invoice_records;
create trigger enforce_invoice_reservation_before_write
before insert or update of invoice_number on public.invoice_records
for each row execute function myr_internal.enforce_invoice_reservation();
