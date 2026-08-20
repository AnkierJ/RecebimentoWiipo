"""
Importa/atualiza estabelecimentos e colaboradores no Supabase a partir do
WiipoRecebidos.csv (colunas: EMPRESA;ESTABELECIMENTO;MATRICULA;COLABORADOR;CARGO).

Idempotente: pode ser rodado de novo quando o CSV for atualizado (novas
contratações, mudanças de unidade). Não mexe em card_received/received_at
de colaboradores já existentes.

Credenciais: lidas de .streamlit/secrets.toml (o mesmo arquivo usado pelo
app) se existir; senão, das variáveis de ambiente SUPABASE_URL e
SUPABASE_SERVICE_KEY.

Uso:
    python seed_from_csv.py [caminho_do_csv]
"""
import csv
import os
import re
import sys
import tomllib
from pathlib import Path

from supabase import create_client

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "WiipoRecebidos.csv"
SECRETS_PATH = Path(__file__).parent / ".streamlit" / "secrets.toml"

RAW_LABEL_RE = re.compile(
    r"^(?P<code>\S+\s+\d+)\s*-\s*(?P<name>.+?)\s*-\s*CNPJ\s*:\s*(?P<cnpj>[\d./-]+)\s*$"
)


def parse_establishment(raw_label: str) -> dict:
    m = RAW_LABEL_RE.match(raw_label.strip())
    if not m:
        # fallback: mantém o texto inteiro como nome se o formato não bater
        return {"code": raw_label.strip(), "name": raw_label.strip(), "cnpj": None}
    return {
        "code": m.group("code").strip(),
        "name": m.group("name").strip(),
        "cnpj": m.group("cnpj").strip(),
    }


def load_credentials() -> tuple[str, str]:
    if SECRETS_PATH.exists():
        secrets = tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        url = secrets.get("supabase_url")
        key = secrets.get("supabase_service_key")
        if url and key:
            return url, key

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return url, key

    sys.exit(
        "Credenciais não encontradas. Preencha supabase_url e "
        "supabase_service_key em .streamlit/secrets.toml, ou defina as "
        "variáveis de ambiente SUPABASE_URL e SUPABASE_SERVICE_KEY."
    )


def main():
    url, key = load_credentials()

    client = create_client(url, key)

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    print(f"{len(rows)} linhas lidas de {CSV_PATH}")

    # --- 1. Upsert dos estabelecimentos (únicos por raw_label) ---
    raw_labels = {r["ESTABELECIMENTO"].strip() for r in rows}
    empresa_by_label = {r["ESTABELECIMENTO"].strip(): r["EMPRESA"].strip() for r in rows}

    establishment_payload = []
    for raw_label in sorted(raw_labels):
        parsed = parse_establishment(raw_label)
        establishment_payload.append(
            {
                "raw_label": raw_label,
                "code": parsed["code"],
                "name": parsed["name"],
                "cnpj": parsed["cnpj"],
                "empresa": empresa_by_label[raw_label],
            }
        )

    client.table("establishments").upsert(
        establishment_payload, on_conflict="raw_label"
    ).execute()
    print(f"{len(establishment_payload)} estabelecimentos upsertados")

    # busca os ids gerados/existentes
    existing = client.table("establishments").select("id, raw_label").execute().data
    id_by_label = {row["raw_label"]: row["id"] for row in existing}

    # --- 2. Upsert dos colaboradores (únicos por matricula) ---
    employee_payload = []
    for r in rows:
        label = r["ESTABELECIMENTO"].strip()
        establishment_id = id_by_label.get(label)
        if not establishment_id:
            print(f"AVISO: estabelecimento não encontrado para '{label}', pulando linha")
            continue
        employee_payload.append(
            {
                "matricula": r["MATRICULA"].strip(),
                "nome": r["COLABORADOR"].strip(),
                "cargo": (r.get("CARGO") or "").strip() or None,
                "establishment_id": establishment_id,
                # card_received NÃO é enviado: em caso de conflito, o valor
                # existente na base é preservado (upsert só atualiza colunas
                # presentes no payload).
            }
        )

    batch_size = 500
    for i in range(0, len(employee_payload), batch_size):
        batch = employee_payload[i : i + batch_size]
        client.table("employees").upsert(batch, on_conflict="matricula").execute()
        print(f"  colaboradores {i + 1}-{i + len(batch)} upsertados")

    print(f"{len(employee_payload)} colaboradores upsertados no total")
    print("Importação concluída.")


if __name__ == "__main__":
    main()
