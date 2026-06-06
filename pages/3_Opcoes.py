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


def _preco_ativo(ativo: str) -> float | None:
    """Return the current spot price of the underlying asset.

    Parameters
    ----------
    ativo : str
        Underlying asset ticker (e.g. 'BOVA11', 'PETR4').

    Returns
    -------
    float or None
        Current price in BRL, or None if unavailable.
    """
    d = _dados_mkt.get(ativo) or mercado.buscar_dados_ativo_opcao(ativo)
    preco = d.get("preco")
    return preco if preco and preco > 0 else None


def _distancia_strike(tipo: str, preco_ativo: float, strike: float) -> str:
    """Format the distance between spot price and strike as a signed percentage.

    For PUT: positive = OTM (spot above strike), negative = ITM.
    For CALL: positive = OTM (spot below strike), negative = ITM.

    Parameters
    ----------
    tipo : str
        'PUT' or 'CALL'.
    preco_ativo : float
        Current spot price.
    strike : float
        Option strike.

    Returns
    -------
    str
        Formatted string, e.g. '+4.2% OTM' or '-1.8% ITM'.
    """
    pct = (preco_ativo - strike) / strike * 100
    if tipo == "PUT":
        otm = pct >= 0
        sinal = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    else:  # CALL
        otm = pct <= 0
        sinal = f"{-pct:.1f}%" if pct <= 0 else f"-{-pct:.1f}%"
        sinal = f"+{abs(pct):.1f}%" if pct <= 0 else f"-{abs(pct):.1f}%"
    label = "OTM" if otm else "ITM"
    return f"{sinal} {label}"

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
# Open positions — interactive table + unified action panel
# ---------------------------------------------------------------------------
st.subheader("Posições Abertas")

# Session-state defaults
if "acao_opcao" not in st.session_state:
    st.session_state.acao_opcao = None   # "nova" | "editar" | "encerrar" | "rolar"

hoje = datetime.date.today()

