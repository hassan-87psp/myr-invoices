-- Isolated, empty pilot store. Never apply to production.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'myr_lhdn_sandbox' OR current_user<>'myr_lhdn_sandbox_admin' OR inet_server_addr() IS NOT NULL THEN
   RAISE EXCEPTION 'Private Sandbox database and owner required';
 END IF;
END $$;
CREATE SCHEMA myr_native;
CREATE TABLE myr_native.users(
 id uuid PRIMARY KEY,email text UNIQUE NOT NULL,
 disabled boolean NOT NULL DEFAULT false,email_verified_at timestamptz,
 is_platform_admin boolean NOT NULL DEFAULT false);
CREATE TABLE myr_native.companies(
 id uuid PRIMARY KEY,version bigint NOT NULL DEFAULT 1,tin text NOT NULL,
 status text NOT NULL DEFAULT 'active',data jsonb NOT NULL);
CREATE TABLE myr_native.company_members(
 company_id uuid REFERENCES myr_native.companies(id),email text REFERENCES myr_native.users(email),
 role text NOT NULL,status text NOT NULL,PRIMARY KEY(company_id,email));
CREATE TABLE myr_native.lhdn_documents(
 company_id uuid REFERENCES myr_native.companies(id),invoice_id text NOT NULL,
 PRIMARY KEY(company_id,invoice_id));
REVOKE ALL ON SCHEMA myr_native FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA myr_native FROM PUBLIC;
COMMIT;
