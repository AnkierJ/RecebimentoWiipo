-- Migração para bases já criadas com a versão anterior do supabase_schema.sql.
-- Rode uma vez no SQL Editor do Supabase. Idempotente (pode rodar de novo sem erro).

alter table employees alter column matricula drop not null;

alter table employees
    add column if not exists manually_added boolean not null default false;
