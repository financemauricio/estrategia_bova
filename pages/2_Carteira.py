"""Carteira — central operations page: options, ETF positions, cash, contributions.

Layout
------
Zone 1 : Status strip   — 5 KPIs always visible (patrimônio, caixa, comprometido, livre, próximo vencimento)
Zone 2 : Alert banner   — shown only when a position expires in ≤ 7 days
Zone 3 : Options table  — selectable rows (PUT=blue, CALL=green) + contextual action panel
Zone 4 : Performance    — cumulative return vs IBOV, IVV, HASH11
Zone 5 : Expanders      — ETF positions, cash, aportes, options history
"""

from __future__ import annotations

import datetime
import math
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import ALOCACAO_ALVO, APORTE_MENSAL
from modulos import banco, bs, mercado, performance
from modulos.componentes import (
    distancia_strike,
    preco_ativo,
    prob_badge,
    prob_exercicio,
    validar_saida_caixa,
)


# ─── B3 option code parser ────────────────────────────────────────────────────

_CALL_MONTHS = "ABCDEFGHIJKL"
_PUT_MONTHS  = "MNOPQRSTUVWX"
_MONTH_NAMES = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"]

_PREFIXO_ATIVO: dict[str, str] = {
    "BOVA": "BOVA11", "HASH": "HASH11", "SMAL": "SMAL11", "IVVB": "IVVB11",
    "PETR": "PETR4",  "VALE": "VALE3",  "PRIO": "PRIO3",  "RECV": "RECV3",
    "ITUB": "ITUB4",  "BBDC": "BBDC4",  "BBAS": "BBAS3",  "SANB": "SANB11",
    "ABEV": "ABEV3",  "LREN": "LREN3",  "MGLU": "MGLU3",
    "WEGE": "WEGE3",  "EMBR": "EMBR3",  "TOTS": "TOTS3",  "INTB": "INTB3",
    "EQTL": "EQTL3",  "ELET": "ELET3",  "CPFE": "CPFE3",
    "VIVT": "VIVT3",  "SUZB": "SUZB3",  "KLBN": "KLBN11",
    "RADL": "RADL3",  "HAPV": "HAPV3",
    "RENT": "RENT3",  "GOLL": "GOLL4",  "AZUL": "AZUL4",
}


def _nª_sexta(ano: int, mes: int, n: int) -> datetime.date:
    """Return the Nth Friday of a given month/year."""
    primeiro = datetime.date(ano, mes, 1)
    dias_ate_sexta = (4 - primeiro.weekday()) % 7
    return primeiro + datetime.timedelta(days=dias_ate_sexta) + datetime.timedelta(weeks=n - 1)


def _sugerir_vencimento(mes_idx: int, semana: str) -> datetime.date:
    """Suggest expiry date: 3rd Friday (monthly) or Nth Friday (weekly W1–W4)."""
    hoje = datetime.date.today()
    for delta_ano in range(2):
        ano = hoje.year + delta_ano
        try:
            n    = int(semana[1]) if semana else 3
            data = _nª_sexta(ano, mes_idx, n)
            if data >= hoje:
                return data
        except (ValueError, OverflowError):
            continue
    return hoje + datetime.timedelta(days=30)


def _parse_codigo(codigo: str) -> dict:
    """Parse a B3 option code and return extracted fields."""
    codigo = codigo.upper().strip()
    m = re.match(r'^([A-Z]{4})([A-Z])(\d+)(W\d)?$', codigo)
    if not m:
        return {"ok": False}
    prefixo, letra_mes, strike_str, semana = m.groups()
    ativo = _PREFIXO_ATIVO.get(prefixo, prefixo)
    if letra_mes in _CALL_MONTHS:
        tipo, mes_idx = "CALL", _CALL_MONTHS.index(letra_mes) + 1
    elif letra_mes in _PUT_MONTHS:
        tipo, mes_idx = "PUT", _PUT_MONTHS.index(letra_mes) + 1
    else:
        return {"ok": False}
    return {
        "ok": True, "ativo": ativo, "tipo": tipo,
        "mes_idx": mes_idx, "mes_nome": _MONTH_NAMES[mes_idx - 1],
        "strike_raw": strike_str, "semana": semana or "",
    }


# ─── Page title ───────────────────────────────────────────────────────────────

st.title("💼 Carteira")

# ─── Data loading (single block — all queries cached) ─────────────────────────

dados      = mercado.buscar_dados_mercado()
posicoes   = banco.listar_posicoes()
saldo      = banco.saldo_caixa()
abertas    = banco.listar_opcoes("ABERTA")
todas_op   = banco.listar_opcoes()
aportes    = banco.listar_aportes()
patrimonio = mercado.calcular_patrimonio(posicoes, dados)
total_etf  = patrimonio["total_etf"]
pat_total  = total_etf + saldo
selic      = bs.buscar_selic()
total_ap   = banco.total_aportado()
total_pr   = banco.total_premios_recebidos()

# ─── Derived values ───────────────────────────────────────────────────────────

hoje         = datetime.date.today()
puts_abertas = [op for op in abertas if op["tipo"] == "PUT"]
comprometido = sum(op["strike"] * op["quantidade"] for op in puts_abertas)
caixa_livre  = saldo - comprometido
pct_comp     = comprometido / saldo if saldo > 0 else 0.0

_ab_sorted = sorted(
    abertas,
    key=lambda x: datetime.date.fromisoformat(x["vencimento"])
    if isinstance(x["vencimento"], str) else x["vencimento"],
)
_proximo_cod  = (_ab_sorted[0]["codigo_opcao"] or "—").upper() if _ab_sorted else None
_proximo_dias: int | None = None
if _ab_sorted:
    _v = _ab_sorted[0]["vencimento"]
    if isinstance(_v, str):
        _v = datetime.date.fromisoformat(_v)
    _proximo_dias = (_v - hoje).days

