"""Opções — register, monitor and close options positions."""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

import math
import re

import plotly.graph_objects as go

from modulos import banco, bs, mercado


# ---------------------------------------------------------------------------
# B3 option code parser
# ---------------------------------------------------------------------------

_CALL_MONTHS = "ABCDEFGHIJKL"   # Jan–Dez CALL
_PUT_MONTHS  = "MNOPQRSTUVWX"   # Jan–Dez PUT
_MONTH_NAMES = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]


def _nª_sexta(ano: int, mes: int, n: int) -> datetime.date:
    """Return the Nth Friday of a given month/year."""
    primeiro = datetime.date(ano, mes, 1)
    dias_ate_sexta = (4 - primeiro.weekday()) % 7  # 4 = Friday
    primeira_sexta = primeiro + datetime.timedelta(days=dias_ate_sexta)
    return primeira_sexta + datetime.timedelta(weeks=n - 1)


def _sugerir_vencimento(mes_idx: int, semana: str) -> datetime.date:
    """Suggest an expiry date based on month letter and optional week suffix.

    Monthly options → 3rd Friday of the month.
    Weekly options (W1–W4) → Nth Friday of the month.
    Picks the nearest future occurrence.
    """
    hoje = datetime.date.today()
    for delta_ano in range(2):
        ano = hoje.year + delta_ano
        try:
            if semana:
                n = int(semana[1])  # W1→1, W2→2, etc.
                data = _nª_sexta(ano, mes_idx, n)
            else:
                data = _nª_sexta(ano, mes_idx, 3)
            if data >= hoje:
                return data
        except (ValueError, OverflowError):
            continue
    return hoje + datetime.timedelta(days=30)

_PREFIXO_ATIVO = {
    # ETFs
    "BOVA": "BOVA11",
    "HASH": "HASH11",
    "SMAL": "SMAL11",
    "IVVB": "IVVB11",
    # Commodities / energia
    "PETR": "PETR4",
    "VALE": "VALE3",
    "PRIO": "PRIO3",
    "RECV": "RECV3",
    # Bancos
    "ITUB": "ITUB4",
    "BBDC": "BBDC4",
    "BBAS": "BBAS3",
    "SANB": "SANB11",
    # Consumo / varejo
    "ABEV": "ABEV3",
    "LREN": "LREN3",
    "MGLU": "MGLU3",
    # Industria / tech
    "WEGE": "WEGE3",
    "EMBR": "EMBR3",
    "TOTS": "TOTS3",
    "INTB": "INTB3",
    # Utilities
    "EQTL": "EQTL3",
    "ELET": "ELET3",
    "CPFE": "CPFE3",
    # Telecom
    "VIVT": "VIVT3",
    # Papel / celulose
    "SUZB": "SUZB3",
    "KLBN": "KLBN11",
    # Saúde
    "RADL": "RADL3",
    "HAPV": "HAPV3",
    # Outros
    "RENT": "RENT3",
    "GOLL": "GOLL4",
    "AZUL": "AZUL4",
}

def _parse_codigo(codigo: str) -> dict:
    """Parse a B3 option code and return extracted fields.

    Parameters
    ----------
    codigo : str
        e.g. 'BOVAR169', 'BOVAR164W1', 'HASHQ50'

    Returns
    -------
    dict with keys: ativo, tipo, mes_idx (1-12), strike_raw, semana, ok
    """
    codigo = codigo.upper().strip()
    m = re.match(r'^([A-Z]{4})([A-Z])(\d+)(W\d)?$', codigo)
    if not m:
        return {"ok": False}

    prefixo, letra_mes, strike_str, semana = m.groups()
    ativo = _PREFIXO_ATIVO.get(prefixo, prefixo)

    if letra_mes in _CALL_MONTHS:
        tipo = "CALL"
        mes_idx = _CALL_MONTHS.index(letra_mes) + 1
    elif letra_mes in _PUT_MONTHS:
        tipo = "PUT"
        mes_idx = _PUT_MONTHS.index(letra_mes) + 1
    else:
        return {"ok": False}

    return {
        "ok": True,
        "ativo": ativo,
        "tipo": tipo,
        "mes_idx": mes_idx,
        "mes_nome": _MONTH_NAMES[mes_idx - 1],
        "strike_raw": strike_str,
        "semana": semana or "",
    }

st.title("📋 Opções")