if abertas:
    # Build display dataframe
    _rows_ab = []
    for op in abertas:
        venc = op["vencimento"]
        if isinstance(venc, str):
            venc = datetime.date.fromisoformat(venc)
        dias = (venc - hoje).days
        prob = _prob_exercicio(op["tipo"], op["ativo"], op["strike"], dias)
        spot = _preco_ativo(op["ativo"])
        dist = _distancia_strike(op["tipo"], spot, op["strike"]) if spot else "—"
        _rows_ab.append({
            "Código": (op["codigo_opcao"] or "—").upper(),
            "Tipo": op["tipo"],
            "Strike": f"R$ {op['strike']:.2f}",
            "Spot": f"R$ {spot:.2f}" if spot else "—",
            "Distância": dist,
            "Dias": f"{'⚠️ ' if dias <= 5 else ''}{dias}",
            "Qtd": op["quantidade"],
            "Prêmio Total": f"R$ {op['premio_total']:.2f}",
            "Prob. Exercício": _prob_badge(prob),
            "Obs.": op["observacao"] or "",
        })

    df_ab = pd.DataFrame(_rows_ab)

    # Row color by tipo via pandas Styler (PUT=blue, CALL=green)
    def _color_tipo(row: pd.Series) -> list[str]:
        bg = "#0d2137" if row["Tipo"] == "PUT" else "#0d2b1a"
        return [f"background-color: {bg}; color: white"] * len(row)

    df_styled = df_ab.style.apply(_color_tipo, axis=1)

    # "Nova venda" button above the table
    if st.button("📋 Nova venda", key="btn_nova"):
        st.session_state.acao_opcao = "nova"

    # Selectable dataframe
    sel = st.dataframe(
        df_styled,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tbl_abertas",
    )
    st.caption(
        "🔵 PUT  🟩 CALL  ·  "
        "🟢 < 25%  🟡 25–50%  🔴 > 50% — prob. via Black-Scholes, vol. histórica 20d.  "
        "Clique em uma linha para ver as ações disponíveis."
    )

    selected_rows = sel.selection.rows
    _op_ativa: dict | None = abertas[selected_rows[0]] if selected_rows else None

    # ── Action buttons (only when a row is selected) ──────────────────────
    if _op_ativa and st.session_state.acao_opcao != "nova":
        _cod_label = (_op_ativa["codigo_opcao"] or "—").upper()
        st.markdown(
            f"**Selecionado:** {_cod_label} — {_op_ativa['tipo']} "
            f"Strike R$ {_op_ativa['strike']:.2f} · Venc. {_op_ativa['vencimento']}"
        )
        _a1, _a2, _a3, _a4 = st.columns(4)
        if _a1.button("✏️ Editar",    use_container_width=True, key="btn_editar"):
            st.session_state.acao_opcao = "editar"
        if _a2.button("✅ Encerrar",  use_container_width=True, key="btn_encerrar"):
            st.session_state.acao_opcao = "encerrar"
        if _a3.button("🔄 Rolar",     use_container_width=True, key="btn_rolar"):
            st.session_state.acao_opcao = "rolar"
        if _a4.button("✖ Cancelar",   use_container_width=True, key="btn_cancel"):
            st.session_state.acao_opcao = None

    # ══════════════════════════════════════════════════════════════════════
    # PANEL: Nova venda
    # ══════════════════════════════════════════════════════════════════════
    if st.session_state.acao_opcao == "nova":
        st.subheader("📋 Registrar Nova Venda")
        _codigo_preview = st.text_input(
            "Código da opção",
            placeholder="ex: BOVAR169 ou BOVAR164W1",
            key="codigo_input",
        ).upper().strip()
        _parsed = _parse_codigo(_codigo_preview) if _codigo_preview else {"ok": False}
        _venc_sugerido = hoje + datetime.timedelta(days=30)
        if _codigo_preview and _parsed["ok"]:
            _venc_sugerido = _sugerir_vencimento(_parsed["mes_idx"], _parsed["semana"])
            st.success(
                f"✅ **{_parsed['ativo']}** · **{_parsed['tipo']}** · "
                f"vencimento sugerido **{_venc_sugerido.strftime('%d/%m/%Y')}**"
                + (f" · {_parsed['semana']}" if _parsed["semana"] else "")
            )
        elif _codigo_preview:
            st.warning("⚠️ Código não reconhecido.")

        with st.form("form_nova", clear_on_submit=True):
            n1, n2, n3 = st.columns(3)
            strike_op = n1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=100.0)
            venc_op   = n2.date_input("Vencimento", value=_venc_sugerido)
            qtd_op    = n3.number_input("Quantidade", min_value=1, step=1)
            n4, n5 = st.columns([2, 1])
            premio_op = n4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_op    = n5.text_input("Observação")
            _total_p  = qtd_op * premio_op
            _reserva  = strike_op * qtd_op if _parsed.get("tipo") == "PUT" else 0.0
            st.markdown(
                f"💰 **Prêmio total:** R$ {_total_p:,.2f}"
                + (f"  |  🔒 **Reserva:** R$ {_reserva:,.2f}" if _reserva else "")
            )
            if st.form_submit_button("✅ Registrar venda", use_container_width=True):
                if not _parsed["ok"]:
                    st.error("Informe um código válido antes de registrar.")
                else:
                    banco.inserir_opcao(
                        data_abertura=str(hoje),
                        tipo=_parsed["tipo"],
                        ativo=_parsed["ativo"],
                        codigo_opcao=_codigo_preview,
                        strike=strike_op,
                        vencimento=str(venc_op),
                        quantidade=int(qtd_op),
                        premio_unitario=premio_op,
                        observacao=obs_op,
                    )
                    st.session_state.acao_opcao = None
                    st.success(f"✅ {_parsed['tipo']} **{_codigo_preview}** registrada — R$ {_total_p:,.2f}")
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # PANEL: Editar
    # ══════════════════════════════════════════════════════════════════════
    elif st.session_state.acao_opcao == "editar" and _op_ativa:
        st.subheader("✏️ Editar Posição")
        _venc_edit = _op_ativa["vencimento"]
        if isinstance(_venc_edit, str):
            _venc_edit = datetime.date.fromisoformat(_venc_edit)
        with st.form("form_editar", clear_on_submit=False):
            e1, e2, e3 = st.columns(3)
            strike_edit = e1.number_input("Strike (R$)", value=float(_op_ativa["strike"]), min_value=0.01, step=0.50, format="%.2f")
            venc_edit   = e2.date_input("Vencimento", value=_venc_edit)
            qtd_edit    = e3.number_input("Quantidade", value=int(_op_ativa["quantidade"]), min_value=1, step=1)
            e4, e5 = st.columns([2, 1])
            premio_edit = e4.number_input("Prêmio unitário (R$)", value=float(_op_ativa["premio_unitario"]), min_value=0.0001, step=0.01, format="%.4f")
            obs_edit    = e5.text_input("Observação", value=_op_ativa.get("observacao") or "")
            if st.form_submit_button("💾 Salvar alterações", use_container_width=True):
                banco.editar_opcao(
                    opcao_id=_op_ativa["id"],
                    strike=strike_edit,
                    vencimento=str(venc_edit),
                    quantidade=int(qtd_edit),
                    premio_unitario=premio_edit,
                    observacao=obs_edit,
                )
                st.session_state.acao_opcao = None
                st.success("✅ Posição atualizada.")
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # PANEL: Encerrar
    # ══════════════════════════════════════════════════════════════════════
    elif st.session_state.acao_opcao == "encerrar" and _op_ativa:
        st.subheader("✅ Encerrar Posição")
        with st.form("form_fechar", clear_on_submit=True):
            fc1, fc2, fc3 = st.columns(3)
            status_novo   = fc1.selectbox("Novo status", ["EXPIRADA", "EXERCIDA"])
            data_fech     = fc2.date_input("Data de fechamento", value=hoje)
            recompra_unit = fc3.number_input(
                "Prêmio recompra (R$/ação)",
                min_value=0.0, value=0.0, step=0.01, format="%.4f",
                help="0 se expirou sem valor ou se foi exercida.",
            )
            _resultado = _op_ativa["premio_total"] - recompra_unit * _op_ativa["quantidade"]
            _cor_res   = "🟢" if _resultado >= 0 else "🔴"
            st.markdown(
                f"**Prêmio recebido:** R$ {_op_ativa['premio_total']:,.2f}  |  "
                f"**Custo recompra:** R$ {recompra_unit * _op_ativa['quantidade']:,.2f}  |  "
                f"{_cor_res} **Resultado:** R$ {_resultado:,.2f}"
            )
            if st.form_submit_button("Encerrar posição", use_container_width=True):
                banco.fechar_opcao(_op_ativa["id"], status_novo, str(data_fech), premio_recompra=recompra_unit)
                st.session_state.acao_opcao = None
                st.success(f"Posição encerrada — resultado: R$ {_resultado:,.2f}")
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # PANEL: Rolar
    # ══════════════════════════════════════════════════════════════════════
    elif st.session_state.acao_opcao == "rolar" and _op_ativa:
        st.subheader("🔄 Rolar Posição")
        _roll_codigo = st.text_input(
            "Código da NOVA opção",
            placeholder="ex: BOVAS170",
            key="roll_codigo_input",
        ).upper().strip()
        _roll_parsed = _parse_codigo(_roll_codigo) if _roll_codigo else {"ok": False}
        _roll_venc_sug = (
            _sugerir_vencimento(_roll_parsed["mes_idx"], _roll_parsed["semana"])
            if _roll_parsed.get("ok") else hoje + datetime.timedelta(days=30)
        )
        if _roll_codigo and _roll_parsed["ok"]:
            st.success(
                f"✅ **{_roll_parsed['ativo']}** · **{_roll_parsed['tipo']}** · "
                f"vencimento sugerido **{_roll_venc_sug.strftime('%d/%m/%Y')}**"
                + (f" · {_roll_parsed['semana']}" if _roll_parsed["semana"] else "")
            )
        elif _roll_codigo:
            st.warning("⚠️ Código não reconhecido.")

        with st.form("form_rolar", clear_on_submit=True):
            st.markdown("**Fechamento da posição atual**")
            r1, r2 = st.columns(2)
            data_roll     = r1.date_input("Data do roll", value=hoje)
            recompra_roll = r2.number_input("Prêmio recompra (R$/ação)", min_value=0.0, value=0.0, step=0.01, format="%.4f")

            st.markdown("**Nova opção vendida**")
            rn1, rn2, rn3 = st.columns(3)
            strike_roll = rn1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=float(_op_ativa["strike"]))
            venc_roll   = rn2.date_input("Vencimento", value=_roll_venc_sug)
            qtd_roll    = rn3.number_input("Quantidade", min_value=1, step=1, value=int(_op_ativa["quantidade"]))
            rn4, rn5 = st.columns([2, 1])
            premio_roll = rn4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_roll    = rn5.text_input("Observação")

            _custo_rc  = recompra_roll * _op_ativa["quantidade"]
            _cred_novo = premio_roll * qtd_roll
            _cred_liq  = _cred_novo - _custo_rc
            _cor_liq   = "🟢" if _cred_liq >= 0 else "🔴"
            st.markdown(
                f"**Custo recompra:** R$ {_custo_rc:,.2f}  |  "
                f"**Prêmio novo:** R$ {_cred_novo:,.2f}  |  "
                f"{_cor_liq} **Crédito líquido:** R$ {_cred_liq:,.2f}"
            )
            if st.form_submit_button("🔄 Confirmar roll", use_container_width=True):
                if not _roll_parsed.get("ok"):
                    st.error("Informe o código da nova opção antes de confirmar.")
                else:
                    novo_id = banco.rolar_opcao(
                        opcao_id=_op_ativa["id"],
                        data_fechamento=str(data_roll),
                        premio_recompra=recompra_roll,
                        tipo=_roll_parsed["tipo"],
                        ativo=_roll_parsed["ativo"],
                        codigo_opcao=_roll_codigo,
                        strike=strike_roll,
                        vencimento=str(venc_roll),
                        quantidade=int(qtd_roll),
                        premio_unitario=premio_roll,
                        observacao=obs_roll,
                    )
                    st.session_state.acao_opcao = None
                    st.success(f"✅ Roll executado — nova posição #{novo_id} **{_roll_codigo}**. Crédito: R$ {_cred_liq:,.2f}")
                    st.rerun()

