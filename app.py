"""Entry point — Streamlit navigation. Read-only market signals, no database."""

import streamlit as st

from config import APP_VERSION

st.set_page_config(
    page_title="Sinais de Opções",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("pages/1_Sinais.py", title="Sinais", icon="📊"),
    st.Page("pages/2_Analise_Ativo.py", title="Análise do Ativo", icon="🔍"),
    st.Page("pages/3_Regra.py", title="A Regra", icon="📐"),
]

pg = st.navigation(pages)
st.sidebar.caption(f"versão {APP_VERSION}")
pg.run()
