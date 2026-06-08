"""Shared UI utility functions — reused across the Carteira and Dashboard pages.

Extracts duplicated Black-Scholes probability logic and badge/formatting
helpers so they live in a single place.
"""

from __future__ import annotations

import math


def prob_exercicio(
    tipo: str,
    ativo: str,
    strike: float,
    dias: int,
    dados_mkt: dict,
    selic: float,
) -> float | None:
    """Return probability of exercise [0, 1] using Black-Scholes N(±d2).

    Works for any B3 stock — portfolio assets use the cached market data
    dict; others are fetched on demand via ``mercado.buscar_dados_ativo_opcao``.

    Parameters
    ----------
    tipo : str
        'PUT' or 'CALL'.
    ativo : str
        Underlying asset ticker, e.g. 'BOVA11', 'PETR4'.
    strike : float
        Option strike price.
    dias : int
        Calendar days to expiry.
    dados_mkt : dict
        Output of ``mercado.buscar_dados_mercado()``.
    selic : float
        Annual Selic rate as decimal (e.g. 0.1325).

    Returns
    -------
    float or None
        Probability in [0, 1], or None if data is unavailable.
    """
    from modulos import bs, mercado  # lazy import avoids circular deps

    d = dados_mkt.get(ativo) or mercado.buscar_dados_ativo_opcao(ativo)
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
    d1_num = math.log(preco / strike) + (selic + 0.5 * sigma ** 2) * T
    d2     = (d1_num / (sigma * math.sqrt(T))) - sigma * math.sqrt(T)
    norm_d2 = (1.0 + math.erf(d2 / math.sqrt(2.0))) / 2.0
    return (1 - norm_d2) if tipo == "PUT" else norm_d2


def prob_badge(prob: float | None) -> str:
    """Format probability as a coloured emoji badge.

    Parameters
    ----------
    prob : float or None
        Probability in [0, 1].

    Returns
    -------
    str
        e.g. '🟢 12.3%' or '🔴 67.1%'.
    """
    if prob is None:
        return "—"
    pct   = prob * 100
    emoji = "🔴" if pct >= 50 else ("🟡" if pct >= 25 else "🟢")
    return f"{emoji} {pct:.1f}%"


def preco_ativo(ativo: str, dados_mkt: dict) -> float | None:
    """Return the current spot price for an underlying asset.

    Parameters
    ----------
    ativo : str
        Underlying asset ticker (e.g. 'BOVA11', 'PETR4').
    dados_mkt : dict
        Output of ``mercado.buscar_dados_mercado()``.

    Returns
    -------
    float or None
        Current price in BRL, or None if unavailable.
    """
    from modulos import mercado

    d     = dados_mkt.get(ativo) or mercado.buscar_dados_ativo_opcao(ativo)
    preco = d.get("preco")
    return preco if preco and preco > 0 else None


def validar_saida_caixa(saldo: float, valor: float) -> str | None:
    """Return an error message if ``valor`` exceeds ``saldo``, else None."""
    if valor <= 0:
        return None
    if saldo < valor:
        falta = valor - saldo
        return (
            f"Caixa insuficiente: necessário R$ {valor:,.2f}, "
            f"disponível R$ {saldo:,.2f} (faltam R$ {falta:,.2f}). "
            "Registre um aporte ou depósito em **Caixa e Movimentações** antes de continuar."
        )
    return None


def distancia_strike(tipo: str, preco_spot: float, strike: float) -> str:
    """Format % distance from spot price to strike with OTM/ITM label.

    For PUT : positive = OTM (spot above strike), negative = ITM.
    For CALL: positive = OTM (spot below strike), negative = ITM.

    Parameters
    ----------
    tipo : str
        'PUT' or 'CALL'.
    preco_spot : float
        Current underlying price.
    strike : float
        Option strike price.

    Returns
    -------
    str
        e.g. '+4.2% OTM' or '-1.8% ITM'.
    """
    pct = (preco_spot - strike) / strike * 100
    if tipo == "PUT":
        otm   = pct >= 0
        sinal = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    else:
        otm   = pct <= 0
        sinal = f"+{abs(pct):.1f}%" if pct <= 0 else f"-{abs(pct):.1f}%"
    return f"{sinal} {'OTM' if otm else 'ITM'}"
