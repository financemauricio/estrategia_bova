"""Entry point — defines Streamlit navigation and initialises the database."""

import streamlit as st

st.set_page_config(
    page_title="ETF + Opções",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialise DB tables on first run (idempotent)
try:
    from modulos.banco import init_db
    init_db()
except Exception as e:
    st.error(f"Erro ao conectar ao banco de dados: {e}")
    st.info(
        "Configure a variável DATABASE_URL em `.streamlit/secrets.toml` "
        "(local) ou no painel Secrets do Streamlit Cloud."
    )
    st.stop()

pages = [
    st.Page("pages/1_Dashboard.py",      title="Dashboard",       icon="📊"),
    st.Page("pages/2_Carteira.py",        title="Carteira",        icon="💼"),
    st.Page("pages/3_Analise_Semanal.py", title="Análise Semanal", icon="📅"),
]

pg = st.navigation(pages)
pg.run()
