-- MYR Invoices security follow-up (2026-11-18)
-- Helper must not inherit caller-controlled search_path.
alter function public.jwt_email() set search_path = pg_catalog, auth;

-- Trigger functions are called by database triggers, not browser RPC.
-- Remove the default PUBLIC EXECUTE privilege.
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.company_after_insert() from public, anon, authenticated;

-- The following exposed SECURITY DEFINER RPCs are intentional:
-- get_public_link and submit_public_link are token-gated buyer access;
-- accept_invites is verified-email/role based;
-- is_member, is_platform_admin and admin_* perform internal authorization checks.
-- Do not grant any of the admin_* functions to anon.
