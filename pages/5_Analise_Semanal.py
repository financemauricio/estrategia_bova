"""Análise Semanal — 5-step checklist and BOVA11 + MA200 chart."""

from __future__ import annotations

import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    ALOCACAO_ALVO,
    CAIXA_MIN_PCT,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    MA_VISUALIZACAO,
)
from modulos import banco, estrategia, mercado

st.title("📅 Análise Semanal")
st.caption("Use esta tela todo final de semana para revisar a estratégia.")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
dados = mercado.buscar_dados_mercado()
posicoes = banco.listar_posicoes()
saldo = banco.saldo_caixa()
opcoes_abertas = banco.listar_opcoes("ABERTA")
pat = mercado.calcular_patrimonio(posicoes, dados)
total_etf = pat["total_etf"]

resultado = estrategia.avaliar_estrategia(dados, posicoes, saldo, total_etf, opcoes_abertas)
passos = resultado["passos"]
rec = resultado["recomendacao"]

st.divider()

# ---------------------------------------------------------------------------
# BOVA11 chart with MA200
# ---------------------------------------------------------------------------
st.subheader(f"BOVA11 — Preço com MA{MA_PERIODO} (decisão) + referências (3 meses)")

bova_hist: pd.DataFrame | None = dados.get("BOVA11", {}).get("hist")

# Colours and dash styles per MA window
_MA_STYLES: dict[int, dict] = {
    25:  {"color": "#2ecc71", "dash": "solid",  "width": 2},
    50:  {"color": "#f39c12", "dash": "dot",    "width": 2},
    200: {"color": "#e74c3c", "dash": "dashdot","width": 1},
}

