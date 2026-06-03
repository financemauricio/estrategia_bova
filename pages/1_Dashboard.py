"""Dashboard — real-time market monitor and strategy recommendation."""

from __future__ import annotations

import time

import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh as _st_autorefresh  # type: ignore[import]
    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False

from config import (
    ALOCACAO_ALVO,
    CAIXA_MIN_PCT,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    MA_VISUALIZACAO,
    REFRESH_INTERVAL_SECONDS,
)
import math

import plotly.graph_objects as go

from modulos import alertas, banco, bs, estrategia, mercado

# ---------------------------------------------------------------------------
# Auto-refresh every REFRESH_INTERVAL_SECONDS milliseconds
# ---------------------------------------------------------------------------
if _HAS_AUTOREFRESH:
    try:
        _st_autorefresh(interval=REFRESH_INTERVAL_SECONDS * 1_000, key="dashboard_refresh")
    except Exception:
        pass

st.title("📊 Dashboard")

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
with st.spinner("Buscando dados de mercado..."):
    dados = mercado.buscar_dados_mercado()

posicoes = banco.listar_posicoes()
saldo = banco.saldo_caixa()
opcoes_abertas = banco.listar_opcoes("ABERTA")
patrimonio_calc = mercado.calcular_patrimonio(posicoes, dados)
total_etf = patrimonio_calc["total_etf"]
patrimonio_total = total_etf + saldo

# ---------------------------------------------------------------------------
# Send e-mail alert if threshold crossed (only once per refresh cycle)
# ---------------------------------------------------------------------------
if dados:
    alertas.verificar_e_alertar(dados)

# ---------------------------------------------------------------------------
# Monday expiry summary — send once per day using session_state guard
# ---------------------------------------------------------------------------
import datetime as _dt

_hoje = _dt.date.today()
_session_key = f"expiry_email_sent_{_hoje.isoformat()}"

if _hoje.weekday() == 0 and not st.session_state.get(_session_key):
    _semana_atras = _hoje - _dt.timedelta(days=7)
    _todas_opcoes = banco.listar_opcoes()
    _vencidas_semana = []
    for _op in _todas_opcoes:
        _venc = _op["vencimento"]
        if isinstance(_venc, str):
            _venc = _dt.date.fromisoformat(_venc)
        if _semana_atras <= _venc < _hoje:
            _vencidas_semana.append(_op)

    if _vencidas_semana:
        _enviado = alertas.alertar_vencimentos(_vencidas_semana)
        st.session_state[_session_key] = True
        if _enviado:
            _exercidas_n = sum(1 for o in _vencidas_semana if o["status"] == "EXERCIDA")
            if _exercidas_n:
                st.warning(
                    f"📧 Email enviado: {_exercidas_n} opção(ões) exercida(s) na semana passada. "
                    "Verifique se precisa depositar na corretora."
                )
            else:
                st.info(f"📧 Resumo semanal enviado: {len(_vencidas_semana)} opção(ões) vencida(s).")
    else:
        st.session_state[_session_key] = True  # nenhuma vencida, não tentar novamente hoje

# ---------------------------------------------------------------------------
# Friday weekly reminder — send once per day
# ---------------------------------------------------------------------------
_key_sexta = f"lembrete_sexta_{_hoje.isoformat()}"

if _hoje.weekday() == 4 and not st.session_state.get(_key_sexta):
    _enviado_sexta = alertas.alertar_lembrete_sexta(opcoes_abertas)
    st.session_state[_key_sexta] = True
    if _enviado_sexta:
        st.info("📧 Lembrete semanal enviado por email.")

# ---------------------------------------------------------------------------
# Top KPIs
# ---------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Patrimônio Total", f"R$ {patrimonio_total:,.2f}")
col2.metric("Total em ETFs", f"R$ {total_etf:,.2f}")

