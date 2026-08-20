"""
Wiipo Recebidos - controle de entrega dos cartões de benefícios.

Duas visões no mesmo app, escolhidas pela URL:
  - sem parâmetro `token`  -> visão administradora (RH/gestão)
  - com `?token=<uuid>`    -> visão do gestor da unidade
"""
import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import qrcode
import streamlit as st
from PIL import Image
from supabase import create_client

ASSETS_DIR = Path(__file__).parent / "Assets"

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

    st.subheader("Estabelecimentos")
    search = st.text_input("Filtrar por nome ou código", key="admin_search")
    view_df = df.copy()
    if search:
        mask = view_df["name"].str.contains(search, case=False, na=False) | view_df[
            "code"
        ].str.contains(search, case=False, na=False)
        view_df = view_df[mask]

    st.dataframe(
        view_df[["code", "name", "total_employees", "received_count", "pct_complete"]].rename(
            columns={
                "code": "Código",
                "name": "Unidade",
                "total_employees": "Colaboradores",
                "received_count": "Recebidos",
                "pct_complete": "% Concluído",
            }
        ),
        column_config={
            "% Concluído": st.column_config.ProgressColumn(
                format="%.1f%%", min_value=0, max_value=100
            ),
        },
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
    st.download_button(
        "Baixar todos os links (CSV)", csv_bytes, file_name="links_gestores.csv", mime="text/csv"
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

    st.subheader("Colaboradores adicionados manualmente pelos gestores")
    manual_rows = (
        client.table("employees")
        .select("nome, cargo, updated_by, received_at, establishments(code, name)")
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
                    "Adicionado por": r["updated_by"] or "-",
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

    manager_name = st.text_input(
        "Seu nome (fica registrado como responsável pela confirmação)", key="manager_name"
    )

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
                    if row.cargo:
                        st.caption(row.cargo)
                with col_check:
                    st.checkbox(
                        "Recebeu",
                        value=bool(row.card_received),
                        key=checkbox_key,
                        disabled=bool(row.card_received),
                    )

    if filtered_df.empty:
        st.info("Nenhum colaborador encontrado para essa busca.")

    if st.button("Salvar alterações", type="primary", use_container_width=True):
        ids_to_confirm = [
            emp_id
            for emp_id, already_received in zip(base_df["id"], base_df["card_received"])
            if not already_received and st.session_state.get(f"card_chk_{emp_id}")
        ]
        if ids_to_confirm:
            bulk_update_employees(client, ids_to_confirm, True, manager_name)
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
                        "updated_by": manager_name or None,
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
