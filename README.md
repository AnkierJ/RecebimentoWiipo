# Wiipo Recebidos

App para conferir se os cartões de benefícios Wiipo chegaram a todos os
colaboradores, unidade por unidade.

- **Visão administradora** (`/`): lista todos os estabelecimentos, gráfico de
  pizza de conclusão (geral e por unidade), e geração de link/QR Code
  individual por estabelecimento.
- **Visão do gestor** (`/?token=...`): lista dos colaboradores da própria
  unidade, com checkbox para marcar quem já recebeu o cartão. Pode ser
  reaberta quantas vezes for preciso para atualizar o progresso.

## 1. Criar a base no Supabase

1. Crie um projeto em [supabase.com](https://supabase.com).
2. Em **SQL Editor**, rode o conteúdo de [`supabase_schema.sql`](supabase_schema.sql).
3. Em **Project Settings > API**, copie a `Project URL` e a `service_role`
   key (não a `anon` key — o app usa a service_role porque roda inteiramente
   no servidor do Streamlit, nunca no navegador do usuário).

## 2. Importar a planilha de colaboradores

```bash
pip install -r requirements.txt
python seed_from_csv.py WiipoRecebidos.csv
```

O script lê as credenciais direto de `.streamlit/secrets.toml` (o mesmo
arquivo do passo 3) se ele já existir. Se preferir não usar o secrets.toml
ainda, dá para passar por variável de ambiente:

```powershell
# PowerShell
$env:SUPABASE_URL = "https://xxxx.supabase.co"
$env:SUPABASE_SERVICE_KEY = "<service_role key>"
python seed_from_csv.py WiipoRecebidos.csv
```

```bash
# bash/zsh
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_SERVICE_KEY="<service_role key>"
python seed_from_csv.py WiipoRecebidos.csv
```

Pode rodar de novo sempre que o CSV for atualizado (admissões/mudanças de
unidade) — colaboradores já marcados como recebidos não são resetados.

## 3. Configurar secrets

Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e
preencha `supabase_url`, `supabase_service_key`, `admin_password` e
`app_base_url` (a URL pública onde o app vai ficar publicado — necessária
para montar os links dos gestores). **Não commite esse arquivo.**

## 4. Rodar localmente

```bash
streamlit run app.py
```

## 5. Publicar em produção

Forma mais rápida: [Streamlit Community Cloud](https://streamlit.io/cloud)
(gratuito).

1. Suba esta pasta para um repositório no GitHub (o `.gitignore` já
   protege o `secrets.toml`).
2. Em share.streamlit.io, clique em **New app**, aponte para o repositório
   e o arquivo `app.py`.
3. Em **Settings > Secrets**, cole o conteúdo do seu `secrets.toml`
   preenchido.
4. Depois do primeiro deploy, copie a URL gerada e atualize `app_base_url`
   nos secrets (ela é usada para montar os links/QR Codes dos gestores).

Alternativas caso prefira não usar o Community Cloud: Streamlit também roda
bem em qualquer PaaS com suporte a Python (Render, Railway, Fly.io) — o
`requirements.txt` e o comando `streamlit run app.py` já são suficientes.

## Fluxo de uso

1. Na visão administradora, gere o link/QR Code de cada estabelecimento e
   envie ao respectivo gestor (junto com os cartões ou por Teams).
2. O gestor abre o link, vê a lista de colaboradores da unidade e marca
   quem já recebeu o cartão.
3. O RH acompanha o progresso geral e por unidade no gráfico de pizza,
   voltando ao painel administrativo sempre que quiser.
4. O mesmo link continua válido para o gestor revisar/atualizar depois.
