"""
Wiipo Recebidos - controle de entrega dos cartões de benefícios.

Duas visões no mesmo app, escolhidas pela URL:
  - sem parâmetro `token`  -> visão administradora (RH/gestão)
  - com `?token=<uuid>`    -> visão do gestor da unidade
"""
import base64
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import openpyxl
import pandas as pd
import plotly.graph_objects as go
import qrcode
import streamlit as st
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas as pdf_canvas
from supabase import create_client

ASSETS_DIR = Path(__file__).parent / "Assets"
DCENTROS_PATH = Path(__file__).parent / "dCentros.xlsx"

NAVY = "#063465"
DEEP_PURPLE = "#422450"
PURPLE = "#6A2CE5"
PENDING_GRAY = "#33395C"


# ---------------------------------------------------------------------
# Helpers de infraestrutura
# ---------------------------------------------------------------------
@st.cache_resource
def get_client():
    return create_client(st.secrets["supabase_url"], st.secrets["supabase_service_key"])


@st.cache_data
def get_base64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def normalize_cnpj(value) -> str:
    return re.sub(r"\D", "", str(value)) if value else ""


@st.cache_data
def load_dcentros_mapping() -> dict:
    """CNPJ -> {uf, gerente_nucleo}, a partir da base dCentros (colunas Q=UF, AB=Gerente de núcleo)."""
    if not DCENTROS_PATH.exists():
        return {}
    wb = openpyxl.load_workbook(DCENTROS_PATH, data_only=True, read_only=True)
    ws = wb["Current view"]
    mapping = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        cnpj = normalize_cnpj(row[12])  # coluna M
        if not cnpj:
            continue
        mapping[cnpj] = {
            "uf": (row[16] or "Sem UF").strip() if isinstance(row[16], str) else (row[16] or "Sem UF"),
            "gerente_nucleo": row[27].strip() if isinstance(row[27], str) and row[27] else "Sem gerente definido",
        }
    return mapping


def render_header(subtitle: str | None = None):
    logo_b64 = get_base64(ASSETS_DIR / "GentilBranco.png")
    wiipo_b64 = get_base64(ASSETS_DIR / "WiipoLogo.png")
    st.markdown(
        f"""
        <div style="background: linear-gradient(120deg, {NAVY} 0%, {DEEP_PURPLE} 55%, {PURPLE} 100%);
                    padding: 1.4rem 2rem; border-radius: 16px; margin-bottom: 1.5rem;
                    display:flex; align-items:center; justify-content:space-between; gap:1rem;
                    flex-wrap: wrap;">
            <img src="data:image/png;base64,{logo_b64}" style="height:40px;" />
            <div style="flex:1; text-align:center; color:white; min-width:220px;">
                <div style="font-size:1.25rem; font-weight:700;">Controle de Recebimento de Cartões</div>
                {f'<div style="opacity:0.85; font-size:0.92rem; margin-top:2px;">{subtitle}</div>' if subtitle else ""}
            </div>
            <img src="data:image/png;base64,{wiipo_b64}" style="height:34px;" />
        </div>
        """,
        unsafe_allow_html=True,
    )