else:
    st.info("Nenhuma posição aberta.")
    if st.button("📋 Nova venda", key="btn_nova_vazia"):
        st.session_state.acao_opcao = "nova"

    if st.session_state.acao_opcao == "nova":
        st.subheader("📋 Registrar Nova Venda")
        _codigo_preview = st.text_input(
            "Código da opção",
            placeholder="ex: BOVAR169 ou BOVAR164W1",
            key="codigo_input_vazio",
        ).upper().strip()
        _parsed = _parse_codigo(_codigo_preview) if _codigo_preview else {"ok": False}
        _venc_sugerido = hoje + datetime.timedelta(days=30)
        if _codigo_preview and _parsed["ok"]:
            _venc_sugerido = _sugerir_vencimento(_parsed["mes_idx"], _parsed["semana"])
            st.success(
                f"✅ **{_parsed['ativo']}** · **{_parsed['tipo']}** · "
                f"vencimento sugerido **{_venc_sugerido.strftime('%d/%m/%Y')}**"
            )
        elif _codigo_preview:
            st.warning("⚠️ Código não reconhecido.")

        with st.form("form_nova_vazia", clear_on_submit=True):
            n1, n2, n3 = st.columns(3)
            strike_op = n1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=100.0)
            venc_op   = n2.date_input("Vencimento", value=_venc_sugerido)
            qtd_op    = n3.number_input("Quantidade", min_value=1, step=1)
            n4, n5 = st.columns([2, 1])
            premio_op = n4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_op    = n5.text_input("Observação")
            _total_p  = qtd_op * premio_op
            _reserva  = strike_op * qtd_op if _parsed.get("tipo") == "PUT" else 0.0
            st.markdown(
                f"💰 **Prêmio total:** R$ {_total_p:,.2f}"
                + (f"  |  🔒 **Reserva:** R$ {_reserva:,.2f}" if _reserva else "")
            )
            if st.form_submit_button("✅ Registrar venda", use_container_width=True):
                if not _parsed["ok"]:
                    st.error("Informe um código válido.")
                else:
                    banco.inserir_opcao(
                        data_abertura=str(hoje),
                        tipo=_parsed["tipo"],
                        ativo=_parsed["ativo"],
                        codigo_opcao=_codigo_preview,
                        strike=strike_op,
                        vencimento=str(venc_op),
                        quantidade=int(qtd_op),
                        premio_unitario=premio_op,
                        observacao=obs_op,
                    )
                    st.session_state.acao_opcao = None
                    st.success(f"✅ Registrada — R$ {_total_p:,.2f}")
                    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Full history
