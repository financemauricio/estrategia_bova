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
from modulos import bs, cotacoes, estrategia, mercado
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

_sem_fonte = [n for n, d in dados.items() if d.get("cotacao", {}).get("confianca") == "sem_dados"]
if _sem_fonte:
    st.warning(
        "Sem fonte ao vivo agora para: **" + ", ".join(_sem_fonte) + "**. "
        "O preço exibido é o último fechamento do histórico — confirme no Home Broker."
    )

_atrasados = [n for n, d in dados.items() if d.get("cotacao", {}).get("possivel_atraso")]
if _atrasados:
    st.info(
        "Mercado aberto e as fontes gratuitas ainda mostram o **fechamento anterior** para: "
        + ", ".join(_atrasados)
        + ". O preço de hoje chega com atraso de até 15 min — use o botão abaixo para buscar de novo."
    )

if st.button("🔄 Forçar atualização agora", help="Limpa o cache e busca as cotações de novo."):
    st.cache_data.clear()
    st.rerun()

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
    _cot = dados[r["ativo"]].get("cotacao", {})
    _conf = _cot.get("confianca")
    _marca = {"alta": "✓", "unica": "1 fonte", "divergente": "⚠"}.get(_conf, "")
    _linhas.append({
        "Ativo": r["ativo"],
        "Preço": mercado.formatar_reais(r.get("preco")),
        "Variação": mercado.variacao_fmt(r.get("variacao_pct", 0.0)),
        "Cotação": f"{cotacoes.hora_curta(_cot)} {_marca}".strip(),
        f"MA{MA_PERIODO}": mercado.formatar_reais(r.get("ma_decisao")),
        "Viés": r["vies"],
        "Ação": ("⚡ " if r["prioridade"] else "") + r["acao"],
        "Strike ref.": mercado.formatar_reais(r.get("strike_sugerido")),
        "Prêmio ref. (teórico)": mercado.formatar_reais(r.get("premio_teorico")),
        "Prob. exercício": prob_badge(r.get("prob_exercicio")),
        "Vol. 20d": f"{r['vol']*100:.1f} %" if r.get("vol") else "—",
    })

st.dataframe(pd.DataFrame(_linhas), width="stretch", hide_index=True)

with st.expander("🔎 De onde vem cada preço"):
    for nome, d in dados.items():
        cot = d.get("cotacao", {})
        detalhes = " · ".join(
            f"{f['fonte']} R$ {f['preco']:.2f}" for f in cot.get("fontes", [])
        )
        st.write(
            f"**{nome}** — {mercado.formatar_reais(d.get('preco'))} · "
            f"{cotacoes.descricao_cotacao(cot)}"
        )
        st.caption(
            (detalhes + " · " if detalhes else "")
            + f"última barra do histórico: {d.get('data_barra', '—')}"
        )
        if cot.get("confianca") == "divergente":
            st.warning(
                f"{nome}: fontes divergem {cot.get('dispersao_pct', 0):.2f} %. "
                "Confirme no Home Broker antes de operar."
            )
        elif cot.get("confianca") == "sem_dados":
            st.warning(f"{nome}: sem cotação confiável agora — usando o fechamento do histórico.")

st.caption(
    f"Prêmio mínimo: {PREMIO_MIN_PCT*100:.1f} % do preço por ciclo · PUT com delta ≈ {DELTA_PUT_ALVO:.2f} · "
    "Prêmio ref. = Black-Scholes com volatilidade histórica (referência, NÃO é o preço do mercado). "
    "Use **Análise do Ativo → Confira o prêmio real** com o bid do Home Broker. "
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
