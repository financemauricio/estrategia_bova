"""Strategy rules engine — implements the 5-step weekly decision process.

All logic mirrors the operational script exactly:

  Step 1 → Is BOVA11 above or below MA200?  (determines bias)
  Step 2 → Is there enough cash / ETF to honour exercise?
  Step 3 → Was there a relevant daily movement? (> 1.5 % drop or > 2 % rise)
  Step 4 → Is the premium attractive?  (user confirms manually)
  Step 5 → Execute: PUT ATM if buyer bias, CALL 3 % OTM if seller bias.
"""

from __future__ import annotations

from config import (
    CAIXA_MIN_PCT,
    CALL_STRIKE_OTM_PCT,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
)


def avaliar_estrategia(
    dados_mercado: dict,
    posicoes: list[dict],
    saldo_caixa: float,
    total_etf: float,
    opcoes_abertas: list[dict] | None = None,
) -> dict:
    """Run the 5-step strategy and return a structured recommendation.

    Parameters
    ----------
    dados_mercado : dict
        Output from ``mercado.buscar_dados_mercado()``.
    posicoes : list[dict]
        Output from ``banco.listar_posicoes()``.
    saldo_caixa : float
        Current cash balance (BRL).
    total_etf : float
        Total market value of all ETF positions (BRL).
    opcoes_abertas : list[dict] or None
        Open option positions from ``banco.listar_opcoes('ABERTA')``.
        Used to compute committed cash in step 2.

    Returns
    -------
    dict
        - passos         : dict — per-step result
        - recomendacao   : str  — 'PUT_ATM' | 'CALL_OTM' | 'AGUARDAR'
        - prioridade     : bool — True when a strong daily move was detected
        - vies           : str  — 'PUT' | 'CALL' | 'INDEFINIDO'
        - strike_sugerido: float | None — suggested CALL strike
        - mensagem       : str  — human-readable summary

    Examples
    --------
    >>> resultado = avaliar_estrategia(dados, posicoes, 3000, 60000)
    >>> resultado["recomendacao"]
    'PUT_ATM'
    """
    bova = dados_mercado.get("BOVA11", {})
    preco: float | None = bova.get("preco")
    ma200: float | None = bova.get("ma_decisao")   # uses MA_PERIODO from config
    variacao: float = bova.get("variacao_pct", 0.0)

    patrimonio_total = total_etf + saldo_caixa

    # ------------------------------------------------------------------
    # Step 1 — price vs decision MA (MA_PERIODO)
    # ------------------------------------------------------------------
    if preco and ma200:
        acima_ma200 = preco > ma200
        distancia_pct = (preco - ma200) / ma200
        passo1 = {
            "ok": True,
            "resultado": "ACIMA" if acima_ma200 else "ABAIXO",
            "vies": "CALL" if acima_ma200 else "PUT",
            "preco": preco,
            "ma_val": ma200,
            "distancia_pct": distancia_pct,
        }
    else:
        passo1 = {
            "ok": False,
            "resultado": "Dados insuficientes",
            "vies": "INDEFINIDO",
            "preco": preco,
            "ma_val": ma200,
            "distancia_pct": None,
        }

    vies: str = passo1["vies"]

    # ------------------------------------------------------------------
    # Step 2 — Resources available
    # ------------------------------------------------------------------
    caixa_pct = saldo_caixa / patrimonio_total if patrimonio_total > 0 else 0.0
    pos_map = {p["ticker"]: p for p in posicoes}

    # Cash committed to open PUTs (strike × qty for each open PUT)
    puts_abertas = [o for o in (opcoes_abertas or []) if o.get("tipo") == "PUT"]
    comprometido = sum(o["strike"] * o["quantidade"] for o in puts_abertas)
    saldo_disponivel = saldo_caixa - comprometido

    if vies == "PUT":
        recursos_ok = saldo_disponivel > 0 and caixa_pct >= CAIXA_MIN_PCT
        if comprometido > 0 and saldo_disponivel <= 0:
            detalhe_recursos = (
                f"Caixa 100% comprometido com PUTs abertas "
                f"(reserva R$ {comprometido:,.2f}). Não venda novas PUTs."
            )
        elif comprometido > 0:
            detalhe_recursos = (
                f"Caixa disponível: R$ {saldo_disponivel:,.2f} "
                f"(R$ {comprometido:,.2f} reservado para PUTs abertas)"
            )
        else:
            detalhe_recursos = (
                f"Caixa {caixa_pct*100:.1f} % do patrimônio "
                f"({'OK' if recursos_ok else f'mínimo {CAIXA_MIN_PCT*100:.0f} %'})"
            )
    else:
        bova_qtd = pos_map.get("BOVA11", {}).get("quantidade", 0)
        recursos_ok = bova_qtd > 0
        detalhe_recursos = (
            f"BOVA11: {bova_qtd:.0f} cotas disponíveis para cobertura"
        )

    passo2 = {
        "ok": recursos_ok,
        "caixa_pct": caixa_pct,
        "comprometido": comprometido,
        "saldo_disponivel": saldo_disponivel,
        "detalhe": detalhe_recursos,
    }

    # ------------------------------------------------------------------
    # Step 3 — Relevant daily movement in the direction of the bias
    # ------------------------------------------------------------------
    queda_forte = variacao <= LIMIAR_QUEDA_PUT
    alta_forte = variacao >= LIMIAR_ALTA_CALL

    # Signal must match the bias direction
    if vies == "PUT":
        movimento_relevante = queda_forte
    elif vies == "CALL":
        movimento_relevante = alta_forte
    else:
        movimento_relevante = False

    passo3 = {
        "ok": movimento_relevante,
        "variacao": variacao,
        "queda_forte": queda_forte,
        "alta_forte": alta_forte,
        "detalhe": (
            f"Variação do dia: {variacao*100:+.2f} %"
            + (" — QUEDA FORTE ⚡" if queda_forte and vies == "PUT" else "")
            + (" — ALTA FORTE ⚡" if alta_forte and vies == "CALL" else "")
        ),
    }

    # ------------------------------------------------------------------
    # Step 4 — Premium attractiveness (user confirms manually in the UI)
    # ------------------------------------------------------------------
    passo4 = {"ok": None, "manual": True, "detalhe": "Confirme o prêmio no Home Broker"}

    # ------------------------------------------------------------------
    # Step 5 — Final recommendation
    # ------------------------------------------------------------------
    strike_sugerido: float | None = None

    if not passo1["ok"]:
        recomendacao = "AGUARDAR"
        mensagem = "Dados de mercado insuficientes. Tente novamente mais tarde."
    elif not recursos_ok:
        recomendacao = "AGUARDAR"
        mensagem = (
            "Caixa insuficiente para exercício de PUT."
            if vies == "PUT"
            else "Sem cotas de BOVA11 para cobertura de CALL."
        )
    elif vies == "PUT":
        recomendacao = "PUT_ATM"
        mensagem = (
            "Vender PUT ATM com vencimento mensal. "
            + ("PRIORIDADE MÁXIMA — queda forte detectada." if queda_forte else "")
        )
    else:
        recomendacao = "CALL_OTM"
        strike_sugerido = round(preco * (1 + CALL_STRIKE_OTM_PCT), 2) if preco else None
        mensagem = (
            f"Vender CALL 3 % OTM — strike sugerido R$ {strike_sugerido}. "
            + ("PRIORIDADE MÁXIMA — alta forte detectada." if alta_forte else "")
        )

    return {
        "passos": {
            "passo1": passo1,
            "passo2": passo2,
            "passo3": passo3,
            "passo4": passo4,
        },
        "recomendacao": recomendacao,
        "prioridade": movimento_relevante and recursos_ok and passo1["ok"],
        "vies": vies,
        "strike_sugerido": strike_sugerido,
        "mensagem": mensagem,
    }