caixa_pct = saldo / patrimonio_total if patrimonio_total > 0 else 0.0
col3.metric("Caixa", f"R$ {saldo:,.2f}", f"{caixa_pct*100:.1f} %" if patrimonio_total else "")
col4.metric(
    "Caixa vs Mínimo",
    f"{caixa_pct*100:.1f} %" if patrimonio_total else "—",
    delta_color="normal" if caixa_pct >= CAIXA_MIN_PCT else "inverse",
)

st.divider()

# ---------------------------------------------------------------------------
# BOVA11 main card — price + all MAs
# ---------------------------------------------------------------------------
bova = dados.get("BOVA11", {})
preco_bova = bova.get("preco")
var_bova = bova.get("variacao_pct", 0.0)
ma_decisao = bova.get("ma_decisao")
mas = bova.get("mas", {})

if preco_bova and ma_decisao:
    acima = preco_bova > ma_decisao
    distancia = (preco_bova - ma_decisao) / ma_decisao

    st.subheader(f"BOVA11 — Indicador Principal (MA{MA_PERIODO} para decisão)")

    ca, cb, cc, cd = st.columns(4)
    ca.metric("Preço", f"R$ {preco_bova:.2f}", mercado.variacao_fmt(var_bova))
    cb.metric(
        f"MA{MA_PERIODO} (decisão)",
        f"R$ {ma_decisao:.2f}",
        f"{'ACIMA ↑' if acima else 'ABAIXO ↓'} {distancia*100:+.1f} %",
        delta_color="normal" if acima else "inverse",
    )
    cc.metric("Variação Hoje", mercado.variacao_fmt(var_bova))
    cd.metric("Viés", "🟢 CALL" if acima else "🔴 PUT")

    # Other MAs for reference
    outras_mas = [j for j in MA_VISUALIZACAO if j != MA_PERIODO]
    if outras_mas:
        cols_ma = st.columns(len(outras_mas))
        for col_ma, janela in zip(cols_ma, outras_mas):
            val = mas.get(janela)
            if val:
                dist = (preco_bova - val) / val
                col_ma.metric(
                    f"MA{janela} (referência)",
                    f"R$ {val:.2f}",
                    f"{'↑' if preco_bova > val else '↓'} {dist*100:+.1f} %",
                    delta_color="normal" if preco_bova > val else "inverse",
                )

    # Opportunity alert banner
    if var_bova <= LIMIAR_QUEDA_PUT:
        st.error(f"⚡ QUEDA FORTE: {var_bova*100:.2f} % — PRIORIDADE MÁXIMA para venda de PUT")
    elif var_bova >= LIMIAR_ALTA_CALL:
        st.success(f"⚡ ALTA FORTE: {var_bova*100:+.2f} % — PRIORIDADE MÁXIMA para venda de CALL")

else:
    st.warning("Dados de BOVA11 indisponíveis. Verifique a conexão.")

st.divider()

# ---------------------------------------------------------------------------
# IVVB11 and HASH11
# ---------------------------------------------------------------------------
st.subheader("Outros ETFs")
ce, cf = st.columns(2)

for col, nome in [(ce, "IVV"), (cf, "HASH11")]:
    d = dados.get(nome, {})
    p = d.get("preco")
    p_brl = d.get("preco_brl")
    moeda = d.get("moeda", "BRL")
    v = d.get("variacao_pct", 0.0)
    alvo = ALOCACAO_ALVO.get(nome, 0)
    atual = patrimonio_calc["alocacao"].get(nome, 0)
    with col:
        if p:
            if moeda == "USD":
                st.metric(nome, f"US$ {p:.2f}", mercado.variacao_fmt(v))
                usdbrl = d.get("usdbrl", 0)
                st.caption(f"≈ R$ {p_brl:.2f}  |  USD/BRL: {usdbrl:.2f}  |  Alvo: {alvo*100:.0f} %  |  Atual: {atual*100:.1f} %")
            else:
                st.metric(nome, f"R$ {p:.2f}", mercado.variacao_fmt(v))
                st.caption(f"Alvo: {alvo*100:.0f} %  |  Atual: {atual*100:.1f} %")
        else:
            st.metric(nome, "—")

st.divider()