# ─── Zone 1: Status strip ─────────────────────────────────────────────────────

z1, z2, z3, z4, z5 = st.columns(5)
z1.metric("Patrimônio", f"R$ {pat_total:,.2f}")
z2.metric("Caixa total", f"R$ {saldo:,.2f}")
z3.metric("Comprometido PUTs", f"R$ {comprometido:,.2f}")
z4.metric(
    "Caixa livre",
    f"R$ {caixa_livre:,.2f}",
    delta=f"{(1 - pct_comp) * 100:.1f}% disponível",
    delta_color="normal" if caixa_livre >= 0 else "inverse",
)
if _proximo_cod and _proximo_dias is not None:
    z5.metric(
        "Próximo vencimento",
        _proximo_cod,
        delta=f"em {_proximo_dias} dia{'s' if _proximo_dias != 1 else ''}",
        delta_color="inverse" if _proximo_dias <= 5 else ("off" if _proximo_dias <= 10 else "normal"),
    )
else:
    z5.metric("Próximo vencimento", "—")

# ─── Zone 2: Alert banner (only when ≤ 7 days) ───────────────────────────────

_urgentes: list[tuple[dict, int]] = []
for _op in abertas:
    _v = _op["vencimento"]
    if isinstance(_v, str):
        _v = datetime.date.fromisoformat(_v)
    _d = (_v - hoje).days
    if _d <= 7:
        _urgentes.append((_op, _d))
_urgentes.sort(key=lambda x: x[1])

for _op, _d in _urgentes:
    _cod = (_op["codigo_opcao"] or "—").upper()
    _msg = (
        f"{'🚨' if _d <= 2 else '⚠️'} **{_cod}** — {_op['tipo']} "
        f"Strike R$ {_op['strike']:.2f} · vence em **{_d} dia{'s' if _d != 1 else ''}**"
    )
    (st.error if _d <= 2 else st.warning)(_msg)

st.divider()

# ─── Zone 3: Options table + contextual action panel ─────────────────────────

st.subheader("Posições em Opções")

if "acao_opcao" not in st.session_state:
    st.session_state.acao_opcao = None

