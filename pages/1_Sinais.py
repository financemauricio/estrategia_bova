"""Sinais — one row per asset: bias, action, suggested strike and premium."""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh

    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

from config import (
    DELTA_PUT_ALVO,
    DIAS_VENCIMENTO_PADRAO,
    MA_PERIODO,
    PREMIO_MIN_PCT,
    REFRESH_INTERVAL_SECONDS,
)
from modulos import bs, estrategia, mercado
from modulos.componentes import prob_badge

if _HAS_AUTOREFRESH:
    try:
        _st_autorefresh(interval=REFRESH_INTERVAL_SECONDS * 1_000, key="sinais_refresh")
    except Exception:
        pass

st.title("📊 Sinais de Opções")
st.caption("Somente leitura de mercado — nada seu é salvo, nem posições, nem valores.")

with st.spinner("Buscando cotações..."):
    dados = mercado.buscar_dados_mercado()
    selic = bs.buscar_selic()

if not dados:
    st.error("Não foi possível obter cotações agora. Tente novamente em alguns minutos.")
    st.stop()

dias = st.slider(
    "Dias até o vencimento",
    min_value=7,
    max_value=60,
    value=DIAS_VENCIMENTO_PADRAO,
    step=1,
    help="Usado para calcular strike e prêmio teórico.",
)

resultados = estrategia.avaliar_carteira(dados, selic, dias)

prioridades = [r for r in resultados if r["prioridade"] and r["acao"] != "AGUARDAR"]
vender = [r for r in resultados if r["acao"] != "AGUARDAR"]

k1, k2, k3 = st.columns(3)
k1.metric("Ativos monitorados", len(resultados))
k2.metric("Com operação sugerida", len(vender))
k3.metric("Prioridade máxima", len(prioridades), help="Movimento forte no dia, na direção do viés.")

if prioridades:
    nomes = ", ".join(r["ativo"] for r in prioridades)
    st.success(f"⚡ Prioridade máxima: {nomes} — movimento forte no dia.")

st.divider()

_linhas = []
for r in resultados:
    _linhas.append({
        "Ativo": r["ativo"],
        "Preço": mercado.formatar_reais(r.get("preco")),
        "Variação": mercado.variacao_fmt(r.get("variacao_pct", 0.0)),
        f"MA{MA_PERIODO}": mercado.formatar_reais(r.get("ma_decisao")),
        "Viés": r["vies"],
        "Ação": ("⚡ " if r["prioridade"] else "") + r["acao"],
        "Strike": mercado.formatar_reais(r.get("strike_sugerido")),
        "Prêmio teórico": mercado.formatar_reais(r.get("premio_teorico")),
        "Prob. exercício": prob_badge(r.get("prob_exercicio")),
        "Vol. 20d": f"{r['vol']*100:.1f} %" if r.get("vol") else "—",
    })

st.dataframe(pd.DataFrame(_linhas), width="stretch", hide_index=True)

st.caption(
    f"Prêmio mínimo: {PREMIO_MIN_PCT*100:.1f} % do preço por ciclo · PUT com delta ≈ {DELTA_PUT_ALVO:.2f} · "
    "Prêmio teórico via Black-Scholes (vol. histórica 20d + Selic). "
    "Confirme sempre o bid real no Home Broker antes de operar."
)

st.divider()
st.subheader("Leitura rápida")

for r in resultados:
    icone = "🔴" if r["vies"] == "PUT" else ("🟢" if r["vies"] == "CALL" else "⚪")
    with st.expander(f"{icone} {r['ativo']} — {r['acao']}", expanded=r["prioridade"]):
        st.write(r["mensagem"])
        for p in r["passos"]:
            st.write(("✅" if p["ok"] else "❌") + f" **{p['titulo']}** — {p['texto']}")

st.caption(
    f"Atualização a cada {REFRESH_INTERVAL_SECONDS // 60} min — "
    f"{time.strftime('%d/%m/%Y %H:%M')} · veja a aba **A Regra** para o passo a passo."
)