# ---------------------------------------------------------------------------
# Strategy recommendation
# ---------------------------------------------------------------------------
st.subheader("Recomendação da Estratégia")

resultado = estrategia.avaliar_estrategia(dados, posicoes, saldo, total_etf, opcoes_abertas)
rec = resultado["recomendacao"]
prioridade = resultado["prioridade"]
mensagem = resultado["mensagem"]

if rec == "PUT_ATM":
    cor = "error" if prioridade else "warning"
    getattr(st, cor)(f"🔴 VENDER PUT ATM — {mensagem}")
elif rec == "CALL_OTM":
    cor = "success" if prioridade else "info"
    strike = resultado.get("strike_sugerido")
    strike_txt = f" | Strike sugerido: R$ {strike:.2f}" if strike else ""
    getattr(st, cor)(f"🟢 VENDER CALL 3% OTM{strike_txt} — {mensagem}")
else:
    st.info(f"⏸ AGUARDAR — {mensagem}")

with st.expander("Passo 4 — Confirmar atratividade do prêmio"):
    st.markdown(
        "Antes de operar, verifique no seu Home Broker se o prêmio está atrativo. "
        f"Prefira dias de queda > {abs(LIMIAR_QUEDA_PUT)*100:.0f} % (PUT) ou "
        f"alta > {LIMIAR_ALTA_CALL*100:.0f} % (CALL)."
    )

st.divider()

# ---------------------------------------------------------------------------
# 5-step checklist summary
# ---------------------------------------------------------------------------
st.subheader("Passos da Decisão Semanal")
passos = resultado["passos"]
p1 = passos["passo1"]
p2 = passos["passo2"]
p3 = passos["passo3"]

def _icone(ok: bool | None) -> str:
    return "✅" if ok is True else ("❌" if ok is False else "❓")

st.markdown(
    f"""
| Passo | Resultado |
|---|---|
| {_icone(p1['ok'])} 1 — BOVA11 vs MA{MA_PERIODO} | **{p1.get('resultado', '—')}** — viés **{p1.get('vies', '—')}** |
| {_icone(p2['ok'])} 2 — Recursos disponíveis | {p2.get('detalhe', '—')} |
| {_icone(p3['ok'])} 3 — Movimento relevante | {p3.get('detalhe', '—')} |
| {_icone(None)} 4 — Prêmio atrativo | Confirmação manual |
| {_icone(rec != 'AGUARDAR')} 5 — Executar | **{rec}** |
"""
)

st.caption(
    f"Decisão baseada na MA{MA_PERIODO}. Referências visuais: MA{', MA'.join(str(j) for j in MA_VISUALIZACAO)}. "
    f"Atualização a cada {REFRESH_INTERVAL_SECONDS // 60} min — {time.strftime('%d/%m/%Y %H:%M')}."
)

st.divider()

# ---------------------------------------------------------------------------
# Options portfolio overview
# ---------------------------------------------------------------------------
st.subheader("📋 Carteira de Opções — Planejamento de Caixa")

if not opcoes_abertas:
    st.info("Nenhuma opção aberta.")
