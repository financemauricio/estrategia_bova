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
    DELTA_CALL_RENDA,
    DELTA_PUT_RENDA,
    DIAS_VENCIMENTO_PADRAO,
    MA_PERIODO,
    PREMIO_MIN_ESTICADO_PCT,
    PREMIO_MIN_RENDA_PCT,
    REFRESH_INTERVAL_SECONDS,
)
from modulos import alertas, bs, cadeia, cotacoes, estrategia, mercado
from modulos.componentes import prob_badge
from notificar import verificar_alertas_streamlit

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

with st.spinner("Buscando os prêmios reais de fechamento..."):
    cads = {nome: cadeia.cadeia(nome) for nome in dados}
for r in resultados:
    r["mercado"] = cadeia.resumo_premio(
        cads.get(r["ativo"], {}),
        r["vies"],
        r.get("preco"),
        dias,
        selic,
        strike_ref=r.get("strike_sugerido"),
    )

# Alerta automático enquanto o painel estiver aberto. Usa os secrets que já
# existem no Streamlit Cloud; não precisa de GitHub Actions para este caminho.
_assunto_alerta = verificar_alertas_streamlit(
    resultados,
    selic,
    mercados={r["ativo"]: (r.get("mercado") or {}) for r in resultados},
)
if _assunto_alerta:
    st.toast(f"📧 Alerta enviado: {_assunto_alerta}", icon="📧")

with st.expander("📧 Alertas por e-mail"):
    if alertas.configurado():
        st.caption(
            "Enquanto este painel estiver aberto, ele verifica os sinais a cada "
            "atualização e envia quando o movimento de 2 % confirma o viés da MA50. "
            "Para rodar com o painel fechado, use o GitHub Actions."
        )
        if st.button("Enviar e-mail de teste", key="teste_email_sinais"):
            _ok, _erro = alertas.email_teste(alertas.configuracao().get("app_url", ""))
            if _ok:
                st.success("Teste enviado. Confira a caixa de entrada.")
            else:
                st.error(f"Falha ao enviar: {_erro}")
    else:
        st.caption(
            "E-mail ainda não configurado nos Secrets do Streamlit Cloud. "
            "Cadastre EMAIL_REMETENTE, EMAIL_SENHA e EMAIL_DESTINATARIO."
        )

prioridades = [r for r in resultados if r["prioridade"] and r["acao"] != "AGUARDAR"]
vender = [r for r in resultados if r["acao"] != "AGUARDAR"]

k1, k2, k3 = st.columns(3)
k1.metric("Ativos monitorados", len(resultados))
k2.metric("Com operação sugerida", len(vender))
k3.metric("Prioridade máxima", len(prioridades), help="Movimento forte no dia, na direção do viés.")

if prioridades:
    nomes = ", ".join(r["ativo"] for r in prioridades)
    st.success(f"⚡ Prioridade máxima: {nomes} — movimento forte no dia.")

_esticados = [r for r in resultados if r.get("modo") == "ESTICADO" and r["acao"] != "AGUARDAR"]
if _esticados:
    nomes = ", ".join(r["ativo"] for r in _esticados)
    st.info(
        f"🔥 Modo esticado: {nomes} — o ativo subiu muito e a CALL vai para "
        f"+3 % OTM. Prêmio maior; se exercido, você vende num preço esticado."
    )

st.divider()

