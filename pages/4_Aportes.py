"""Aportes — monthly contribution log and totals."""

from __future__ import annotations

import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from config import ALOCACAO_ALVO, APORTE_MENSAL
from modulos import banco, mercado

st.title("💰 Aportes")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
dados = mercado.buscar_dados_mercado()
total_ap = banco.total_aportado()
total_pr = banco.total_premios_recebidos()
aportes = banco.listar_aportes()

k1, k2, k3 = st.columns(3)
k1.metric("Total aportado", f"R$ {total_ap:,.2f}")
k2.metric("Total de prêmios recebidos", f"R$ {total_pr:,.2f}")
k3.metric("Soma total investida", f"R$ {total_ap + total_pr:,.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Register new contribution
# ---------------------------------------------------------------------------
st.subheader("Registrar Aporte Mensal")

with st.form("form_aporte", clear_on_submit=True):
    fa1, fa2 = st.columns(2)
    data_ap = fa1.date_input("Data", value=datetime.date.today())
    valor_total_ap = fa2.number_input(
        "Valor total (R$)", min_value=0.01, value=APORTE_MENSAL, step=100.0, format="%.2f"
    )

    st.markdown("**Distribuição por ticker**")
    fb1, fb2, fb3 = st.columns(3)

    # Suggest split from current allocation
    posicoes = banco.listar_posicoes()
    saldo = banco.saldo_caixa()
    pat = mercado.calcular_patrimonio(posicoes, dados)
    sug = mercado.sugerir_alocacao_aporte(valor_total_ap, pat, saldo, ALOCACAO_ALVO)

    bova_val = fb1.number_input(
        "BOVA11 — R$", min_value=0.0, value=sug.get("BOVA11", 0.0), step=10.0, format="%.2f"
    )
    ivvb_val = fb2.number_input(
        "IVVB11 — R$", min_value=0.0, value=sug.get("IVVB11", 0.0), step=10.0, format="%.2f"
    )
    hash_val = fb3.number_input(
        "HASH11 — R$", min_value=0.0, value=sug.get("HASH11", 0.0), step=10.0, format="%.2f"
    )

    # Compute quantities from market price
    def _qtd(ticker: str, valor: float) -> float:
        p = dados.get(ticker, {}).get("preco", 0.0)
        return valor / p if p else 0.0

    st.caption(
        f"BOVA11 ≈ {_qtd('BOVA11', bova_val):.2f} cotas | "
        f"IVVB11 ≈ {_qtd('IVVB11', ivvb_val):.2f} cotas | "
        f"HASH11 ≈ {_qtd('HASH11', hash_val):.2f} cotas"
    )

    obs_ap = st.text_input("Observação")

    if st.form_submit_button("Registrar aporte"):
        banco.inserir_aporte(
            data=str(data_ap),
            valor_total=valor_total_ap,
            bova11_qtd=_qtd("BOVA11", bova_val),
            bova11_valor=bova_val,
            ivvb11_qtd=_qtd("IVVB11", ivvb_val),
            ivvb11_valor=ivvb_val,
            hash11_qtd=_qtd("HASH11", hash_val),
            hash11_valor=hash_val,
            observacao=obs_ap,
        )
        st.success(f"Aporte de R$ {valor_total_ap:,.2f} registrado.")
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Contribution history table
# ---------------------------------------------------------------------------
st.subheader("Histórico de Aportes")

if aportes:
    df = pd.DataFrame(aportes)

    # Cumulative sum chart
    df_sorted = df.sort_values("data")
    df_sorted["acumulado"] = df_sorted["valor_total"].cumsum()
    fig = px.area(
        df_sorted,
        x="data",
        y="acumulado",
        labels={"acumulado": "Acumulado (R$)", "data": "Data"},
        color_discrete_sequence=["#2ecc71"],
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
        margin=dict(t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Table
    display_cols = [
        "data", "valor_total",
        "bova11_valor", "bova11_qtd",
        "ivvb11_valor", "ivvb11_qtd",
        "hash11_valor", "hash11_qtd",
        "observacao",
    ]
    existing = [c for c in display_cols if c in df.columns]
    st.dataframe(df[existing], use_container_width=True, hide_index=True)
else:
    st.info("Nenhum aporte registrado ainda.")
