-- Adiciona o CNPJ à view establishment_progress, necessário para cruzar com a
-- base dCentros (UF e Gerente de núcleo) no painel administrativo.
-- Rode uma vez no SQL Editor do Supabase. Idempotente.

-- Postgres só permite adicionar colunas no FINAL da lista com
-- CREATE OR REPLACE VIEW (mudar a posição/nome de uma coluna existente dá
-- erro 42P16) — por isso `cnpj` vai depois de pct_complete, não no meio.
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