if abertas:
    # Build styled dataframe (ordered by vencimento ASC)
    _rows_ab = []
    for _op in _ab_sorted:
        _v = _op["vencimento"]
        if isinstance(_v, str):
            _v = datetime.date.fromisoformat(_v)
        _d = (_v - hoje).days
        _prob = prob_exercicio(_op["tipo"], _op["ativo"], _op["strike"], _d, dados, selic)
        _spot = preco_ativo(_op["ativo"], dados)
        _dist = distancia_strike(_op["tipo"], _spot, _op["strike"]) if _spot else "—"
        _rows_ab.append({
            "Código":          (_op["codigo_opcao"] or "—").upper(),
            "Tipo":            _op["tipo"],
            "Strike":          f"R$ {_op['strike']:.2f}",
            "Spot":            f"R$ {_spot:.2f}" if _spot else "—",
            "Distância":       _dist,
            "Dias":            f"{'⚠️ ' if _d <= 5 else ''}{_d}",
            "Qtd":             _op["quantidade"],
            "Prêmio Total":    f"R$ {_op['premio_total']:.2f}",
            "Prob. Exercício": prob_badge(_prob),
            "Obs.":            _op.get("observacao") or "",
        })

    df_ab = pd.DataFrame(_rows_ab)

    def _color_tipo(row: pd.Series) -> list[str]:
        bg = "#0d2137" if row["Tipo"] == "PUT" else "#0d2b1a"
        return [f"background-color: {bg}; color: white"] * len(row)

    if st.button("📋 Nova venda", key="btn_nova"):
        st.session_state.acao_opcao = "nova"

    sel = st.dataframe(
        df_ab.style.apply(_color_tipo, axis=1),
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="tbl_abertas",
    )
    st.caption(
        "🔵 PUT  🟩 CALL  ·  🟢 < 25%  🟡 25–50%  🔴 > 50% — "
        "prob. via Black-Scholes, vol. histórica 20d.  Clique em uma linha para ver as ações."
    )

    _sel_rows  = sel.selection.rows
    # Map selected row index back to the abertas list (ab_sorted order)
    _op_ativa: dict | None = _ab_sorted[_sel_rows[0]] if _sel_rows else None

    # Action buttons (shown when a row is selected and action ≠ nova)
    if _op_ativa and st.session_state.acao_opcao != "nova":
        _cod_lbl = (_op_ativa["codigo_opcao"] or "—").upper()
        st.markdown(
            f"**Selecionado:** {_cod_lbl} — {_op_ativa['tipo']} "
            f"Strike R$ {_op_ativa['strike']:.2f} · Venc. {_op_ativa['vencimento']}"
        )
        _a1, _a2, _a3, _a4 = st.columns(4)
        if _a1.button("✏️ Editar",   use_container_width=True, key="btn_editar"):
            st.session_state.acao_opcao = "editar"
        if _a2.button("✅ Encerrar", use_container_width=True, key="btn_encerrar"):
            st.session_state.acao_opcao = "encerrar"
        if _a3.button("🔄 Rolar",    use_container_width=True, key="btn_rolar"):
            st.session_state.acao_opcao = "rolar"
        if _a4.button("✖ Cancelar",  use_container_width=True, key="btn_cancel"):
            st.session_state.acao_opcao = None

    # ── Panel: Nova venda ──────────────────────────────────────────────────
    if st.session_state.acao_opcao == "nova":
        st.subheader("📋 Registrar Nova Venda")
        _cod_prev = st.text_input(
            "Código da opção", placeholder="ex: BOVAR169 ou BOVAR164W1", key="codigo_input",
        ).upper().strip()
        _prs = _parse_codigo(_cod_prev) if _cod_prev else {"ok": False}
        _venc_s = hoje + datetime.timedelta(days=30)
        if _cod_prev and _prs["ok"]:
            _venc_s = _sugerir_vencimento(_prs["mes_idx"], _prs["semana"])
            st.success(
                f"✅ **{_prs['ativo']}** · **{_prs['tipo']}** · "
                f"vencimento sugerido **{_venc_s.strftime('%d/%m/%Y')}**"
                + (f" · {_prs['semana']}" if _prs["semana"] else "")
            )
        elif _cod_prev:
            st.warning("⚠️ Código não reconhecido — verifique a nomenclatura B3.")

        with st.form("form_nova", clear_on_submit=True):
            n1, n2, n3 = st.columns(3)
            strike_n = n1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=100.0)
            venc_n   = n2.date_input("Vencimento", value=_venc_s)
            qtd_n    = n3.number_input("Quantidade", min_value=1, step=1)
            n4, n5 = st.columns([2, 1])
            premio_n = n4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_n    = n5.text_input("Observação")
            _total_n  = qtd_n * premio_n
            _reserva_n = strike_n * qtd_n if _prs.get("tipo") == "PUT" else 0.0
            st.markdown(
                f"💰 **Prêmio total:** R$ {_total_n:,.2f} (crédito no caixa)"
                + (f"  |  🔒 **Reserva necessária:** R$ {_reserva_n:,.2f}" if _reserva_n else "")
            )
            if _reserva_n and caixa_livre + _total_n < _reserva_n:
                st.warning(
                    f"Após o prêmio, o caixa livre ficará em R$ {caixa_livre + _total_n:,.2f}, "
                    f"abaixo da reserva de R$ {_reserva_n:,.2f}. Considere aportar antes de vender a PUT."
                )
            if st.form_submit_button("✅ Registrar venda", use_container_width=True):
                if not _prs["ok"]:
                    st.error("Informe um código válido antes de registrar.")
                else:
                    banco.inserir_opcao(
                        data_abertura=str(hoje), tipo=_prs["tipo"], ativo=_prs["ativo"],
                        codigo_opcao=_cod_prev, strike=strike_n, vencimento=str(venc_n),
                        quantidade=int(qtd_n), premio_unitario=premio_n, observacao=obs_n,
                    )
                    st.session_state.acao_opcao = None
                    st.success(f"✅ {_prs['tipo']} **{_cod_prev}** registrada — R$ {_total_n:,.2f}")
                    st.rerun()

    # ── Panel: Editar ──────────────────────────────────────────────────────
    elif st.session_state.acao_opcao == "editar" and _op_ativa:
        st.subheader("✏️ Editar Posição")
        _ve = _op_ativa["vencimento"]
        if isinstance(_ve, str):
            _ve = datetime.date.fromisoformat(_ve)
        with st.form("form_editar", clear_on_submit=False):
            e1, e2, e3 = st.columns(3)
            strike_e = e1.number_input("Strike (R$)", value=float(_op_ativa["strike"]), min_value=0.01, step=0.50, format="%.2f")
            venc_e   = e2.date_input("Vencimento", value=_ve)
            qtd_e    = e3.number_input("Quantidade", value=int(_op_ativa["quantidade"]), min_value=1, step=1)
            e4, e5 = st.columns([2, 1])
            premio_e = e4.number_input("Prêmio unitário (R$)", value=float(_op_ativa["premio_unitario"]), min_value=0.0001, step=0.01, format="%.4f")
            obs_e    = e5.text_input("Observação", value=_op_ativa.get("observacao") or "")
            if st.form_submit_button("💾 Salvar alterações", use_container_width=True):
                banco.editar_opcao(
                    opcao_id=_op_ativa["id"], strike=strike_e, vencimento=str(venc_e),
                    quantidade=int(qtd_e), premio_unitario=premio_e, observacao=obs_e,
                )
                st.session_state.acao_opcao = None
                st.success("✅ Posição atualizada.")
                st.rerun()

    # ── Panel: Encerrar ────────────────────────────────────────────────────
    elif st.session_state.acao_opcao == "encerrar" and _op_ativa:
        st.subheader("✅ Encerrar Posição")
        fc1, fc2, fc3 = st.columns(3)
        status_f   = fc1.selectbox("Novo status", ["EXPIRADA", "EXERCIDA"], key="status_fechar")
        data_f     = fc2.date_input("Data de fechamento", value=hoje, key="data_fechar")
        recompra_f = fc3.number_input(
            "Prêmio recompra (R$/ação)", min_value=0.0, value=0.0, step=0.01, format="%.4f",
            key="recompra_fechar",
            help="Use apenas ao recomprar antes do vencimento. Deixe 0 se expirou ou foi exercida.",
            disabled=status_f == "EXERCIDA",
        )
        if status_f == "EXERCIDA":
            recompra_f = 0.0

        _custo_recompra = recompra_f * _op_ativa["quantidade"]
        _impacto_ex = (
            banco.impacto_exercicio(_op_ativa["tipo"], _op_ativa["strike"], _op_ativa["quantidade"])
            if status_f == "EXERCIDA"
            else None
        )
        _res = _op_ativa["premio_total"] - _custo_recompra

        st.markdown(
            f"**Prêmio recebido:** R$ {_op_ativa['premio_total']:,.2f}  |  "
            f"**Custo recompra:** R$ {_custo_recompra:,.2f}  |  "
            f"{'🟢' if _res >= 0 else '🔴'} **Resultado opção:** R$ {_res:,.2f}"
        )
        st.caption(f"Caixa atual: **R$ {saldo:,.2f}**  |  Caixa livre (após reservas PUT): **R$ {caixa_livre:,.2f}**")

        _erro_caixa: str | None = None
        if _custo_recompra > 0:
            _erro_caixa = validar_saida_caixa(saldo, _custo_recompra)
            if _erro_caixa:
                st.error(_erro_caixa)
            else:
                st.info(f"Recompra debitará **R$ {_custo_recompra:,.2f}** do caixa.")

        if _impacto_ex:
            if _impacto_ex["tipo"] == "SAIDA":
                _erro_ex = validar_saida_caixa(saldo, _impacto_ex["valor"])
                if _erro_ex:
                    _erro_caixa = _erro_ex
                    st.error(
                        f"Exercício de PUT exige **R$ {_impacto_ex['valor']:,.2f}** para compra das ações. {_erro_ex}"
                    )
                else:
                    st.warning(
                        f"Exercício debitará **R$ {_impacto_ex['valor']:,.2f}** do caixa "
                        f"(compra de {_op_ativa['quantidade']} {_op_ativa['ativo']} a R$ {_op_ativa['strike']:.2f})."
                    )
            else:
                st.success(
                    f"Exercício creditará **R$ {_impacto_ex['valor']:,.2f}** no caixa "
                    f"(venda de {_op_ativa['quantidade']} {_op_ativa['ativo']} a R$ {_op_ativa['strike']:.2f}). "
                    "Atualize manualmente a posição ETF se necessário."
                )

        with st.form("form_fechar", clear_on_submit=True):
            if st.form_submit_button("Encerrar posição", use_container_width=True, disabled=bool(_erro_caixa)):
                try:
                    banco.fechar_opcao(
                        _op_ativa["id"], status_f, str(data_f), premio_recompra=recompra_f,
                    )
                except banco.CaixaInsuficienteError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.acao_opcao = None
                    st.success(f"Posição encerrada — resultado: R$ {_res:,.2f}")
                    st.rerun()

    # ── Panel: Rolar ───────────────────────────────────────────────────────
    elif st.session_state.acao_opcao == "rolar" and _op_ativa:
        st.subheader("🔄 Rolar Posição")
        _roll_cod = st.text_input(
            "Código da NOVA opção", placeholder="ex: BOVAS170", key="roll_codigo_input",
        ).upper().strip()
        _roll_prs = _parse_codigo(_roll_cod) if _roll_cod else {"ok": False}
        _roll_vs  = (
            _sugerir_vencimento(_roll_prs["mes_idx"], _roll_prs["semana"])
            if _roll_prs.get("ok") else hoje + datetime.timedelta(days=30)
        )
        if _roll_cod and _roll_prs["ok"]:
            st.success(
                f"✅ **{_roll_prs['ativo']}** · **{_roll_prs['tipo']}** · "
                f"vencimento sugerido **{_roll_vs.strftime('%d/%m/%Y')}**"
                + (f" · {_roll_prs['semana']}" if _roll_prs["semana"] else "")
            )
        elif _roll_cod:
            st.warning("⚠️ Código não reconhecido.")
        with st.form("form_rolar", clear_on_submit=True):
            st.markdown("**Fechamento da posição atual**")
            r1, r2 = st.columns(2)
            data_r    = r1.date_input("Data do roll", value=hoje)
            recomp_r  = r2.number_input("Prêmio recompra (R$/ação)", min_value=0.0, value=0.0, step=0.01, format="%.4f")
            st.markdown("**Nova opção vendida**")
            rn1, rn2, rn3 = st.columns(3)
            strike_r  = rn1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=float(_op_ativa["strike"]))
            venc_r    = rn2.date_input("Vencimento", value=_roll_vs)
            qtd_r     = rn3.number_input("Quantidade", min_value=1, step=1, value=int(_op_ativa["quantidade"]))
            rn4, rn5 = st.columns([2, 1])
            premio_r  = rn4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_r     = rn5.text_input("Observação")
            _custo_r  = recomp_r * _op_ativa["quantidade"]
            _cred_r   = premio_r * qtd_r
            _liq_r    = _cred_r - _custo_r
            st.markdown(
                f"**Custo recompra:** R$ {_custo_r:,.2f}  |  "
                f"**Prêmio novo:** R$ {_cred_r:,.2f}  |  "
                f"{'🟢' if _liq_r >= 0 else '🔴'} **Crédito líquido:** R$ {_liq_r:,.2f}"
            )
            _erro_roll = validar_saida_caixa(saldo, _custo_r) if _custo_r > 0 else None
            if _erro_roll:
                st.error(_erro_roll)
            elif _custo_r > 0:
                st.info(f"Recompra no roll debitará **R$ {_custo_r:,.2f}** do caixa.")

            if st.form_submit_button(
                "🔄 Confirmar roll",
                use_container_width=True,
                disabled=bool(_erro_roll),
            ):
                if not _roll_prs.get("ok"):
                    st.error("Informe o código da nova opção antes de confirmar.")
                else:
                    try:
                        novo_id = banco.rolar_opcao(
                            opcao_id=_op_ativa["id"], data_fechamento=str(data_r),
                            premio_recompra=recomp_r, tipo=_roll_prs["tipo"],
                            ativo=_roll_prs["ativo"], codigo_opcao=_roll_cod,
                            strike=strike_r, vencimento=str(venc_r),
                            quantidade=int(qtd_r), premio_unitario=premio_r, observacao=obs_r,
                        )
                    except banco.CaixaInsuficienteError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.acao_opcao = None
                        st.success(
                            f"✅ Roll executado — posição #{novo_id} **{_roll_cod}** aberta. "
                            f"Crédito líquido: R$ {_liq_r:,.2f}"
                        )
                        st.rerun()

