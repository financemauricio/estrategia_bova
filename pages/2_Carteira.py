"""Carteira — portfolio positions, allocation and contribution calculator."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import ALOCACAO_ALVO, APORTE_MENSAL
from modulos import banco, mercado

st.title("💼 Carteira")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
dados = mercado.buscar_dados_mercado()
posicoes = banco.listar_posicoes()
saldo = banco.saldo_caixa()
patrimonio = mercado.calcular_patrimonio(posicoes, dados)
total_etf = patrimonio["total_etf"]
patrimonio_total = total_etf + saldo

# ---------------------------------------------------------------------------
# Positions table
# ---------------------------------------------------------------------------
st.subheader("Posições Atuais")

if posicoes:
    rows = []
    for pos in posicoes:
        ticker = pos["ticker"]
        qtd    = pos["quantidade"]
        pm_brl = pos["preco_medio"]   # always stored in BRL
        d      = dados.get(ticker, {})
        preco_usd = d.get("preco", 0.0)
        preco_brl = d.get("preco_brl", preco_usd)
        usdbrl    = d.get("usdbrl", 1.0)
        em_usd    = d.get("moeda", "BRL") == "USD"

        valor_brl = qtd * preco_brl

        if em_usd:
            # Convert stored BRL PM to USD using current rate for display
            pm_display       = f"US$ {pm_brl / usdbrl:.2f}" if usdbrl else f"R$ {pm_brl:.2f}"
            preco_display    = f"US$ {preco_usd:.2f}"
            variacao_pm      = (preco_usd - pm_brl / usdbrl) / (pm_brl / usdbrl) if pm_brl and usdbrl else 0.0
        else:
            pm_display       = f"R$ {pm_brl:.2f}"
            preco_display    = f"R$ {preco_brl:.2f}"
            variacao_pm      = (preco_brl - pm_brl) / pm_brl if pm_brl else 0.0

        var_cor = "+" if variacao_pm >= 0 else ""
        rows.append({
            "Ticker":       ticker,
            "Qtd":          f"{qtd:.4f}".rstrip("0").rstrip("."),
            "Preço Pago":   pm_display,
            "Preço Atual":  preco_display,
            "Variação":     f"{var_cor}{variacao_pm*100:.2f} %",
            "Valor (R$)":   f"R$ {valor_brl:,.2f}",
        })

    df_pos = pd.DataFrame(rows)
    fig_pos = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c}</b>" for c in df_pos.columns],
            fill_color="#1a1d27",
            font=dict(color="white", size=13),
            align="center",
            line_color="#333",
        ),
        cells=dict(
            values=[df_pos[c].tolist() for c in df_pos.columns],
            fill_color="#0e1117",
            font=dict(color="white", size=12),
            align="center",
            line_color="#222",
            height=32,
        ),
    ))
    fig_pos.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        height=60 + len(rows) * 36,
    )
    st.plotly_chart(fig_pos, use_container_width=True)
    st.caption("IVV em US$ — PM convertido de R$ para US$ pela taxa atual. Valor Total sempre em R$.")
else:
    st.info("Nenhuma posição registrada. Adicione abaixo.")

# ---------------------------------------------------------------------------
# Allocation chart — actual vs target
# ---------------------------------------------------------------------------
st.subheader("Alocação Atual vs Alvo")

tickers = list(ALOCACAO_ALVO.keys())
alvo_vals = [ALOCACAO_ALVO[t] * 100 for t in tickers]
atual_vals = [patrimonio["alocacao"].get(t, 0) * 100 for t in tickers]

fig = go.Figure()
fig.add_trace(
    go.Bar(name="Alvo %", x=tickers, y=alvo_vals, marker_color="#888888", opacity=0.6)
)
fig.add_trace(
    go.Bar(name="Atual %", x=tickers, y=atual_vals, marker_color="#2ecc71")
)
fig.update_layout(
    barmode="group",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    yaxis_title="% do patrimônio em ETFs",
    height=320,
    margin=dict(t=10, b=10),
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Contribution calculator
# ---------------------------------------------------------------------------
st.subheader("Calculadora de Aporte")

aporte_val = st.number_input(
    "Valor do aporte (R$)",
    min_value=0.0,
    value=APORTE_MENSAL,
    step=100.0,
    format="%.2f",
)

sugestao = mercado.sugerir_alocacao_aporte(aporte_val, patrimonio, saldo, ALOCACAO_ALVO)

cs = st.columns(len(sugestao))
for col, (ticker, valor) in zip(cs, sugestao.items()):
    d = dados.get(ticker, {})
    # IVV: divide BRL amount by BRL-equivalent price to get share quantity
    preco_ref = d.get("preco_brl") or d.get("preco", 0.0)
    qtd = valor / preco_ref if preco_ref else 0.0
    moeda_label = "US$" if d.get("moeda") == "USD" else "R$"
    col.metric(ticker, f"R$ {valor:,.2f}", f"≈ {qtd:.4f} cotas ({moeda_label})")

st.caption(
    "Sugestão calculada para aproximar a alocação atual ao alvo (70/20/10). "
    "Ajuste conforme disponibilidade de lotes."
)

st.divider()

# ---------------------------------------------------------------------------
# Edit / add position
# ---------------------------------------------------------------------------
st.subheader("Registrar / Atualizar Posição")

with st.form("form_posicao", clear_on_submit=True):
    col_a, col_b, col_c = st.columns(3)
    ticker_sel = col_a.selectbox("Ticker", list(ALOCACAO_ALVO.keys()))
    qtd_input = col_b.number_input("Quantidade total de cotas", min_value=0.0, step=1.0, format="%.4f")
    _is_ivv = ticker_sel == "IVV"
    pm_label = "Preço médio (US$) — será convertido para R$" if _is_ivv else "Preço médio (R$)"
    pm_input_raw = col_c.number_input(pm_label, min_value=0.0, step=0.01, format="%.4f")
    # Store IVV PM in BRL (multiply by current USDBRL)
    _usdbrl_now = dados.get("IVV", {}).get("usdbrl", 1.0) if _is_ivv else 1.0
    pm_input = pm_input_raw * _usdbrl_now if _is_ivv else pm_input_raw

    submitted = st.form_submit_button("Salvar posição")
    if submitted:
        banco.upsert_posicao(ticker_sel, qtd_input, pm_input)
        st.success(f"Posição de {ticker_sel} atualizada.")
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Cash balance management
# ---------------------------------------------------------------------------
st.subheader("Caixa")
st.metric("Saldo atual", f"R$ {saldo:,.2f}")

with st.form("form_caixa", clear_on_submit=True):
    cc1, cc2, cc3, cc4 = st.columns([1, 1, 2, 2])
    data_cx = cc1.date_input("Data")
    tipo_cx = cc2.selectbox("Tipo", ["ENTRADA", "SAIDA"])
    valor_cx = cc3.number_input("Valor (R$)", min_value=0.01, step=10.0, format="%.2f")
    desc_cx = cc4.text_input("Descrição")

    if st.form_submit_button("Registrar movimentação"):
        banco.registrar_caixa(str(data_cx), tipo_cx, valor_cx, desc_cx)
        st.success("Movimentação registrada.")
        st.rerun()

mov = banco.listar_caixa(20)
if mov:
    st.dataframe(
        pd.DataFrame(mov)[["data", "tipo", "valor", "descricao"]],
        use_container_width=True,
        hide_index=True,
    )