_linhas = []
for r in resultados:
    _cot = dados[r["ativo"]].get("cotacao", {})
    _conf = _cot.get("confianca")
    _marca = {"alta": "✓", "unica": "1 fonte", "divergente": "⚠"}.get(_conf, "")
    _real = r.get("mercado") or {}
    _venc = _real.get("vencimento") or ""
    _venc_fmt = f"{_venc[8:10]}/{_venc[5:7]}" if len(_venc) >= 10 else "—"
    _linhas.append({
        "Ativo": r["ativo"],
        "Preço": mercado.formatar_reais(r.get("preco")),
        "Variação": mercado.variacao_fmt(r.get("variacao_pct", 0.0)),
        "Cotação": f"{cotacoes.hora_curta(_cot)} {_marca}".strip(),
        f"MA{MA_PERIODO}": mercado.formatar_reais(r.get("ma_decisao")),
        "Viés": r["vies"],
        "Ação": ("⚡ " if r["prioridade"] else "") + r["acao"],
        "Modo": ("🔥 " if r.get("modo") == "ESTICADO" else "") + r.get("modo", "—"),
        "Strike ref.": mercado.formatar_reais(r.get("strike_sugerido")),
        "Prêmio real (fech.)": (
            f"{mercado.formatar_reais(_real['preco'])} · K{_real['strike']:.0f}"
            + (
                f" · {_real['preco'] / r['preco'] * 100:.2f} %"
                if r.get("preco")
                else ""
            )
            if _real
            else "—"
        ),
        "Venc. real": _venc_fmt if _real else "—",
        "Prêmio teórico": mercado.formatar_reais(r.get("premio_teorico")),
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
    f"Modo renda: PUT delta {DELTA_PUT_RENDA:.2f} · CALL delta {DELTA_CALL_RENDA:+.2f} · "
    f"piso {PREMIO_MIN_RENDA_PCT*100:.1f} % do preço. "
    f"Modo esticado: CALL +3 % OTM · piso {PREMIO_MIN_ESTICADO_PCT*100:.1f} %. "
    f"**Prêmio real (fech.)** = último negócio do vencimento mais próximo de {dias} dias, "
    "fonte opcoes.net.br — é o preço de fechamento, não o bid de agora. "
    "**Teórico** = Black-Scholes com volatilidade histórica (referência). "
    "Confirme o bid no Home Broker em **Análise do Ativo**. "
    "**CALL só se coberta** — o app não rastreia posição."
)

st.divider()
st.subheader("Leitura rápida")

for r in resultados:
    icone = "🔴" if r["vies"] == "PUT" else ("🟢" if r["vies"] == "CALL" else "⚪")
    with st.expander(f"{icone} {r['ativo']} — {r['acao']}", expanded=r["prioridade"]):
        st.write(r["mensagem"])
        if r.get("modo") == "ESTICADO":
            st.info(
                f"🔥 Modo esticado ({r['gatilhos'].get('ativos', 0)}/3): "
                + estrategia.descrever_gatilhos(r["gatilhos"])
                + ". A CALL vai para +3 % OTM; se exercido, a venda é num preço esticado."
            )
        elif r.get("vies") in ("CALL", "PUT"):
            st.caption(
                f"Modo renda — delta {r.get('delta_alvo'):+.2f} · piso "
                f"{r.get('premio_min_pct', 0)*100:.1f} % do preço."
            )
        _real = r.get("mercado")
        if _real:
            _venc = _real.get("vencimento") or ""
            _venc_fmt = f"{_venc[8:10]}/{_venc[5:7]}" if len(_venc) >= 10 else _venc
            st.write(
                f"📉 **Mercado (fech. {_real.get('data', '—')})**: "
                f"{_real['tipo']} K{_real['strike']:.0f} a "
                f"R$ {_real['preco']:.2f} · {_real['negocios']} negócios · "
                f"venc. {_venc_fmt} ({_real['dias']} dias)"
                + (f" · IV {_real['iv']*100:.1f} %" if _real.get("iv") else "")
                + (
                    f" · spot do fechamento R$ {_real['spot_mercado']:.2f}"
                    if _real.get("spot_mercado")
                    else ""
                )
            )
            if _real["preco"] < r.get("premio_min", 0):
                st.warning(
                    f"No fechamento o mercado pagou R$ {_real['preco']:.2f}, "
                    f"abaixo do mínimo R$ {r['premio_min']:.2f} — pela regra, não vale."
                )
        for p in r["passos"]:
            st.write(("✅" if p["ok"] else "❌") + f" **{p['titulo']}** — {p['texto']}")

st.caption(
    f"Atualização a cada {REFRESH_INTERVAL_SECONDS // 60} min — "
    f"{time.strftime('%d/%m/%Y %H:%M')} · veja a aba **A Regra** para o passo a passo."
)