else:
    # No open positions — show new sale button only
    st.info("Nenhuma posição em opções aberta.")
    if st.button("📋 Nova venda", key="btn_nova_vazia"):
        st.session_state.acao_opcao = "nova"

    if st.session_state.acao_opcao == "nova":
        st.subheader("📋 Registrar Nova Venda")
        _cod_v = st.text_input(
            "Código da opção", placeholder="ex: BOVAR169 ou BOVAR164W1", key="codigo_input_vazio",
        ).upper().strip()
        _prs_v = _parse_codigo(_cod_v) if _cod_v else {"ok": False}
        _vs_v  = hoje + datetime.timedelta(days=30)
        if _cod_v and _prs_v["ok"]:
            _vs_v = _sugerir_vencimento(_prs_v["mes_idx"], _prs_v["semana"])
            st.success(f"✅ **{_prs_v['ativo']}** · **{_prs_v['tipo']}** · vencimento sugerido **{_vs_v.strftime('%d/%m/%Y')}**")
        elif _cod_v:
            st.warning("⚠️ Código não reconhecido.")
        with st.form("form_nova_v", clear_on_submit=True):
            n1, n2, n3 = st.columns(3)
            strike_nv = n1.number_input("Strike (R$)", min_value=1.0, step=0.50, format="%.2f", value=100.0)
            venc_nv   = n2.date_input("Vencimento", value=_vs_v)
            qtd_nv    = n3.number_input("Quantidade", min_value=1, step=1)
            n4, n5 = st.columns([2, 1])
            premio_nv = n4.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
            obs_nv    = n5.text_input("Observação")
            _tot_nv   = qtd_nv * premio_nv
            _res_nv   = strike_nv * qtd_nv if _prs_v.get("tipo") == "PUT" else 0.0
            st.markdown(
                f"💰 **Prêmio total:** R$ {_tot_nv:,.2f}"
                + (f"  |  🔒 **Reserva:** R$ {_res_nv:,.2f}" if _res_nv else "")
            )
            if st.form_submit_button("✅ Registrar venda", use_container_width=True):
                if not _prs_v["ok"]:
                    st.error("Informe um código válido.")
                else:
                    banco.inserir_opcao(
                        data_abertura=str(hoje), tipo=_prs_v["tipo"], ativo=_prs_v["ativo"],
                        codigo_opcao=_cod_v, strike=strike_nv, vencimento=str(venc_nv),
                        quantidade=int(qtd_nv), premio_unitario=premio_nv, observacao=obs_nv,
                    )
                    st.session_state.acao_opcao = None
                    st.success(f"✅ Registrada — R$ {_tot_nv:,.2f}")
                    st.rerun()

