-- =========================================================
-- Wiipo Recebidos - schema Supabase
-- Controle de recebimento dos cartões de benefícios Wiipo
-- =========================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------
-- Estabelecimentos (unidades)
-- ---------------------------------------------------------
create table if not exists establishments (
    id            uuid primary key default gen_random_uuid(),
    code          text not null,              -- ex: 'GNCF 0015'
    name          text not null,               -- ex: 'Shopping 10'
    cnpj          text,
    empresa       text,                        -- razão social (coluna EMPRESA do CSV)
    raw_label     text not null unique,        -- string original completa (ESTABELECIMENTO), usada para import idempotente
    access_token  uuid not null default gen_random_uuid() unique,  -- token do link/QR do gestor
    created_at    timestamptz not null default now()
);

comment on column establishments.access_token is
    'Token usado na URL enviada ao gestor da unidade (?token=). Não expõe o id interno.';

-- ---------------------------------------------------------
-- Colaboradores
-- ---------------------------------------------------------
create table if not exists employees (
    id                uuid primary key default gen_random_uuid(),
    establishment_id  uuid not null references establishments(id) on delete cascade,
    matricula         text unique,             -- nulo para colaboradores adicionados manualmente pelo gestor
    nome              text not null,
    cargo             text,
    card_received     boolean not null default false,
    received_at       timestamptz,
    updated_by        text,                    -- nome do gestor que fez a última marcação
    manually_added    boolean not null default false,  -- true = incluído pelo gestor, não veio do CSV do RH
    created_at        timestamptz not null default now()
);

create index if not exists idx_employees_establishment on employees(establishment_id);
create index if not exists idx_employees_matricula on employees(matricula);

-- ---------------------------------------------------------
-- Log de acessos ao link do gestor (auditoria simples)
-- ---------------------------------------------------------
create table if not exists access_log (
    id                uuid primary key default gen_random_uuid(),
    establishment_id  uuid not null references establishments(id) on delete cascade,
    accessed_at       timestamptz not null default now(),
    note              text
);

create index if not exists idx_access_log_establishment on access_log(establishment_id);

-- ---------------------------------------------------------
-- View de progresso por estabelecimento (para o painel admin)
-- ---------------------------------------------------------
create or replace view establishment_progress as
select
    e.id,
    e.code,
    e.name,
    e.raw_label,
    e.access_token,
    count(emp.id)                                            as total_employees,
    count(emp.id) filter (where emp.card_received)            as received_count,
    case when count(emp.id) = 0 then 0
         else round(100.0 * count(emp.id) filter (where emp.card_received) / count(emp.id), 1)
    end                                                        as pct_complete,
    e.cnpj
from establishments e
left join employees emp on emp.establishment_id = e.id
group by e.id, e.code, e.name, e.raw_label, e.access_token, e.cnpj
order by e.name;

-- ---------------------------------------------------------
-- Segurança: RLS habilitado, sem policies para anon/authenticated.
-- O app Streamlit acessa via service_role key (nunca exposta ao
-- navegador, pois roda no servidor), então o backend tem acesso
-- total e o restante do mundo não tem nenhum.
-- ---------------------------------------------------------
alter table establishments enable row level security;
alter table employees enable row level security;
alter table access_log enable row level security;

-- (nenhuma policy criada de propósito — apenas service_role passa)
