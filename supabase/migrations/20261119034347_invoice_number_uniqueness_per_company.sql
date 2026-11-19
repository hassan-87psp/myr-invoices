-- Prevent concurrent or accidental reuse of the same invoice number within one tenant.
-- Applied to MYR INVOICES Supabase as migration 20261119034347.
create unique index if not exists invoice_records_company_number_uq
  on public.invoice_records(company_id, lower(btrim(invoice_number)))
  where btrim(invoice_number) <> '';