st.divider()

# ─── Performance vs benchmarks ───────────────────────────────────────────────
st.subheader("📈 Performance vs IBOV, IVV e HASH11")
try:
    _perf = performance.calcular_performance()
except Exception as _perf_exc:
    st.error(f"Erro ao calcular performance: {_perf_exc}")
    _perf = None

if _perf is None:
    st.info(
        "Registre posições ETF, aportes ou movimentações de caixa para "
        "habilitar o gráfico de performance."
    )
else:
    _res = _perf["resumo"]
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric(
        "Retorno sobre capital investido",
        f"{_res['carteira_pct']:+.2f} %",
        help="Retorno acumulado sobre o capital investido. Aportes são tratados como fluxos de capital, não como lucro.",
    )
    _alphas_ord = list(_res["alphas"].items())
    for _col, (_bench, _alpha) in zip((_m2, _m3, _m4), _alphas_ord[:3]):
        _lbl = _bench.replace("S&P 500 (IVV)", "IVV").replace("IBOV (BOVA11)", "IBOV")
        _col.metric(
            f"α vs {_lbl}",
            f"{_alpha:+.2f} pp",
            help="Diferença em pontos percentuais vs o índice no mesmo período",
        )
    _fig_perf = performance.grafico_performance(_perf["retornos"])
    st.plotly_chart(_fig_perf, use_container_width=True)
    _c1, _c2, _c3 = st.columns(3)
    _c1.metric("Capital investido", f"R$ {_res['fluxos_externos']:,.2f}")
    _c2.metric("Patrimônio atual", f"R$ {_res['patrimonio_atual']:,.2f}")
    _c3.metric("Fluxo externo líquido", f"R$ {_res['fluxos_externos']:,.2f}")
    _alpha_rows = [
        {
            "Referência": bench,
            "Retorno índice (%)": f"{_perf['retornos'][bench].iloc[-1]:+.2f}",
            "Carteira (%)":       f"{_res['carteira_pct']:+.2f}",
            "Diferença (pp)":     f"{alpha:+.2f}",
            "Status": "🟢 Acima" if alpha > 0 else ("🔴 Abaixo" if alpha < 0 else "—"),
        }
        for bench, alpha in _res["alphas"].items()
    ]
    st.dataframe(pd.DataFrame(_alpha_rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Desde {_res['data_inicio'].strftime('%d/%m/%Y')} · "
        f"Patrimônio R$ {_res['patrimonio_atual']:,.2f} · "
        "IBOV = BOVA11 · IVV em BRL · Benchmark 70/20/10 = alvo da estratégia. "
        "A performance da carteira é calculada sobre o capital investido, tratando aportes como fluxo de capital."
    )

st.divider()

# ─── Zone 4: Expanders ────────────────────────────────────────────────────────

# ── Expander 1: ETF positions + allocation ────────────────────────────────────
with st.expander("📊 Posições ETF e Alocação"):
    if posicoes:
        _rows_etf = []
        for pos in posicoes:
            ticker     = pos["ticker"]
            qtd_pos    = pos["quantidade"]
            pm_brl     = pos["preco_medio"]
            data_ent   = pos.get("data_entrada") or "—"
            custo_pos  = pos.get("custo_total") or (qtd_pos * pm_brl)
            d_pos      = dados.get(ticker, {})
            preco_usd  = d_pos.get("preco", 0.0)
            preco_brl_ = d_pos.get("preco_brl", preco_usd)
            usdbrl_    = d_pos.get("usdbrl", 1.0)
            em_usd_    = d_pos.get("moeda", "BRL") == "USD"
            valor_brl_ = qtd_pos * preco_brl_
            if em_usd_:
                pm_disp  = f"US$ {pm_brl / usdbrl_:.2f}" if usdbrl_ else f"R$ {pm_brl:.2f}"
                pr_disp  = f"US$ {preco_usd:.2f}"
                var_pm   = (preco_usd - pm_brl / usdbrl_) / (pm_brl / usdbrl_) if pm_brl and usdbrl_ else 0.0
            else:
                pm_disp  = f"R$ {pm_brl:.2f}"
                pr_disp  = f"R$ {preco_brl_:.2f}"
                var_pm   = (preco_brl_ - pm_brl) / pm_brl if pm_brl else 0.0
            sinal_ = "+" if var_pm >= 0 else ""
            _rows_etf.append({
                "Ticker": ticker,
                "Entrada": str(data_ent),
                "Qtd":    f"{qtd_pos:.4f}".rstrip("0").rstrip("."),
                "Preço Pago":  pm_disp,
                "Preço Atual": pr_disp,
                "Variação":    f"{sinal_}{var_pm*100:.2f} %",
                "Custo (R$)":  f"R$ {custo_pos:,.2f}",
                "Valor (R$)":  f"R$ {valor_brl_:,.2f}",
            })
        df_etf = pd.DataFrame(_rows_etf)
        fig_etf = go.Figure(go.Table(
            header=dict(values=[f"<b>{c}</b>" for c in df_etf.columns], fill_color="#1a1d27", font=dict(color="white", size=13), align="center", line_color="#333"),
            cells=dict(values=[df_etf[c].tolist() for c in df_etf.columns], fill_color="#0e1117", font=dict(color="white", size=12), align="center", line_color="#222", height=32),
        ))
        fig_etf.update_layout(margin=dict(t=0,b=0,l=0,r=0), paper_bgcolor="rgba(0,0,0,0)", height=60+len(_rows_etf)*36)
        st.plotly_chart(fig_etf, use_container_width=True)
        st.caption("IVV em US$ — PM convertido de R$ para US$ pela taxa atual. Valor Total sempre em R$.")
    else:
        st.info("Nenhuma posição ETF registrada.")

    st.markdown("**Alocação Atual vs Alvo**")
    _tks   = list(ALOCACAO_ALVO.keys())
    _alvo  = [ALOCACAO_ALVO[t] * 100 for t in _tks]
    _atual = [patrimonio["alocacao"].get(t, 0) * 100 for t in _tks]
    _por_t = patrimonio["por_ticker"]
    _under = {t: ALOCACAO_ALVO[t] for t in _tks if _por_t.get(t, 0) < ALOCACAO_ALVO[t] * total_etf}
    _denom = 1 - sum(ALOCACAO_ALVO[t] for t in _under)
    _novo_t = (total_etf - sum(_por_t.get(t, 0) for t in _under)) / _denom if _denom > 0 else None

    def _comprar(ticker: str) -> float:
        if ticker not in _under or not _novo_t:
            return 0.0
        return max(ALOCACAO_ALVO[ticker] * _novo_t - _por_t.get(ticker, 0.0), 0.0)

    _bar_cols  = ["#e67e22" if _atual[i] < _alvo[i] else "#2ecc71" for i in range(len(_tks))]
    _bar_texts = [
        f"<b>{_atual[i]:.1f}%</b><br>comprar R$ {_comprar(_tks[i]):,.0f}" if _atual[i] < _alvo[i]
        else f"<b>{_atual[i]:.1f}%</b>"
        for i in range(len(_tks))
    ]
    fig_aloc = go.Figure()
    fig_aloc.add_trace(go.Bar(name="Alvo %",  x=_tks, y=_alvo,  marker_color="#555", opacity=0.5, text=[f"{v:.0f}%" for v in _alvo],   textposition="outside"))
    fig_aloc.add_trace(go.Bar(name="Atual %", x=_tks, y=_atual, marker_color=_bar_cols, text=_bar_texts, textposition="inside", insidetextanchor="middle"))
    fig_aloc.update_layout(barmode="group", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", yanchor="bottom", y=1.02), height=300, margin=dict(t=10,b=10))
    _tot_comp = sum(_comprar(t) for t in _under)
    st.plotly_chart(fig_aloc, use_container_width=True)
    st.caption(f"Total a aportar para atingir o alvo: **R$ {_tot_comp:,.2f}** (sem vender)." if _under else "✅ Carteira dentro do alvo.")

    st.markdown("**Calculadora de Aporte**")
    _aporte_v = st.number_input("Valor do aporte (R$)", min_value=0.0, value=APORTE_MENSAL, step=100.0, format="%.2f", key="aporte_calc")
    _sug = mercado.sugerir_alocacao_aporte(_aporte_v, patrimonio, saldo, ALOCACAO_ALVO)
    _cs  = st.columns(len(_sug))
    for _col, (_tk, _val) in zip(_cs, _sug.items()):
        _d2      = dados.get(_tk, {})
        _pref    = _d2.get("preco_brl") or _d2.get("preco", 0.0)
        _qtd_s   = _val / _pref if _pref else 0.0
        _ml      = "US$" if _d2.get("moeda") == "USD" else "R$"
        _col.metric(_tk, f"R$ {_val:,.2f}", f"≈ {_qtd_s:.4f} cotas ({_ml})")

    st.markdown("**Registrar / Atualizar Posição ETF**")
    with st.form("form_posicao", clear_on_submit=True):
        pa, pb, pc, pd_col = st.columns(4)
        _tk_sel = pa.selectbox("Ticker", list(ALOCACAO_ALVO.keys()))
        _pos_atual = next((p for p in posicoes if p["ticker"] == _tk_sel), {})
        _qtd_default = float(_pos_atual.get("quantidade") or 0.0)
        _pm_default_brl = float(_pos_atual.get("preco_medio") or 0.0)
        _is_ivv = _tk_sel == "IVV"
        _pm_lbl = "Preço médio (US$) — será convertido para R$" if _is_ivv else "Preço médio (R$)"
        _usd_now = dados.get("IVV", {}).get("usdbrl", 1.0) if _is_ivv else 1.0
        _pm_default = _pm_default_brl / _usd_now if _is_ivv and _usd_now else _pm_default_brl
        _data_default = _pos_atual.get("data_entrada") or hoje
        if isinstance(_data_default, str):
            _data_default = datetime.date.fromisoformat(_data_default)
        _qtd_p  = pb.number_input("Quantidade total de cotas", min_value=0.0, value=_qtd_default, step=1.0, format="%.4f")
        _pm_raw = pc.number_input(_pm_lbl, min_value=0.0, value=float(_pm_default), step=0.01, format="%.4f")
        _data_pos = pd_col.date_input("Data de entrada", value=_data_default, help="Data econômica em que essa posição passou a fazer parte da carteira.")
        _pm_brl_ = _pm_raw * _usd_now if _is_ivv else _pm_raw
        _custo_calc = _qtd_p * _pm_brl_
        _custo_default = float(_pos_atual.get("custo_total") or _custo_calc)
        _custo_total = st.number_input(
            "Custo total da posição (R$)",
            min_value=0.0,
            value=_custo_default,
            step=100.0,
            format="%.2f",
            help="Capital originalmente usado para montar a posição inicial. Importante para performance por cota.",
        )
        if st.form_submit_button("Salvar posição"):
            banco.upsert_posicao(_tk_sel, _qtd_p, _pm_brl_, str(_data_pos), _custo_total)
            st.success(f"Posição de {_tk_sel} atualizada.")
            st.rerun()

# ── Expander 2: Cash ──────────────────────────────────────────────────────────
with st.expander("💵 Caixa e Movimentações"):
    st.caption(
        "Prêmios de opções entram automaticamente. Recompras e exercícios de PUT saem do caixa. "
        "Aportes creditam o valor recebido e debitam o que foi investido em ETFs. "
        "Para fluxo externo manual, use depósito, saque ou resgate na descrição."
    )
    _ck1, _ck2, _ck3 = st.columns(3)
    _ck1.metric("Saldo total", f"R$ {saldo:,.2f}")
    _ck2.metric("Comprometido PUTs", f"R$ {comprometido:,.2f}")
    _ck3.metric("Livre", f"R$ {caixa_livre:,.2f}", delta=f"{(1-pct_comp)*100:.1f}% disponível", delta_color="normal" if caixa_livre >= 0 else "inverse")

    if puts_abertas:
        _rows_p = []
        for _op in puts_abertas:
            _vp = _op["vencimento"]
            if isinstance(_vp, str):
                _vp = datetime.date.fromisoformat(_vp)
            _rp = _op["strike"] * _op["quantidade"]
            _rows_p.append({
                "Código": (_op["codigo_opcao"] or "—").upper(),
                "Strike": f"R$ {_op['strike']:.2f}", "Qtd": _op["quantidade"],
                "Reserva": f"R$ {_rp:,.2f}",
                "% caixa": f"{_rp/saldo*100:.1f}%" if saldo > 0 else "—",
                "Vencimento": str(_vp), "Dias": (_vp - hoje).days,
            })
        st.dataframe(pd.DataFrame(_rows_p), use_container_width=True, hide_index=True)

    with st.form("form_caixa", clear_on_submit=True):
        _cc1, _cc2, _cc3, _cc4 = st.columns([1, 1, 2, 2])
        _data_cx  = _cc1.date_input("Data")
        _tipo_cx  = _cc2.selectbox("Tipo", ["ENTRADA", "SAIDA"])
        _valor_cx = _cc3.number_input("Valor (R$)", min_value=0.01, step=10.0, format="%.2f")
        _desc_cx  = _cc4.text_input("Descrição")
        if st.form_submit_button("Registrar movimentação"):
            try:
                banco.registrar_caixa(str(_data_cx), _tipo_cx, _valor_cx, _desc_cx)
            except banco.CaixaInsuficienteError as exc:
                st.error(str(exc))
            else:
                st.success("Movimentação registrada.")
                st.rerun()

    _mov = banco.listar_caixa(20)
    if _mov:
        st.dataframe(pd.DataFrame(_mov)[["data", "tipo", "valor", "descricao"]], use_container_width=True, hide_index=True)

# ── Expander 3: Aportes ───────────────────────────────────────────────────────
with st.expander("💰 Aportes"):
    _ak1, _ak2, _ak3 = st.columns(3)
    _ak1.metric("Total aportado", f"R$ {total_ap:,.2f}")
    _ak2.metric("Total prêmios recebidos", f"R$ {total_pr:,.2f}")
    _ak3.metric("Soma total investida", f"R$ {total_ap + total_pr:,.2f}")

    with st.form("form_aporte", clear_on_submit=True):
        _fa1, _fa2 = st.columns(2)
        _data_ap  = _fa1.date_input("Data", value=hoje, key="data_aporte")
        _valor_ap = _fa2.number_input("Valor total (R$)", min_value=0.01, value=APORTE_MENSAL, step=100.0, format="%.2f")
        st.markdown("**Distribuição por ticker**")
        _fb1, _fb2, _fb3 = st.columns(3)
        _sug_ap = mercado.sugerir_alocacao_aporte(_valor_ap, patrimonio, saldo, ALOCACAO_ALVO)
        _bova_v = _fb1.number_input("BOVA11 — R$", min_value=0.0, value=_sug_ap.get("BOVA11", 0.0), step=10.0, format="%.2f")
        _ivv_v = _fb2.number_input("IVV — R$", min_value=0.0, value=_sug_ap.get("IVV", 0.0), step=10.0, format="%.2f")
        _hash_v = _fb3.number_input("HASH11 — R$", min_value=0.0, value=_sug_ap.get("HASH11", 0.0), step=10.0, format="%.2f")

        def _qtd_ap(ticker: str, valor: float) -> float:
            _dp = dados.get(ticker, {})
            _pp = _dp.get("preco_brl") or _dp.get("preco", 0.0)
            return valor / _pp if _pp else 0.0

        _ivv_d = dados.get("IVV", {})
        st.caption(
            f"BOVA11 ≈ {_qtd_ap('BOVA11', _bova_v):.2f} cotas | "
            f"IVV ≈ {_qtd_ap('IVV', _ivv_v):.4f} cotas (US$ {_ivv_d.get('preco', 0):.2f}) | "
            f"HASH11 ≈ {_qtd_ap('HASH11', _hash_v):.2f} cotas"
        )
        _investido_ap = _bova_v + _ivv_v + _hash_v
        _sobra_ap = _valor_ap - _investido_ap
        if _sobra_ap > 0.01:
            st.info(f"R$ {_sobra_ap:,.2f} permanecerão em caixa (aporte não totalmente investido).")
        _obs_ap = st.text_input("Observação", key="obs_aporte")
        if st.form_submit_button("Registrar aporte"):
            banco.inserir_aporte(
                data=str(_data_ap), valor_total=_valor_ap,
                bova11_qtd=_qtd_ap("BOVA11", _bova_v), bova11_valor=_bova_v,
                ivvb11_qtd=_qtd_ap("IVV", _ivv_v),     ivvb11_valor=_ivv_v,
                hash11_qtd=_qtd_ap("HASH11", _hash_v), hash11_valor=_hash_v,
                observacao=_obs_ap,
            )
            st.success(f"Aporte de R$ {_valor_ap:,.2f} registrado.")
            st.rerun()

    if aportes:
        _df_ap = pd.DataFrame(aportes).sort_values("data")
        _df_ap["acumulado"] = _df_ap["valor_total"].cumsum()
        _fig_ap = px.area(
            _df_ap, x="data", y="acumulado",
            labels={"acumulado": "Acumulado (R$)", "data": "Data"},
            color_discrete_sequence=["#2ecc71"],
        )
        _fig_ap.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=250, margin=dict(t=10,b=10))
        st.plotly_chart(_fig_ap, use_container_width=True)
        _ap_cols = ["data","valor_total","bova11_valor","bova11_qtd","ivvb11_valor","ivvb11_qtd","hash11_valor","hash11_qtd","observacao"]
        _df_ap_base = pd.DataFrame(aportes)
        st.dataframe(_df_ap_base[[c for c in _ap_cols if c in _df_ap_base.columns]], use_container_width=True, hide_index=True)

# ── Expander 4: Options history ───────────────────────────────────────────────
with st.expander("📜 Histórico de Opções"):
    if todas_op:
        _hist_rows = []
        for _op in todas_op:
            _pt   = _op.get("premio_total") or 0.0
            _ru   = _op.get("premio_recompra") or 0.0
            _qt   = _op.get("quantidade") or 0
            _curc = _ru * _qt
            _resc = _pt - _curc if _op["status"] != "ABERTA" else None
            _orig = _op.get("origem_id")
            _hist_rows.append({
                "ID":          _op["id"],
                "Roll de":     f"#{_orig}" if _orig else "—",
                "Abertura":    _op["data_abertura"],
                "Tipo":        _op["tipo"],
                "Ativo":       _op["ativo"],
                "Código":      (_op["codigo_opcao"] or "—").upper(),
                "Strike":      f"R$ {_op['strike']:.2f}",
                "Vencimento":  _op["vencimento"],
                "Qtd":         _qt,
                "Prêmio Rec.": f"R$ {_pt:,.2f}",
                "Recompra":    f"R$ {_curc:,.2f}" if _curc else "—",
                "Resultado":   (f"{'🟢' if _resc >= 0 else '🔴'} R$ {_resc:,.2f}" if _resc is not None else "aberta"),
                "Status":      _op["status"],
                "Fechamento":  _op.get("data_fechamento") or "—",
            })
        _df_hist = pd.DataFrame(_hist_rows)

        def _hcor(row: dict) -> str:
            if row["Status"] == "ABERTA":
                return "#0e1117"
            return "#0d2b1a" if "🟢" in row["Resultado"] else ("#2b0d0d" if "🔴" in row["Resultado"] else "#0e1117")

        _fill_h = [[_hcor(r) for r in _hist_rows]] * len(_df_hist.columns)
        _fig_h  = go.Figure(go.Table(
            header=dict(values=[f"<b>{c}</b>" for c in _df_hist.columns], fill_color="#1a1d27", font=dict(color="white", size=12), align="center", line_color="#333"),
            cells=dict(values=[_df_hist[c].tolist() for c in _df_hist.columns], fill_color=_fill_h, font=dict(color="white", size=11), align="center", line_color="#222", height=30),
        ))
        _fig_h.update_layout(margin=dict(t=0,b=0,l=0,r=0), paper_bgcolor="rgba(0,0,0,0)", height=60+len(_hist_rows)*34)
        st.plotly_chart(_fig_h, use_container_width=True)
    else:
        st.info("Nenhuma operação registrada ainda.")
