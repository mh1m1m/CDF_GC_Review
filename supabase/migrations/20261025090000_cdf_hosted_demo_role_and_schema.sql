-- Hosted synthetic demo (CDF_GC_Review). Applied to the Supabase project on 2026-10-25.
-- The API connects as cdf_app and keeps all of its tables in schema cdf; it creates them itself on first start
-- (cdf_gco_crms/storage.py translates the engine's DDL). The role's password is set out of band, never here.
-- Schema cdf is not exposed through the Data API (only public and graphql_public are), and anon/authenticated
-- get no rights on it.
create schema if not exists cdf;
revoke all on schema cdf from public;
revoke all on schema cdf from anon, authenticated;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'cdf_app') then
    create role cdf_app login noinherit nocreatedb nocreaterole connection limit 30;
  end if;
end $$;

grant usage, create on schema cdf to cdf_app;
alter role cdf_app set search_path = cdf;
alter role cdf_app set statement_timeout = '60s';
alter role cdf_app set idle_in_transaction_session_timeout = '120s';
comment on schema cdf is 'CDF_GC_Review hosted synthetic demo: SYN- cases only, owned by role cdf_app';