st.markdown("""
<style>
[data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {
    text-align: center !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Single-fetch: all options + cash balance (2 DB round-trips total)
# ---------------------------------------------------------------------------
todas = banco.listar_opcoes()
saldo = banco.saldo_caixa()

# Market data for probability calculation (cached — no extra round-trip cost)
_dados_mkt = mercado.buscar_dados_mercado()
_selic = bs.buscar_selic()

def _prob_exercicio(tipo: str, ativo: str, strike: float, dias: int) -> float | None:
    """Return probability of exercise [0, 1] using Black-Scholes N(±d2).

    Works for any B3 stock — portfolio assets use the cached market data,
    others are fetched on demand via ``mercado.buscar_dados_ativo_opcao``.

    Parameters
    ----------
    tipo : str
        'PUT' or 'CALL'.
    ativo : str
        Underlying asset name, e.g. 'PETR4', 'BOVA11'.
    strike : float
        Option strike price.
    dias : int
        Calendar days to expiry.

    Returns
    -------
    float or None
        Probability in [0, 1], or None if data is unavailable.
    """
    # Use portfolio cache first; fall back to on-demand fetch
    d = _dados_mkt.get(ativo) or mercado.buscar_dados_ativo_opcao(ativo)
    hist  = d.get("hist")
    preco = d.get("preco")
    if hist is None or preco is None or preco <= 0 or dias <= 0:
        return None
    try:
        sigma = bs.calcular_vol_historica(hist, janela=20)
    except Exception:
        return None
    T = max(dias, 1) / 252
    if sigma <= 0:
        return None
    d1_num = math.log(preco / strike) + (_selic + 0.5 * sigma ** 2) * T
    d2 = (d1_num / (sigma * math.sqrt(T))) - sigma * math.sqrt(T)
    norm_d2 = (1.0 + math.erf(d2 / math.sqrt(2.0))) / 2.0
    return (1 - norm_d2) if tipo == "PUT" else norm_d2


def _prob_badge(prob: float | None) -> str:
    if prob is None:
        return "—"
    pct = prob * 100
    if pct >= 50:
        emoji = "🔴"
    elif pct >= 25:
        emoji = "🟡"
    else:
        emoji = "🟢"
    return f"{emoji} {pct:.1f}%"

abertas   = [o for o in todas if o["status"] == "ABERTA"]
exercidas = [o for o in todas if o["status"] == "EXERCIDA"]
expiradas = [o for o in todas if o["status"] in ("EXPIRADA", "ROLADA")]
total_premios = sum(o["premio_total"] for o in todas)

# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total de prêmios recebidos", f"R$ {total_premios:,.2f}")
k2.metric("Posições abertas", len(abertas))
k3.metric("Exercidas", len(exercidas))
k4.metric("Expiradas / Roladas", len(expiradas))

st.divider()

# ---------------------------------------------------------------------------
# Caixa comprometido com PUTs abertas
# ---------------------------------------------------------------------------
st.subheader("💰 Caixa vs. Compromisso com PUTs")

puts_abertas = [op for op in abertas if op["tipo"] == "PUT"]
comprometido = sum(op["strike"] * op["quantidade"] for op in puts_abertas)
disponivel = saldo - comprometido
pct_comprometido = comprometido / saldo if saldo > 0 else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Saldo total em caixa", f"R$ {saldo:,.2f}")
c2.metric(
    "Comprometido com PUTs",
    f"R$ {comprometido:,.2f}",
    help="Σ strike × quantidade de todas as PUTs abertas — valor necessário se exercidas.",
)
c3.metric(
    "Caixa disponível",
    f"R$ {disponivel:,.2f}",
    delta=f"{(1 - pct_comprometido) * 100:.1f}% livre",
    delta_color="normal" if disponivel >= 0 else "inverse",
)
c4.metric("% comprometido", f"{pct_comprometido * 100:.1f}%")

if disponivel < 0:
    st.error(
        "🚨 **Caixa insuficiente!** O valor comprometido com PUTs supera o saldo disponível. "
        "Não venda novas PUTs até encerrar ou rolar posições."
    )
elif pct_comprometido >= 0.80:
    st.warning(
        "⚠️ **Caixa muito comprometido** (≥ 80%). Evite novas PUTs até alguma posição expirar ou ser exercida."
    )
elif pct_comprometido >= 0.50:
    st.info(
        "ℹ️ **Atenção:** mais de 50% do caixa já está reservado para PUTs abertas. "
        "Avalie com cuidado antes de vender novas PUTs."
    )
else:
    st.success(
        f"✅ Caixa confortável — {(1 - pct_comprometido) * 100:.1f}% livre para novas operações."
    )

if puts_abertas:
    with st.expander("Detalhes do comprometimento por PUT"):
        rows_put = []
        for op in puts_abertas:
            exp = op["vencimento"]
            if isinstance(exp, str):
                exp = datetime.date.fromisoformat(exp)
            dias = (exp - datetime.date.today()).days
            reserva = op["strike"] * op["quantidade"]
            rows_put.append({
                "Código": op["codigo_opcao"] or "—",
                "Strike": f"R$ {op['strike']:.2f}",
                "Qtd": op["quantidade"],
                "Reserva (R$)": f"R$ {reserva:,.2f}",
                "% do caixa": f"{reserva / saldo * 100:.1f}%" if saldo > 0 else "—",
                "Vencimento": str(exp),
                "Dias restantes": dias,
            })
        st.dataframe(pd.DataFrame(rows_put), use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Open positions
# ---------------------------------------------------------------------------
st.subheader("Posições Abertas")

if abertas:
    hoje = datetime.date.today()

    rows = []
    for op in abertas:
        venc = op["vencimento"]
        if isinstance(venc, str):
            venc = datetime.date.fromisoformat(venc)
        dias = (venc - hoje).days
        alerta = "⚠️" if dias <= 5 else ""
        prob = _prob_exercicio(op["tipo"], op["ativo"], op["strike"], dias)
        rows.append(
            {
                "Código": (op["codigo_opcao"] or "—").upper(),
                "Strike": f"R$ {op['strike']:.2f}",
                "Dias": f"{dias}{' ' + alerta if alerta else ''}",
                "Qtd": op["quantidade"],
                "Prêmio Total": f"R$ {op['premio_total']:.2f}",
                "Prob. Exercício": _prob_badge(prob),
                "Obs.": op["observacao"] or "",
            }
        )
    df_abertas = pd.DataFrame(rows)
    # Plotly table for full centering control
    fig_tbl = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c}</b>" for c in df_abertas.columns],
            fill_color="#1a1d27",
            font=dict(color="white", size=13),
            align="center",
            line_color="#333",
        ),
        cells=dict(
            values=[df_abertas[c].tolist() for c in df_abertas.columns],
            fill_color="#0e1117",
            font=dict(color="white", size=12),
            align="center",
            line_color="#222",
            height=32,
        ),
    ))
    fig_tbl.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        height=60 + len(rows) * 36,
    )
    st.plotly_chart(fig_tbl, use_container_width=True)
    st.caption("🟢 < 25 %  🟡 25–50 %  🔴 > 50 % — probabilidade calculada via Black-Scholes com vol. histórica 20d.")
else:
    st.info("Nenhuma posição aberta.")

st.divider()

# ---------------------------------------------------------------------------
# Register new option sale
# ---------------------------------------------------------------------------
st.subheader("Registrar Venda de Opção")

# Live parse feedback outside the form (reacts on every keystroke)
_codigo_preview = st.text_input(
    "Código da opção",
    placeholder="ex: BOVAR169 ou BOVAR164W1",
    key="codigo_input",
).upper().strip()

_parsed = _parse_codigo(_codigo_preview) if _codigo_preview else {"ok": False}

_venc_sugerido = datetime.date.today() + datetime.timedelta(days=30)
if _codigo_preview and _parsed["ok"]:
    _venc_sugerido = _sugerir_vencimento(_parsed["mes_idx"], _parsed["semana"])
    st.success(
        f"✅ **{_parsed['ativo']}** · **{_parsed['tipo']}** · "
        f"vencimento sugerido **{_venc_sugerido.strftime('%d/%m/%Y')}** "
        + (f"· {_parsed['semana']}" if _parsed['semana'] else "")
    )
elif _codigo_preview:
    st.warning("⚠️ Código não reconhecido — verifique a nomenclatura B3.")

with st.form("form_opcao", clear_on_submit=True):
    fc1, fc2, fc3 = st.columns(3)
    strike_op  = fc1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=100.0)
    venc_op    = fc2.date_input("Vencimento", value=_venc_sugerido)
    qtd_op     = fc3.number_input("Quantidade", min_value=1, step=1)

    fc4, fc5 = st.columns([2, 1])
    premio_op = fc4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
    obs_op    = fc5.text_input("Observação")

    total_preview = qtd_op * premio_op
    reserva_caixa = strike_op * qtd_op if (_parsed.get("tipo") == "PUT") else 0.0

    st.markdown(
        f"💰 **Prêmio total:** R$ {total_preview:,.2f}"
        + (f"  |  🔒 **Reserva de caixa:** R$ {reserva_caixa:,.2f}" if reserva_caixa else "")
    )

    submitted = st.form_submit_button("✅ Registrar venda", use_container_width=True)
    if submitted:
        if not _parsed["ok"]:
            st.error("Informe um código de opção válido antes de registrar.")
        else:
            banco.inserir_opcao(
                data_abertura=str(datetime.date.today()),
                tipo=_parsed["tipo"],
                ativo=_parsed["ativo"],
                codigo_opcao=_codigo_preview,
                strike=strike_op,
                vencimento=str(venc_op),
                quantidade=int(qtd_op),
                premio_unitario=premio_op,
                observacao=obs_op,
            )
            st.success(
                f"✅ {_parsed['tipo']} **{_codigo_preview}** registrada — "
                f"prêmio R$ {total_preview:,.2f}"
            )
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Close / update open position
# ---------------------------------------------------------------------------
st.subheader("Encerrar Posição")

if abertas:
    _label_op = {
        f"{(op['codigo_opcao'] or '—').upper()} — {op['tipo']} Strike {op['strike']} Venc. {op['vencimento']}": op
        for op in abertas
    }

    with st.form("form_fechar", clear_on_submit=True):
        opcao_sel_label = st.selectbox("Selecionar posição", list(_label_op.keys()))
        fc1, fc2 = st.columns(2)
        status_novo = fc1.selectbox("Novo status", ["EXERCIDA", "EXPIRADA", "ROLADA"])
        data_fech = fc2.date_input("Data de fechamento", value=datetime.date.today())

        if st.form_submit_button("Encerrar"):
            banco.fechar_opcao(_label_op[opcao_sel_label]["id"], status_novo, str(data_fech))
            st.success("Posição encerrada.")
            st.rerun()
else:
    st.caption("Nenhuma posição aberta para encerrar.")

st.divider()

# ---------------------------------------------------------------------------
# Edit open position
# ---------------------------------------------------------------------------
st.subheader("✏️ Editar Posição Aberta")

if abertas:
    _label_edit = {
        f"{(op['codigo_opcao'] or '—').upper()} — {op['tipo']} Strike {op['strike']} Venc. {op['vencimento']}": op
        for op in abertas
    }
    _sel_edit_label = st.selectbox("Selecionar posição para editar", list(_label_edit.keys()), key="sel_edit")
    _op_edit = _label_edit[_sel_edit_label]

    _venc_edit = _op_edit["vencimento"]
    if isinstance(_venc_edit, str):
        _venc_edit = datetime.date.fromisoformat(_venc_edit)

    with st.form("form_editar", clear_on_submit=False):
        e1, e2, e3 = st.columns(3)
        strike_edit  = e1.number_input("Strike (R$)", value=float(_op_edit["strike"]), min_value=0.01, step=0.50, format="%.2f")
        venc_edit    = e2.date_input("Vencimento", value=_venc_edit)
        qtd_edit     = e3.number_input("Quantidade", value=int(_op_edit["quantidade"]), min_value=1, step=1)

        e4, e5 = st.columns([2, 1])
        premio_edit  = e4.number_input("Prêmio unitário (R$)", value=float(_op_edit["premio_unitario"]), min_value=0.0001, step=0.01, format="%.4f")
        obs_edit     = e5.text_input("Observação", value=_op_edit.get("observacao") or "")

        if st.form_submit_button("💾 Salvar alterações", use_container_width=True):
            banco.editar_opcao(
                opcao_id=_op_edit["id"],
                strike=strike_edit,
                vencimento=str(venc_edit),
                quantidade=int(qtd_edit),
                premio_unitario=premio_edit,
                observacao=obs_edit,
            )
            st.success("✅ Posição atualizada.")
            st.rerun()
else:
    st.caption("Nenhuma posição aberta para editar.")

st.divider()

# ---------------------------------------------------------------------------
# Full history
# ---------------------------------------------------------------------------
st.subheader("Histórico Completo")

if todas:
    df = pd.DataFrame(todas)
    df["premio_total"] = df["premio_total"].map(lambda x: f"R$ {x:,.2f}")
    df["strike"] = df["strike"].map(lambda x: f"R$ {x:.2f}")
    cols_show = [
        "id", "data_abertura", "tipo", "ativo", "codigo_opcao",
        "strike", "vencimento", "quantidade", "premio_total", "status", "data_fechamento",
    ]
    st.dataframe(df[cols_show], use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma operação registrada ainda.")
