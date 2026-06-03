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
# Allocation chart — actual vs target + buy-to-rebalance calculator
# ---------------------------------------------------------------------------
st.subheader("Alocação Atual vs Alvo")

tickers = list(ALOCACAO_ALVO.keys())
alvo_vals   = [ALOCACAO_ALVO[t] * 100 for t in tickers]
atual_vals  = [patrimonio["alocacao"].get(t, 0) * 100 for t in tickers]
por_ticker  = patrimonio["por_ticker"]

# Colour each bar: green if at/above target, orange if below
bar_colors = [
    "#2ecc71" if atual_vals[i] >= alvo_vals[i] else "#e67e22"
    for i in range(len(tickers))
]

fig = go.Figure()
fig.add_trace(go.Bar(
    name="Alvo %", x=tickers, y=alvo_vals,
    marker_color="#555", opacity=0.5,
))
fig.add_trace(go.Bar(
    name="Atual %", x=tickers, y=atual_vals,
    marker_color=bar_colors,
))
fig.update_layout(
    barmode="group",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    yaxis_title="% do patrimônio em ETFs",
    height=300,
    margin=dict(t=10, b=10),
)
st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Buy-to-rebalance: exact amount in R$ needed for each under-allocated asset
# (no-sell assumption — only compute purchases for assets below target)
# ---------------------------------------------------------------------------
st.subheader("🛒 Quanto comprar para rebalancear")

# Identify under-allocated assets
under = {t: ALOCACAO_ALVO[t] for t in tickers if por_ticker.get(t, 0) < ALOCACAO_ALVO[t] * total_etf}

if not under:
    st.success("✅ Carteira dentro do alvo — nenhuma compra necessária.")
else:
    # Exact solution (no-sell):
    # New total S = (total_etf - Σv_under) / (1 - Σalvo_under)
    # Buy_i = alvo_i × S - v_i  for each underallocated asset i
    soma_alvo_under  = sum(ALOCACAO_ALVO[t] for t in under)
    soma_valor_under = sum(por_ticker.get(t, 0) for t in under)
    denom = 1 - soma_alvo_under

    if denom <= 0:
        # Edge case: all weight goes to underallocated — buy proportionally
        novo_total = None
    else:
        novo_total = (total_etf - soma_valor_under) / denom

    buy_cols = st.columns(len(under))
    for col, (ticker, alvo_pct) in zip(buy_cols, under.items()):
        valor_atual = por_ticker.get(ticker, 0.0)
        if novo_total:
            comprar_brl = alvo_pct * novo_total - valor_atual
        else:
            comprar_brl = 0.0
        comprar_brl = max(comprar_brl, 0.0)

        d = dados.get(ticker, {})
        preco_brl = d.get("preco_brl") or d.get("preco", 0.0)
        em_usd = d.get("moeda", "BRL") == "USD"
        usdbrl = d.get("usdbrl", 1.0)
        cotas = comprar_brl / preco_brl if preco_brl else 0.0

        if em_usd:
            comprar_usd = comprar_brl / usdbrl
            col.metric(
                f"{ticker}",
                f"R$ {comprar_brl:,.2f}",
                f"≈ US$ {comprar_usd:,.2f} · {cotas:.4f} cotas",
            )
        else:
            col.metric(
                f"{ticker}",
                f"R$ {comprar_brl:,.2f}",
                f"≈ {cotas:.2f} cotas @ R$ {preco_brl:.2f}",
            )

    total_comprar = sum(
        max((ALOCACAO_ALVO[t] * novo_total - por_ticker.get(t, 0.0)), 0.0)
        for t in under
    ) if novo_total else 0.0
    st.caption(
        f"Total a aportar para atingir o alvo: **R$ {total_comprar:,.2f}**. "
        "Cálculo assume que apenas os ativos abaixo do alvo serão comprados, sem vender os demais."
    )

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