else:
    import datetime as _dt

    _selic = bs.buscar_selic()
    hoje = _dt.date.today()

    # Build enriched rows
    _op_rows = []
    for op in opcoes_abertas:
        venc = op["vencimento"]
        if isinstance(venc, str):
            venc = _dt.date.fromisoformat(venc)
        dias = (venc - hoje).days

        # Probability of exercise
        d_mkt = dados.get(op["ativo"], {})
        hist_op = d_mkt.get("hist")
        preco_op = d_mkt.get("preco", 0.0)
        prob = None
        if hist_op is not None and preco_op > 0 and dias > 0:
            try:
                sigma = bs.calcular_vol_historica(hist_op, janela=20)
                T = max(dias, 1) / 252
                d1n = math.log(preco_op / op["strike"]) + (_selic + 0.5 * sigma**2) * T
                d2 = d1n / (sigma * math.sqrt(T)) - sigma * math.sqrt(T)
                nd2 = (1.0 + math.erf(d2 / math.sqrt(2.0))) / 2.0
                prob = (1 - nd2) if op["tipo"] == "PUT" else nd2
            except Exception:
                pass

        reserva = op["strike"] * op["quantidade"]
        prob_pct = prob * 100 if prob is not None else 0.0
        cor = "#e74c3c" if prob_pct >= 50 else ("#f39c12" if prob_pct >= 25 else "#2ecc71")

        _op_rows.append({
            "codigo": (op["codigo_opcao"] or "—").upper(),
            "tipo": op["tipo"],
            "vencimento": venc,
            "dias": dias,
            "strike": op["strike"],
            "qtd": op["quantidade"],
            "reserva": reserva,
            "prob": prob_pct,
            "cor": cor,
        })

    # Sort by expiry
    _op_rows.sort(key=lambda x: x["vencimento"])

    # KPI strip
    total_reserva = sum(r["reserva"] for r in _op_rows)
    op_k1, op_k2, op_k3 = st.columns(3)
    op_k1.metric("Opções abertas", len(_op_rows))
    op_k2.metric("Reserva total necessária", f"R$ {total_reserva:,.2f}",
                 help="Σ strike × quantidade de todas as opções abertas")
    caixa_cobre = "✅ Cobre" if saldo >= total_reserva else "🚨 Insuficiente"
    op_k3.metric("Caixa vs. Reserva", caixa_cobre,
                 delta=f"R$ {saldo - total_reserva:+,.2f}")

    # Bar chart: cash at risk per expiry, colored by probability
    fig_op = go.Figure()
    for row in _op_rows:
        fig_op.add_trace(go.Bar(
            x=[str(row["vencimento"])],
            y=[row["reserva"]],
            name=row["codigo"],
            marker_color=row["cor"],
            text=f"{row['codigo']}<br>Prob: {row['prob']:.1f}%<br>R$ {row['reserva']:,.0f}",
            hoverinfo="text",
        ))

    fig_op.update_layout(
        barmode="stack",
        xaxis_title="Vencimento",
        yaxis_title="Reserva de caixa (R$)",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
        margin=dict(t=10, b=10),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(tickformat=",.0f", tickprefix="R$ "),
    )
    # Reference line: available cash
    fig_op.add_hline(
        y=saldo, line_dash="dash", line_color="#3498db",
        annotation_text=f"Caixa disponível R$ {saldo:,.0f}",
        annotation_position="top left",
    )
    st.plotly_chart(fig_op, use_container_width=True)

    # Detail table
    tbl_cols  = ["Código", "Tipo", "Vencimento", "Dias", "Strike", "Qtd", "Reserva (R$)", "Prob. Exercício"]
    tbl_vals  = [
        [r["codigo"]              for r in _op_rows],
        [r["tipo"]                for r in _op_rows],
        [str(r["vencimento"])     for r in _op_rows],
        [str(r["dias"])           for r in _op_rows],
        [f"R$ {r['strike']:.2f}" for r in _op_rows],
        [str(r["qtd"])            for r in _op_rows],
        [f"R$ {r['reserva']:,.2f}" for r in _op_rows],
        [f"{r['prob']:.1f}%"     for r in _op_rows],
    ]
    cell_colors = [["#0e1117"] * len(_op_rows)] * (len(tbl_cols) - 1) + \
                  [[r["cor"]   for r in _op_rows]]

    fig_tbl = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c}</b>" for c in tbl_cols],
            fill_color="#1a1d27", font=dict(color="white", size=12),
            align="center", line_color="#333",
        ),
        cells=dict(
            values=tbl_vals,
            fill_color=cell_colors,
            font=dict(color="white", size=12),
            align="center", line_color="#222", height=30,
        ),
    ))
    fig_tbl.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        height=55 + len(_op_rows) * 34,
    )
    st.plotly_chart(fig_tbl, use_container_width=True)
    st.caption("🟢 < 25%  🟡 25–50%  🔴 > 50% probabilidade de exercício (Black-Scholes, vol. histórica 20d)")
