"""A Regra — the wheel plan in plain language, plus realistic expectations."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import (
    CALL_STRIKE_OTM_ESTICADO_PCT,
    DELTA_CALL_RENDA,
    DELTA_PUT_RENDA,
    DIST_MA_ESTICADO_PCT,
    ESTICADO_MIN_CRITERIOS,
    GANHO_5D_ESTICADO_PCT,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    PREMIO_MIN_ESTICADO_PCT,
    PREMIO_MIN_RENDA_PCT,
    RSI_ESTICADO,
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

st.subheader("2. Strike — dois modos, sem decisão no impulso")
st.markdown(
    f"""
- **Modo renda (padrão):** PUT delta **{DELTA_PUT_RENDA:.2f}** · CALL delta **{DELTA_CALL_RENDA:+.2f}**.
  Longe do dinheiro, prêmio menor, pouca chance de exercício por ciclo.
- **Modo esticado (exceção):** quando o ativo sobe muito, a CALL vai para
  **{CALL_STRIKE_OTM_ESTICADO_PCT*100:.0f} % acima** do preço. Prêmio maior; se exercido,
  você vende num preço esticado.
- Gatilho do modo esticado: **{ESTICADO_MIN_CRITERIOS} de 3** critérios —
  distância ≥ **{DIST_MA_ESTICADO_PCT*100:.0f} %** acima da MA{MA_PERIODO},
  RSI ≥ **{RSI_ESTICADO:.0f}**, ou ganho de 5 dias ≥ **{GANHO_5D_ESTICADO_PCT*100:.0f} %**.
  Sem gatilho, fica no modo renda.
- Com esses padrões, o gatilho ligou em **~8-17 % dos dias** nos últimos ~400 pregões de cada ativo —
  é exceção, não rotina.
- A CALL é sempre **coberta**: você precisa ter a ação. O app não rastreia posição.
"""
)

st.subheader("3. Prêmio mínimo — sem prêmio, sem operação")
st.markdown(
    f"""
- **Modo renda:** prêmio **real** de pelo menos **{PREMIO_MIN_RENDA_PCT*100:.1f} % do preço** por ciclo.
- **Modo esticado:** pelo menos **{PREMIO_MIN_ESTICADO_PCT*100:.1f} % do preço** por ciclo.
- Se o prêmio for magro, o risco não é pago. **Ficar de fora também é posição.**
- O app mostra um **prêmio de referência** (Black-Scholes com volatilidade histórica). Ele serve para comparar séries, **não** para prever o preço do mercado.
- Use **Análise do Ativo → Confira o prêmio real**: digite o bid do Home Broker e o app calcula a volatilidade implícita, a probabilidade e o retorno anualizado.

**Exemplo real (VALE3, out/2026):** PUT strike 64 com spot 63,90 foi vendida a R$ 2,00.
A conta teórica com volatilidade histórica (19,3 %) daria R$ 1,26 — 60 % abaixo.
A volatilidade embutida no preço de mercado era **28 %**. É por isso que o prêmio do app
nunca deve ser tratado como o preço da corretora.

**Exemplo real (BOVA11, fechamento de 21/10/2026):** o **mesmo strike K210** valia:
- **R$ 0,21** no semanal de **23/10** (1 dia);
- **R$ 7,19** no mensal de **19/11** (28 dias).

O prêmio teórico de ~R$ 7,00 é do vencimento de **~30 dias**. Se o book mostra R$ 0,21,
ele está no semanal — é outro papel, com outro risco. O app agora mostra o **prêmio real
de fechamento e o vencimento** em cada sugestão, e a cadeia completa em Análise do Ativo.
"""
)

st.subheader("4. Prioridade — só o movimento forte muda a ordem")
st.markdown(
    f"""
- Queda de **{abs(LIMIAR_QUEDA_PUT)*100:.1f} %** ou mais no dia → prioridade na PUT.
- Alta de **{LIMIAR_ALTA_CALL*100:.1f} %** ou mais → prioridade na CALL.
- **Modo esticado** (os {ESTICADO_MIN_CRITERIOS} de 3 critérios acima) → vender CALL +3 % OTM.
- Fora disso, siga o viés normalmente, sem pressa.
"""
)

st.divider()
st.subheader("A cotação — o input da regra")
st.markdown(
    """
- O preço vem de **três fontes**: Yahoo (horário do último negócio), brapi e Status Invest.
- O app compara as três a cada 2 min. Se concordam (até 0,8 %), usa o consenso; se divergem, **avisa** e manda confirmar no Home Broker.
- Fontes gratuitas atrasam até **15 min**. No começo do pregão elas ainda mostram o fechamento anterior — e o app escreve **"fechamento de dd/mm"** em vez de fingir que é tempo real.
- Em **Sinais → 🔎 De onde vem cada preço** você vê o valor bruto de cada fonte e a data da última barra.
"""
)

st.divider()
st.subheader("Expectativa realista")
st.caption(
    "Backtest de 56 ciclos mensais de PUT delta -0,25 em BOVA11 (regra antiga; ~4,5 anos, "
    "prêmio teórico, sem custos). A regra nova usa -0,15 no modo renda: menos prêmio e "
    "menos exercício. Serve para calibrar expectativa, não como promessa."
)

st.dataframe(
    pd.DataFrame([
        {"Estratégia": "Vender PUT (delta -0,25, referência antiga)", "Retorno médio/mês": "+0,34 %", "Anualizado": "~4,0 %", "Pior mês": "-4,4 %"},
        {"Estratégia": "Buy-and-hold BOVA11", "Retorno médio/mês": "+1,16 %", "Anualizado": "~13,1 %", "Pior mês": "-8,1 %"},
    ]),
    width="stretch",
    hide_index=True,
)

st.markdown(
    """
**Como ler isso:**
- A venda de PUT **não bate o índice em mercado de alta** — você troca parte da valorização pelo prêmio.
- O ganho real vem de **volatilidade menor** e de **comprar mais barato nos exercícios**.
  No backtest antigo (-0,25) isso acontecia em ~30 % dos meses; no modo renda (-0,15),
  a frequência cai para ~15 % por ciclo — e o prêmio também.
- O caixa reservado para a PUT rende Selic (~0,85 %/mês); somando ao prêmio, o resultado empata com o índice, com menos susto.
- Prêmio pequeno (0,4 %/ciclo) exige atenção a corretagem e IR. Sem custos na conta acima.
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