if bova_hist is not None and not bova_hist.empty:
    df_chart = bova_hist.tail(65).copy()  # ~3 months of trading days

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df_chart.index,
            open=df_chart["Open"],
            high=df_chart["High"],
            low=df_chart["Low"],
            close=df_chart["Close"],
            name="BOVA11",
            increasing_line_color="#2ecc71",
            decreasing_line_color="#e74c3c",
        )
    )

    for janela in MA_VISUALIZACAO:
        col_name = f"MA{janela}"
        if col_name in bova_hist.columns:
            series = bova_hist[col_name].tail(65)
            style = _MA_STYLES.get(janela, {"color": "#888", "dash": "dot", "width": 1})
            label = f"MA{janela}" + (" ★" if janela == MA_PERIODO else "")
            fig.add_trace(
                go.Scatter(
                    x=df_chart.index,
                    y=series.values,
                    mode="lines",
                    line=dict(color=style["color"], width=style["width"], dash=style["dash"]),
                    name=label,
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
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"★ MA{MA_PERIODO} é a média usada para decisão. MA50 e MA200 são referências visuais.")
else:
    st.warning("Histórico de BOVA11 indisponível.")

st.divider()

# ---------------------------------------------------------------------------
# 5-step checklist
# ---------------------------------------------------------------------------
st.subheader("Checklist dos 5 Passos")

p1 = passos["passo1"]
p2 = passos["passo2"]
p3 = passos["passo3"]
ma_decisao_val = p1.get("ma200")

def _badge(ok: bool | None) -> str:
    if ok is True:
        return "🟢"
    if ok is False:
        return "🔴"
    return "🟡"


with st.container():
    st.markdown(f"### {_badge(p1['ok'])} Passo 1 — BOVA11 vs MA{MA_PERIODO}")
    if p1["ok"]:
        dist = p1.get("distancia_pct", 0)
        ma_val = p1.get("ma200")
        st.write(
            f"Preço: **R$ {p1['preco']:.2f}** | MA{MA_PERIODO}: **R$ {ma_val:.2f}** | "
            f"Distância: **{dist*100:+.2f} %**"
        )
        if p1["resultado"] == "ACIMA":
            st.success(f"✅ BOVA11 **ACIMA** da MA{MA_PERIODO} → Viés **CALL** (vender CALL coberta)")
        else:
            st.success(f"✅ BOVA11 **ABAIXO** da MA{MA_PERIODO} → Viés **PUT** (vender PUT)")
    else:
        st.error("❌ Dados insuficientes para avaliar.")

st.divider()

with st.container():
    st.markdown(f"### {_badge(p2['ok'])} Passo 2 — Recursos Disponíveis")
    st.write(p2.get("detalhe", "—"))
    if p2["ok"]:
        st.success("✅ Recursos suficientes para operar.")
    else:
        st.error("❌ Recursos insuficientes — não abra novas posições.")

st.divider()

with st.container():
    st.markdown(f"### {_badge(p3['ok'])} Passo 3 — Movimento Relevante (na direção do viés)")
    var = p3.get("variacao", 0)
    vies_atual = resultado.get("vies", "INDEFINIDO")
    st.write(f"Variação de hoje: **{var*100:+.2f} %** | Viés: **{vies_atual}**")
    if p3["ok"]:
        if p3.get("queda_forte"):
            st.success(
                f"✅ Queda de {abs(var)*100:.2f} % — sinal de PUT confirmado "
                f"(limiar: {abs(LIMIAR_QUEDA_PUT)*100:.1f} %). Prioridade máxima."
            )
        elif p3.get("alta_forte"):
            st.success(
                f"✅ Alta de {var*100:.2f} % — sinal de CALL confirmado "
                f"(limiar: {LIMIAR_ALTA_CALL*100:.1f} %). Prioridade máxima."
            )
    else:
        if vies_atual == "PUT":
            st.error(
                f"❌ Sem queda relevante hoje ({var*100:+.2f} %). "
                f"Aguarde queda ≥ {abs(LIMIAR_QUEDA_PUT)*100:.1f} % para prioridade máxima."
            )
        elif vies_atual == "CALL":
            st.error(
                f"❌ Sem alta relevante hoje ({var*100:+.2f} %). "
                f"Aguarde alta ≥ {LIMIAR_ALTA_CALL*100:.1f} % para prioridade máxima."
            )
        else:
            st.warning("Viés indefinido — aguardar dados de mercado.")

st.divider()

with st.container():
    st.markdown(f"### 🟡 Passo 4 — Prêmio Atrativo")
    st.info(
        "Confirme no Home Broker: o prêmio oferecido justifica o risco? "
        "Evite vender em dias de baixa volatilidade implícita."
    )
    premium_ok = st.checkbox("Sim, o prêmio está atrativo")

st.divider()

with st.container():
    st.markdown(f"### {_badge(rec != 'AGUARDAR' and premium_ok)} Passo 5 — Executar")
    if not premium_ok:
        st.warning("Confirme o prêmio no Passo 4 antes de prosseguir.")
    elif rec == "PUT_ATM":
        st.error(
            "**VENDER PUT ATM** com vencimento mensal. "
            "Aceitar exercício se houver. Rolar apenas se melhorar strike e prêmio."
        )
    elif rec == "CALL_OTM":
        strike = resultado.get("strike_sugerido")
        st.success(
            f"**VENDER CALL 3% OTM** — strike sugerido R$ {strike:.2f}. "
            "Aceitar exercício se houver. Rolar apenas se claramente vantajoso."
        )
    else:
        st.info("**AGUARDAR** — condições não favorecem operação no momento.")

st.divider()

# ---------------------------------------------------------------------------
# Options expiring soon
# ---------------------------------------------------------------------------
st.subheader("Opções Vencendo em Breve")

abertas = banco.listar_opcoes("ABERTA")
hoje = datetime.date.today()
proximas = []
for op in abertas:
    venc = op["vencimento"]
    if isinstance(venc, str):
        venc = datetime.date.fromisoformat(venc)
    dias = (venc - hoje).days
    if dias <= 10:
        proximas.append(
            {
                "Tipo": op["tipo"],
                "Código": op["codigo_opcao"] or "—",
                "Strike": f"R$ {op['strike']:.2f}",
                "Vencimento": str(venc),
                "Dias restantes": dias,
            }
        )

if proximas:
    st.warning(f"{len(proximas)} opção(ões) vencendo nos próximos 10 dias:")
    st.dataframe(pd.DataFrame(proximas), use_container_width=True, hide_index=True)
else:
    st.success("Nenhuma opção vencendo nos próximos 10 dias.")

st.divider()

# ---------------------------------------------------------------------------
# Allocation status
# ---------------------------------------------------------------------------
st.subheader("Status de Alocação")

for ticker, alvo in ALOCACAO_ALVO.items():
    atual = pat["alocacao"].get(ticker, 0)
    desvio = atual - alvo
    st.metric(
        ticker,
        f"{atual*100:.1f} %",
        delta=f"{desvio*100:+.1f} % vs alvo {alvo*100:.0f} %",
        delta_color="off",
    )