def pie_chart(received: int, pending: int, title: str = "") -> go.Figure:
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Recebido", "Pendente"],
                values=[received, pending],
                hole=0.55,
                marker=dict(colors=[PURPLE, PENDING_GRAY]),
                textinfo="percent",
                sort=False,
            )
        ]
    )
    fig.update_layout(
        title=title,
        height=280,
        margin=dict(t=40, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#F2F1F7"),
        legend=dict(orientation="h", y=-0.12),
    )
    return fig


def make_qr_png(data: str) -> bytes:
    img = qrcode.make(data, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_link(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/?token={token}"


def build_qr_sheet_pdf(establishments: list[dict], base_url: str) -> bytes:
    """PDF em preto e branco, 6 QR Codes por folha A4 (2 colunas x 3 linhas),
    cada um com o código e o nome da unidade abaixo, prontos para impressão e corte."""
    page_w, page_h = A4
    cols, rows_per_page = 2, 3
    margin = 12 * mm
    cell_w = (page_w - 2 * margin) / cols
    cell_h = (page_h - 2 * margin) / rows_per_page
    qr_size = 52 * mm
    per_page = cols * rows_per_page

    buf = BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)

    for i, est in enumerate(establishments):
        pos = i % per_page
        if pos == 0 and i != 0:
            c.showPage()
        col, row = pos % cols, pos // cols
        cell_x = margin + col * cell_w
        cell_y = page_h - margin - (row + 1) * cell_h

        # guia de corte
        c.setStrokeGray(0.75)
        c.setDash(3, 2)
        c.setLineWidth(0.4)
        c.rect(cell_x, cell_y, cell_w, cell_h)
        c.setDash()

        link = build_link(base_url, est["access_token"])
        qr_img = ImageReader(BytesIO(make_qr_png(link)))
        qr_x = cell_x + (cell_w - qr_size) / 2
        qr_y = cell_y + cell_h - 8 * mm - qr_size
        c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

        c.setFillGray(0)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(cell_x + cell_w / 2, qr_y - 6 * mm, est["code"])

        c.setFont("Helvetica", 8)
        name_lines = simpleSplit(est["name"], "Helvetica", 8, cell_w - 8 * mm)[:2]
        text_y = qr_y - 10.5 * mm
        for line in name_lines:
            c.drawCentredString(cell_x + cell_w / 2, text_y, line)
            text_y -= 3.6 * mm

    c.save()
    buf.seek(0)
    return buf.getvalue()


def bulk_update_employees(client, ids: list[str], received: bool, updated_by: str | None):
    if not ids:
        return
    client.table("employees").update(
        {
            "card_received": received,
            "received_at": datetime.now(timezone.utc).isoformat() if received else None,
            "updated_by": updated_by or None,
        }
    ).in_("id", ids).execute()


# ---------------------------------------------------------------------
# Visão administradora
# ---------------------------------------------------------------------
def admin_view(client):
    render_header("Painel administrativo")

    if not st.session_state.get("admin_ok"):
        with st.form("login_form"):
            pwd = st.text_input("Senha de acesso", type="password")
            submitted = st.form_submit_button("Entrar")
        if submitted:
            if pwd and pwd == st.secrets.get("admin_password"):
                st.session_state["admin_ok"] = True
                st.rerun()
            else:
                st.error("Senha incorreta.")
        st.stop()

    try:
        data = client.table("establishment_progress").select("*").execute().data
    except Exception:
        st.error(
            "Não foi possível conectar ao Supabase. Confira `supabase_url` e "
            "`supabase_service_key` em `.streamlit/secrets.toml`."
        )
        st.stop()
    df = pd.DataFrame(data)

    if df.empty:
        st.warning(
            "Nenhum estabelecimento encontrado na base. Rode `seed_from_csv.py` "
            "para importar o CSV antes de usar o painel."
        )
        return

    if "cnpj" in df.columns:
        dcentros = load_dcentros_mapping()
        df["cnpj_norm"] = df["cnpj"].apply(normalize_cnpj)
        df["UF"] = df["cnpj_norm"].map(lambda c: dcentros.get(c, {}).get("uf", "Sem UF"))
        df["Gerente de núcleo"] = df["cnpj_norm"].map(
            lambda c: dcentros.get(c, {}).get("gerente_nucleo", "Sem gerente definido")
        )
    else:
        st.warning(
            "A view `establishment_progress` ainda não tem a coluna `cnpj` — rode "
            "`supabase_migration_cnpj_in_view.sql` no Supabase para habilitar o "
            "agrupamento por UF e Gerente de Núcleo."
        )
        df["UF"] = "Sem UF"
        df["Gerente de núcleo"] = "Sem gerente definido"

    total_emp = int(df["total_employees"].sum())
    total_recv = int(df["received_count"].sum())
    pct = round(100 * total_recv / total_emp, 1) if total_emp else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("Colaboradores", total_emp)
    c2.metric("Cartões recebidos", total_recv)
    c3.metric("Conclusão geral", f"{pct}%")

    st.plotly_chart(
        pie_chart(total_recv, total_emp - total_recv, "Progresso geral"),
        use_container_width=True,
    )

    st.subheader("Estabelecimentos por UF e Gerente de Núcleo")
    search = st.text_input("Filtrar por nome ou código", key="admin_search")
    view_df = df.copy()
    if search:
        mask = view_df["name"].str.contains(search, case=False, na=False) | view_df[
            "code"
        ].str.contains(search, case=False, na=False)
        view_df = view_df[mask]

    unmatched = int((view_df["UF"] == "Sem UF").sum())
    if unmatched:
        st.caption(
            f"⚠️ {unmatched} estabelecimento(s) sem correspondência na base dCentros "
            "(CNPJ não encontrado lá) — agrupado(s) em \"Sem UF\"."
        )

    column_config = {
        "% Concluído": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
    }
    rename_cols = {
        "code": "Código",
        "name": "Unidade",
        "total_employees": "Colaboradores",
        "received_count": "Recebidos",
        "pct_complete": "% Concluído",
    }
    table_cols = ["code", "name", "total_employees", "received_count", "pct_complete"]

    for uf in sorted(view_df["UF"].unique()):
        uf_df = view_df[view_df["UF"] == uf]
        uf_total = int(uf_df["total_employees"].sum())
        uf_recv = int(uf_df["received_count"].sum())
        uf_pct = round(100 * uf_recv / uf_total, 1) if uf_total else 0.0
        with st.expander(f"{uf} — {len(uf_df)} loja(s) — {uf_recv}/{uf_total} recebidos ({uf_pct}%)"):
            for gerente in sorted(uf_df["Gerente de núcleo"].unique()):
                gerente_df = uf_df[uf_df["Gerente de núcleo"] == gerente]
                st.markdown(f"**{gerente}**")
                st.dataframe(
                    gerente_df[table_cols].rename(columns=rename_cols),
                    column_config=column_config,
                    hide_index=True,
                    use_container_width=True,
                )

    base_url = st.secrets.get("app_base_url", "")
    links_df = df[["code", "name", "access_token"]].copy()
    links_df["Link do gestor"] = links_df["access_token"].apply(lambda t: build_link(base_url, t))
    csv_bytes = (
        links_df[["code", "name", "Link do gestor"]]
        .rename(columns={"code": "Código", "name": "Unidade"})
        .to_csv(index=False)
        .encode("utf-8")
    )
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            "Baixar todos os links (CSV)",
            csv_bytes,
            file_name="links_gestores.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl_col2:
        if st.button("Gerar PDF com todos os QR Codes", use_container_width=True):
            with st.spinner("Gerando PDF..."):
                records = df.sort_values("name").to_dict("records")
                st.session_state["qr_pdf_bytes"] = build_qr_sheet_pdf(records, base_url)
        if st.session_state.get("qr_pdf_bytes"):
            st.download_button(
                "Baixar PDF (6 por folha A4, P&B)",
                st.session_state["qr_pdf_bytes"],
                file_name="qrcodes_estabelecimentos.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

    st.subheader("Gerar QR Code / link de um estabelecimento")
    df_sorted = df.sort_values("name")
    options = {f"{row.code} - {row.name}": row for row in df_sorted.itertuples()}
    choice = st.selectbox("Estabelecimento", list(options.keys()))
    row = options[choice]
    link = build_link(base_url, row.access_token)

    col_chart, col_link = st.columns([1, 1])
    with col_chart:
        st.plotly_chart(
            pie_chart(row.received_count, row.total_employees - row.received_count, choice),
            use_container_width=True,
        )
    with col_link:
        st.write("**Link para o gestor:**")
        st.code(link, language=None)
        qr_bytes = make_qr_png(link)
        st.image(qr_bytes, caption="QR Code da unidade", width=220)
        st.download_button(
            "Baixar QR Code (PNG)",
            qr_bytes,
            file_name=f"qrcode_{row.code}.png",
            mime="image/png",
        )
        st.caption(
            "Envie este link ou QR Code ao gestor da unidade (junto com os cartões ou pelo Teams). "
            "O gestor pode voltar a ele quantas vezes precisar para atualizar o progresso."
        )

    st.markdown(f"**Detalhamento — {choice}**")
    detail_rows = (
        client.table("employees")
        .select("nome, cargo, card_received, received_at, updated_by, manually_added")
        .eq("establishment_id", row.id)
        .order("nome")
        .execute()
        .data
    )
    detail_df = pd.DataFrame(detail_rows)

    if detail_df.empty:
        st.caption("Nenhum colaborador cadastrado nesta unidade.")
    else:
        received_df = detail_df[detail_df["card_received"]].copy()
        pending_df = detail_df[~detail_df["card_received"]].copy()

        tab_received, tab_pending = st.tabs(
            [f"✅ Recebido ({len(received_df)})", f"⬜ Pendente ({len(pending_df)})"]
        )
        with tab_received:
            if received_df.empty:
                st.caption("Ninguém confirmado ainda nesta unidade.")
            else:
                received_df["Origem"] = received_df["manually_added"].apply(
                    lambda m: "Adicionado pelo gestor" if m else "Lista do RH"
                )
                st.dataframe(
                    received_df.rename(
                        columns={
                            "nome": "Colaborador",
                            "cargo": "Cargo",
                            "received_at": "Recebido em",
                        }
                    )[["Colaborador", "Cargo", "Recebido em", "Origem"]],
                    hide_index=True,
                    use_container_width=True,
                )
        with tab_pending:
            if pending_df.empty:
                st.caption("Todo mundo já recebeu nesta unidade.")
            else:
                st.dataframe(
                    pending_df.rename(columns={"nome": "Colaborador", "cargo": "Cargo"})[
                        ["Colaborador", "Cargo"]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

    st.subheader("Colaboradores adicionados manualmente pelos gestores")
    manual_rows = (
        client.table("employees")
        .select("nome, cargo, received_at, establishments(code, name)")
        .eq("manually_added", True)
        .order("received_at", desc=True)
        .execute()
        .data
    )
    if manual_rows:
        manual_df = pd.DataFrame(
            [
                {
                    "Unidade": f"{r['establishments']['code']} - {r['establishments']['name']}"
                    if r.get("establishments")
                    else "-",
                    "Colaborador": r["nome"],
                    "Cargo": r["cargo"],
                    "Data": r["received_at"],
                }
                for r in manual_rows
            ]
        )
        st.dataframe(manual_df, hide_index=True, use_container_width=True)
        st.caption(
            "Esses colaboradores não vieram do CSV do RH — foram incluídos diretamente pelo "
            "gestor da unidade porque receberam o cartão mas não estavam na listagem original. "
            "Vale conferir/consolidar com o cadastro do RH."
        )
    else:
        st.caption("Nenhum colaborador adicionado manualmente até o momento.")

    st.divider()
    if st.button("Sair do painel"):
        st.session_state["admin_ok"] = False
        st.rerun()


# ---------------------------------------------------------------------
# Visão do gestor da unidade
# ---------------------------------------------------------------------
def manager_view(client, token: str):
    try:
        est_rows = (
            client.table("establishments").select("*").eq("access_token", token).execute().data
        )
    except Exception:
        render_header()
        st.error("Não foi possível conectar à base de dados. Tente novamente em instantes.")
        return

    if not est_rows:
        render_header()
        st.error("Link inválido. Confira o link/QR Code recebido ou fale com o RH.")
        return

    est = est_rows[0]
    render_header(f"{est['code']} · {est['name']}")

    log_flag = f"logged_{est['id']}"
    if not st.session_state.get(log_flag):
        client.table("access_log").insert({"establishment_id": est["id"]}).execute()
        st.session_state[log_flag] = True

    emp_rows = (
        client.table("employees")
        .select("id, matricula, nome, cargo, card_received")
        .eq("establishment_id", est["id"])
        .order("nome")
        .execute()
        .data
    )
    base_df = pd.DataFrame(emp_rows)

    if base_df.empty:
        st.warning("Nenhum colaborador cadastrado nesta unidade.")
        return

    total = len(base_df)
    received = int(base_df["card_received"].sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Colaboradores", total)
    c2.metric("Recebidos", received)
    c3.metric("Conclusão", f"{round(100 * received / total, 1)}%")
    st.progress(received / total if total else 0.0)

    search = st.text_input("Buscar colaborador por nome", key="manager_search")
    filtered_df = base_df.copy()
    if search:
        filtered_df = filtered_df[filtered_df["nome"].str.contains(search, case=False, na=False)]
    filtered_df = filtered_df.reset_index(drop=True)

    if st.button("Marcar todos (filtrados) como recebido", use_container_width=True):
        for emp_id, already_received in zip(filtered_df["id"], filtered_df["card_received"]):
            if not already_received:
                st.session_state[f"card_chk_{emp_id}"] = True
        st.rerun()

    st.caption(
        "Marque quem recebeu o cartão e clique em **Salvar alterações** no fim da lista. "
        "Uma vez salvo, a confirmação não pode ser desfeita por aqui — se marcou alguém "
        "por engano, entre em contato pelo telefone abaixo."
    )

    st.divider()

    list_box = st.container(height=420, border=False)
    with list_box:
        for row in filtered_df.itertuples():
            checkbox_key = f"card_chk_{row.id}"
            with st.container(border=True):
                col_info, col_check = st.columns([0.72, 0.28], vertical_alignment="center")
                with col_info:
                    icon = "✅" if row.card_received else "⬜"
                    st.markdown(f"**{icon} {row.nome}**")
                    #if row.cargo:
                        #st.caption(row.cargo)
                with col_check:
                    st.checkbox(
                        "Recebeu",
                        value=bool(row.card_received),
                        key=checkbox_key,
                        disabled=bool(row.card_received),
                    )

    if filtered_df.empty:
        st.info("Nenhum colaborador encontrado para essa busca.")

    st.markdown(
        """
        <style>
        div.st-key-sticky_save_bar {
            position: fixed;
            left: 0;
            right: 0;
            bottom: 0;
            z-index: 999;
            padding: 0.75rem 1rem calc(0.75rem + env(safe-area-inset-bottom));
            background: var(--background-color, #0B1330);
            box-shadow: 0 -4px 16px rgba(0,0,0,0.35);
        }
        </style>
        <div style="height:5rem;"></div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="sticky_save_bar"):
        if st.button("Salvar alterações", type="primary", use_container_width=True):
            ids_to_confirm = [
                emp_id
                for emp_id, already_received in zip(base_df["id"], base_df["card_received"])
                if not already_received and st.session_state.get(f"card_chk_{emp_id}")
            ]
            if ids_to_confirm:
                bulk_update_employees(client, ids_to_confirm, True, None)
                st.success(f"{len(ids_to_confirm)} confirmação(ões) salva(s) com sucesso.")
                st.rerun()
            else:
                st.info("Nenhuma marcação nova para salvar.")

    st.divider()
    with st.expander("Colaborador recebeu o cartão mas não está na lista? Adicione aqui"):
        with st.form("add_employee_form", clear_on_submit=True):
            new_nome = st.text_input("Nome do colaborador")
            new_cargo = st.text_input("Cargo (opcional)")
            add_submitted = st.form_submit_button("Adicionar como recebido", type="primary")
        if add_submitted:
            if new_nome.strip():
                client.table("employees").insert(
                    {
                        "establishment_id": est["id"],
                        "nome": new_nome.strip(),
                        "cargo": new_cargo.strip() or None,
                        "card_received": True,
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "manually_added": True,
                    }
                ).execute()
                st.success(f"{new_nome.strip()} adicionado(a) à lista.")
                st.rerun()
            else:
                st.warning("Informe ao menos o nome do colaborador.")

    st.markdown(
        f"""
        <div style="background:rgba(106,44,229,0.12); border:1px solid rgba(106,44,229,0.4);
                    border-radius:10px; padding:0.9rem 1.1rem; margin-top:0.8rem; font-size:0.92rem;">
            Algum colaborador listado foi desligado ou precisa de algum tipo de suporte?
            Entre em contato com
            <a href="tel:+5584936180447" style="color:{PURPLE}; font-weight:600;">+55 84 93618-0447</a>.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "Você pode voltar a este mesmo link/QR Code a qualquer momento para conferir "
        "ou atualizar o progresso da unidade."
    )


# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Wiipo Recebidos",
        page_icon=Image.open(ASSETS_DIR / "WiipoLogo.png"),
        layout="wide",
    )
    client = get_client()
    token = st.query_params.get("token")
    if token:
        manager_view(client, token)
    else:
        admin_view(client)


if __name__ == "__main__":
    main()
