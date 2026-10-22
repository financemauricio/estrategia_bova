"""Análise do ativo — chart with MAs and the option suggestion in detail."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    DIAS_VENCIMENTO_PADRAO,
    MA_PERIODO,
    MA_VISUALIZACAO,
    PREMIO_MIN_PCT,
)
from modulos import bs, estrategia, mercado
from modulos.componentes import distancia_strike, prob_badge

st.title("🔍 Análise do Ativo")

dados = mercado.buscar_dados_mercado()
if not dados:
    st.error("Não foi possível obter cotações agora.")
    st.stop()

selic = bs.buscar_selic()

ativo = st.selectbox("Ativo", list(dados.keys()))
d = dados[ativo]
dias = st.slider("Dias até o vencimento", 7, 60, DIAS_VENCIMENTO_PADRAO, 1)
r = estrategia.avaliar_ativo(ativo, d, selic, dias)

preco = d.get("preco")
ma = d.get("ma_decisao")
var = d.get("variacao_pct", 0.0)

# ── KPIs ──────────────────────────────────────────────────────────────────────
a, b, c, e = st.columns(4)
a.metric("Preço", mercado.formatar_reais(preco), mercado.variacao_fmt(var))
b.metric(
    f"MA{MA_PERIODO}",
    mercado.formatar_reais(ma),
    f"{(preco - ma) / ma * 100:+.1f} %" if preco and ma else "—",
    delta_color="normal" if preco and ma and preco > ma else "inverse",
)
c.metric("Volatilidade 20d", f"{d['vol']*100:.1f} % a.a." if d.get("vol") else "—")
e.metric("Selic", f"{selic*100:.2f} % a.a.")

_fonte = d.get("fonte_preco", "yfinance")
if _fonte == "brapi":
    st.caption("Cotação de hoje corrigida via brapi (barra parcial do Yahoo).")
elif _fonte == "yfinance*":
    st.caption("Pregão de hoje ainda indisponível — usando o fechamento anterior.")

# ── Chart ─────────────────────────────────────────────────────────────────────
hist = d.get("hist")
if hist is not None and not hist.empty:
    df_chart = hist.tail(90).copy()
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df_chart.index,
            open=df_chart["Open"], high=df_chart["High"],
            low=df_chart["Low"], close=df_chart["Close"],
            name=ativo,
            increasing_line_color="#2ecc71",
            decreasing_line_color="#e74c3c",
        )
    )
    _estilos = {
        50: {"color": "#2ecc71", "dash": "solid", "width": 2},
        100: {"color": "#f39c12", "dash": "dot", "width": 2},
        200: {"color": "#e74c3c", "dash": "dashdot", "width": 1},
    }
    for janela in MA_VISUALIZACAO:
        col = f"MA{janela}"
        if col in hist.columns:
            est = _estilos.get(janela, {"color": "#888", "dash": "dot", "width": 1})
            fig.add_trace(
                go.Scatter(
                    x=df_chart.index, y=hist[col].tail(90).values,
                    mode="lines", name=f"MA{janela}" + (" ★" if janela == MA_PERIODO else ""),
                    line=dict(color=est["color"], width=est["width"], dash=est["dash"]),
                )
            )
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=10, b=10),
        yaxis_title="R$",
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(f"★ MA{MA_PERIODO} é a média de decisão. Últimos 90 pregões.")

st.divider()

# ── Suggestion ────────────────────────────────────────────────────────────────
st.subheader("Sugestão da regra")

if r["acao"] == "AGUARDAR":
    st.warning(r["mensagem"])
else:
    cor = "error" if r["vies"] == "PUT" else "success"
    getattr(st, cor)(f"**{r['acao']}** — {r['mensagem']}")

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Strike sugerido", mercado.formatar_reais(r["strike_sugerido"]))
    s2.metric("Prêmio teórico", mercado.formatar_reais(r["premio_teorico"]))
    s3.metric("Prob. exercício", prob_badge(r["prob_exercicio"]))
    if preco and r["strike_sugerido"]:
        s4.metric("Distância", distancia_strike(r["vies"], preco, r["strike_sugerido"]))

    st.markdown(
        f"""
| Item | Referência |
|---|---|
| Viés | **{r['vies']}** ({'abaixo' if r['vies'] == 'PUT' else 'acima'} da MA{MA_PERIODO}) |
| Strike | R$ {r['strike_sugerido']:.2f} |
| Prêmio mínimo aceitável | {PREMIO_MIN_PCT*100:.1f} % do preço (R$ {r.get('premio_min', 0):.2f}/cota) |
| Prêmio teórico | R$ {r['premio_teorico']:.2f}/cota |
| Vencimento considerado | {dias} dias |
"""
    )
    st.info(
        "Próximo passo: abra o Home Broker, localize a série nesse strike/vencimento, "
        "confirme o **bid real** e só então decida. Se o bid estiver abaixo do mínimo, não opere."
    )

for p in r["passos"]:
    st.write(("✅" if p["ok"] else "❌") + f" **{p['titulo']}** — {p['texto']}")
