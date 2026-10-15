"""Entry point — defines Streamlit navigation and initialises the database."""

import streamlit as st

st.set_page_config(
    page_title="ETF + Opções",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialise DB tables on first run (idempotent).
# Degraded mode: if the database is unreachable (e.g. Supabase paused),
# the app still opens — each page shows market data when possible and a
# friendly DB error instead of a blank/red screen.
try:
    from modulos.banco import init_db
    init_db()
    st.session_state["db_ok"] = True
    st.session_state.pop("db_erro", None)
except Exception as e:
    st.session_state["db_ok"] = False
    st.session_state["db_erro"] = str(e)
    st.warning(
        "⚠️ Banco de dados indisponível — rodando em modo degradado "
        "(cotações visíveis, carteira/paineis pausados). "
        "Verifique o Supabase (projeto pausado?) e os Secrets, depois recarregue."
    )

pages = [
    st.Page("pages/1_Dashboard.py",      title="Dashboard",       icon="📊"),
    st.Page("pages/2_Carteira.py",        title="Carteira",        icon="💼"),
    st.Page("pages/3_Analise_Semanal.py", title="Análise Semanal", icon="📅"),
]

pg = st.navigation(pages)
pg.run()
