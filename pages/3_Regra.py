"""A Regra — the wheel plan in plain language, plus realistic expectations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import (
    CALL_STRIKE_OTM_PCT,
    DELTA_PUT_ALVO,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    PREMIO_MIN_PCT,
    TICKERS,
)

st.title("📐 A Regra")
st.caption("O plano em 4 passos. Menos decisões, menos impulso.")

st.subheader("1. Viés — o termômetro é a média")
st.markdown(
    f"""
- Preço **abaixo** da MA{MA_PERIODO} → viés **PUT** (vender PUT, ser pago para comprar mais barato).
- Preço **acima** da MA{MA_PERIODO} → viés **CALL** (vender CALL coberta, ser pago para vender mais caro).
- A média não prevê o futuro: ela só define **de que lado você aceita ser exercido**.
"""
)

st.subheader("2. Strike — delta fixo, não % chutado")
st.markdown(
    f"""
- **PUT:** strike com delta ≈ **{DELTA_PUT_ALVO:.2f}** (≈25 % de chance de exercício).
- **CALL:** strike **{CALL_STRIKE_OTM_PCT*100:.0f} % acima** do preço.
- Em mês calmo o strike fica mais perto; em mês nervoso, mais longe. O risco fica constante.
"""
)

st.subheader("3. Prêmio mínimo — sem prêmio, sem operação")
st.markdown(
    f"""
- Só vale vender se o prêmio **real** chegar a **{PREMIO_MIN_PCT*100:.1f} % do preço** do ativo (por ciclo de ~30 dias).
- Se o prêmio for magro, o risco não é pago. **Ficar de fora também é posição.**
- O app mostra um **prêmio de referência** (Black-Scholes com volatilidade histórica). Ele serve para comparar séries, **não** para prever o preço do mercado.
- Use **Análise do Ativo → Confira o prêmio real**: digite o bid do Home Broker e o app calcula a volatilidade implícita, a probabilidade e o retorno anualizado.

**Exemplo real (VALE3, out/2026):** PUT strike 64 com spot 63,90 foi vendida a R$ 2,00.
A conta teórica com volatilidade histórica (19,3 %) daria R$ 1,26 — 60 % abaixo.
A volatilidade embutida no preço de mercado era **28 %**. É por isso que o prêmio do app
nunca deve ser tratado como o preço da corretora.
"""
)

st.subheader("4. Prioridade — só o movimento forte muda a ordem")
st.markdown(
    f"""
- Queda de **{abs(LIMIAR_QUEDA_PUT)*100:.1f} %** ou mais no dia → prioridade na PUT.
- Alta de **{LIMIAR_ALTA_CALL*100:.1f} %** ou mais → prioridade na CALL.
- Fora disso, siga o viés normalmente, sem pressa.
"""
)

st.divider()
st.subheader("A cotação — o input da regra")
st.markdown(
    """
- O preço vem de **três fontes**: Yahoo (horário do último negócio), brapi e Status Invest.
- O app compara as três a cada minuto. Se concordam (até 0,8 %), usa o consenso; se divergem, **avisa** e manda confirmar no Home Broker.
- Depois do fechamento aparece **"fechamento de dd/mm"** — não um horário que finge ser tempo real.
- Em **Sinais → 🔎 De onde vem cada preço** você vê o valor bruto de cada fonte.
"""
)

st.divider()
st.subheader("Expectativa realista")
st.caption(
    "Backtest de 56 ciclos mensais de PUT delta -0,25 em BOVA11 (~4,5 anos, prêmio teórico, "
    "sem custos). Serve para calibrar expectativa, não como promessa."
)

st.dataframe(
    pd.DataFrame([
        {"Estratégia": "Vender PUT (delta -0,25)", "Retorno médio/mês": "+0,34 %", "Anualizado": "~4,0 %", "Pior mês": "-4,4 %"},
        {"Estratégia": "Buy-and-hold BOVA11", "Retorno médio/mês": "+1,16 %", "Anualizado": "~13,1 %", "Pior mês": "-8,1 %"},
    ]),
    width="stretch",
    hide_index=True,
)

st.markdown(
    """
**Como ler isso:**
- A venda de PUT **não bate o índice em mercado de alta** — você troca parte da valorização pelo prêmio.
- O ganho real vem de **volatilidade menor** e de **comprar mais barato nos exercícios** (~30 % dos meses).
- O caixa reservado para a PUT rende Selic (~0,85 %/mês); somando ao prêmio, o resultado empata com o índice, com menos susto.
- Sem corretagem e IR de 15 % na conta acima. Ajuste para baixo antes de decidir.
"""
)

st.divider()
st.subheader("Ativos monitorados")
st.write(
    " · ".join(TICKERS.keys())
    + " — altere a lista em `config.py` (constante `TICKERS`)."
)

st.warning(
    "Este app é uma ferramenta de leitura de mercado, não recomendação de investimento. "
    "Opções têm risco de perda relevante. Confirme sempre preço, liquidez e vencimento no Home Broker."
)