# ---------------------------------------------------------------------------
st.subheader("Histórico Completo")

if todas:
    hist_rows = []
    for op in todas:
        premio_total   = op.get("premio_total") or 0.0
        recompra_unit  = op.get("premio_recompra") or 0.0
        qtd            = op.get("quantidade") or 0
        custo_recompra = recompra_unit * qtd
        resultado      = premio_total - custo_recompra if op["status"] != "ABERTA" else None
        origem         = op.get("origem_id")
        hist_rows.append({
            "ID": op["id"],
            "Roll de": f"#{origem}" if origem else "—",
            "Abertura": op["data_abertura"],
            "Tipo": op["tipo"],
            "Ativo": op["ativo"],
            "Código": (op["codigo_opcao"] or "—").upper(),
            "Strike": f"R$ {op['strike']:.2f}",
            "Vencimento": op["vencimento"],
            "Qtd": qtd,
            "Prêmio Rec.": f"R$ {premio_total:,.2f}",
            "Recompra": f"R$ {custo_recompra:,.2f}" if custo_recompra else "—",
            "Resultado": (
                f"{'🟢' if resultado >= 0 else '🔴'} R$ {resultado:,.2f}"
                if resultado is not None else "aberta"
            ),
            "Status": op["status"],
            "Fechamento": op.get("data_fechamento") or "—",
        })
    df_hist = pd.DataFrame(hist_rows)

    # Color rows: ABERTA neutral, positive resultado green, negative red
    def _row_color(row: dict) -> str:
        if row["Status"] == "ABERTA":
            return "#0e1117"
        res_str = row["Resultado"]
        if "🟢" in res_str:
            return "#0d2b1a"
        if "🔴" in res_str:
            return "#2b0d0d"
        return "#0e1117"

    _row_cols_hist = [row for row in hist_rows]
    _fill_colors = [[_row_color(r) for r in _row_cols_hist]] * len(df_hist.columns)

    fig_hist = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c}</b>" for c in df_hist.columns],
            fill_color="#1a1d27",
            font=dict(color="white", size=12),
            align="center",
            line_color="#333",
        ),
        cells=dict(
            values=[df_hist[c].tolist() for c in df_hist.columns],
            fill_color=_fill_colors,
            font=dict(color="white", size=11),
            align="center",
            line_color="#222",
            height=30,
        ),
    ))
    fig_hist.update_layout(
        margin=dict(t=0, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        height=60 + len(hist_rows) * 34,
    )
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Nenhuma operação registrada ainda.")
