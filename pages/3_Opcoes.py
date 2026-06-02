"""Opções — register, monitor and close options positions."""

from __future__ import annotations

import datetime

import pandas as pd
import streamlit as st

from modulos import banco

st.title("📋 Opções")

# ---------------------------------------------------------------------------
# Single-fetch: all options + cash balance (2 DB round-trips total)
# ---------------------------------------------------------------------------
todas = banco.listar_opcoes()
saldo = banco.saldo_caixa()

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
        rows.append(
            {
                "ID": op["id"],
                "Tipo": op["tipo"],
                "Código": op["codigo_opcao"] or "—",
                "Strike": f"R$ {op['strike']:.2f}",
                "Vencimento": str(venc),
                "Dias": f"{dias} {alerta}",
                "Qtd": op["quantidade"],
                "Prêmio Unit.": f"R$ {op['premio_unitario']:.4f}",
                "Prêmio Total": f"R$ {op['premio_total']:.2f}",
                "Obs.": op["observacao"] or "",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("Nenhuma posição aberta.")

st.divider()

# ---------------------------------------------------------------------------
# Register new option sale
# ---------------------------------------------------------------------------
st.subheader("Registrar Venda de Opção")

with st.form("form_opcao", clear_on_submit=True):
    r1c1, r1c2, r1c3 = st.columns(3)
    data_ab = r1c1.date_input("Data de abertura", value=datetime.date.today())
    tipo_op = r1c2.selectbox("Tipo", ["PUT", "CALL"])
    ativo_op = r1c3.selectbox("Ativo subjacente", ["BOVA11", "HASH11"])

    r2c1, r2c2, r2c3 = st.columns(3)
    codigo_op = r2c1.text_input("Código da opção", placeholder="ex: BOVAJ24")
    strike_op = r2c2.number_input("Strike (R$)", min_value=0.01, step=0.50, format="%.2f")
    venc_op = r2c3.date_input(
        "Vencimento",
        value=datetime.date.today() + datetime.timedelta(days=30),
    )

    r3c1, r3c2, r3c3 = st.columns(3)
    qtd_op = r3c1.number_input("Quantidade (contratos)", min_value=1, step=1)
    premio_op = r3c2.number_input("Prêmio unitário (R$)", min_value=0.0001, step=0.01, format="%.4f")
    obs_op = r3c3.text_input("Observação")

    total_preview = qtd_op * premio_op
    st.caption(f"Prêmio total a receber: **R$ {total_preview:,.2f}**")

    if st.form_submit_button("Registrar venda"):
        banco.inserir_opcao(
            data_abertura=str(data_ab),
            tipo=tipo_op,
            ativo=ativo_op,
            codigo_opcao=codigo_op,
            strike=strike_op,
            vencimento=str(venc_op),
            quantidade=int(qtd_op),
            premio_unitario=premio_op,
            observacao=obs_op,
        )
        st.success(f"Venda de {tipo_op} registrada. Prêmio total: R$ {total_preview:,.2f}")
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Close / update open position
# ---------------------------------------------------------------------------
st.subheader("Encerrar Posição")

if abertas:
    id_opcoes = {f"ID {op['id']} — {op['tipo']} {op['codigo_opcao'] or ''} Strike {op['strike']} Venc. {op['vencimento']}": op["id"] for op in abertas}

    with st.form("form_fechar", clear_on_submit=True):
        opcao_sel = st.selectbox("Selecionar posição", list(id_opcoes.keys()))
        fc1, fc2 = st.columns(2)
        status_novo = fc1.selectbox("Novo status", ["EXERCIDA", "EXPIRADA", "ROLADA"])
        data_fech = fc2.date_input("Data de fechamento", value=datetime.date.today())

        if st.form_submit_button("Encerrar"):
            banco.fechar_opcao(id_opcoes[opcao_sel], status_novo, str(data_fech))
            st.success("Posição encerrada.")
            st.rerun()
else:
    st.caption("Nenhuma posição aberta para encerrar.")

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
