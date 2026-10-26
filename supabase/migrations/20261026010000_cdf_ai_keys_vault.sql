-- AI service keys saved from the site's AI settings page (cdf_gco_crms/interfaces/ai_settings.py).
-- Keys live in Supabase Vault (encrypted at rest, outside the application's tables). The app's role cdf_app has no
-- access to Vault itself: it can only call these four functions, which touch nothing but the secrets named
-- cdf_ai_key_<service> for the five known services. No key is ever written to an application table or log.

create or replace function cdf.ai_key_set(p_provider text, p_key text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_name text;
  v_id uuid;
begin
  if p_provider not in ('anthropic', 'openai', 'mistral', 'deepseek', 'xai') then
    raise exception 'UNKNOWN_AI_PROVIDER';
  end if;
  if p_key is null or length(p_key) < 16 or length(p_key) > 512 or p_key ~ '\s' then
    raise exception 'INVALID_API_KEY_FORMAT';
  end if;
  v_name := 'cdf_ai_key_' || p_provider;
  select id into v_id from vault.secrets where name = v_name;
  if v_id is null then
    perform vault.create_secret(p_key, v_name, 'CDF_GC_Review: AI service key saved from the settings page');
  else
    perform vault.update_secret(v_id, p_key);
  end if;
end $$;

create or replace function cdf.ai_key_get(p_provider text) returns text
language sql stable security definer set search_path = '' as $$
  select decrypted_secret from vault.decrypted_secrets
  where name = 'cdf_ai_key_' || p_provider
    and p_provider in ('anthropic', 'openai', 'mistral', 'deepseek', 'xai')
$$;

create or replace function cdf.ai_key_clear(p_provider text) returns void
language sql security definer set search_path = '' as $$
  delete from vault.secrets
  where name = 'cdf_ai_key_' || p_provider
    and p_provider in ('anthropic', 'openai', 'mistral', 'deepseek', 'xai')
$$;

create or replace function cdf.ai_key_saved() returns table (provider text, updated_at timestamptz)
language sql stable security definer set search_path = '' as $$
  select substr(name, 12), updated_at from vault.secrets where name like 'cdf\_ai\_key\_%'
$$;

revoke all on function cdf.ai_key_set(text, text) from public, anon, authenticated, service_role;
revoke all on function cdf.ai_key_get(text) from public, anon, authenticated, service_role;
revoke all on function cdf.ai_key_clear(text) from public, anon, authenticated, service_role;
revoke all on function cdf.ai_key_saved() from public, anon, authenticated, service_role;
grant execute on function cdf.ai_key_set(text, text) to cdf_app;
grant execute on function cdf.ai_key_get(text) to cdf_app;
grant execute on function cdf.ai_key_clear(text) to cdf_app;
grant execute on function cdf.ai_key_saved() to cdf_app;
