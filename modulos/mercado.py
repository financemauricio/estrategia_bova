"""Market data layer — fetches prices and moving averages via yfinance.

Results are cached for REFRESH_INTERVAL_SECONDS to avoid hammering the API on
every Streamlit re-run.

IVV is USD-denominated. All BRL-equivalent values are computed using the
live USDBRL=X rate so that portfolio allocation math stays in BRL.
"""

from __future__ import annotations

import streamlit as st
import yfinance as yf
import pandas as pd

from config import (
    TICKERS,
    TICKERS_USD,
    TICKER_USDBRL,
    MA_PERIODO,
    MA_VISUALIZACAO,
    HISTORICO_PERIODO,
    REFRESH_INTERVAL_SECONDS,
)


# ---------------------------------------------------------------------------
# USD/BRL exchange rate
# ---------------------------------------------------------------------------

@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def buscar_usdbrl() -> float:
    """Return the latest USD/BRL exchange rate.

    Returns
    -------
    float
        e.g. 5.72 — meaning 1 USD = R$ 5.72. Falls back to 5.70 on error.
    """
    try:
        hist = yf.Ticker(TICKER_USDBRL).history(period="5d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
    except Exception:
        pass
    return 5.70  # safe fallback


# ---------------------------------------------------------------------------
# Market data fetcher
# ---------------------------------------------------------------------------

@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def buscar_dados_mercado() -> dict[str, dict]:
    """Fetch current price, daily variation and moving averages for all tickers.

    For USD-denominated tickers (IVV), ``preco`` is in USD and
    ``preco_brl`` holds the BRL equivalent using the live USDBRL rate.

    Returns
    -------
    dict[str, dict]
        Keys are asset names ('BOVA11', 'IVV', 'HASH11').
        Each value is a dict with:
        - preco       : float — latest closing price in native currency
        - preco_brl   : float — price in BRL (same as preco for BRL assets)
        - moeda       : str   — 'BRL' or 'USD'
        - variacao_pct: float — today's return (fraction)
        - ma_decisao  : float | None — MA used for strategy decisions
        - mas         : dict[int, float|None] — all MAs in MA_VISUALIZACAO
        - hist        : pd.DataFrame — full history with MA columns

    Examples
    --------
    >>> dados = buscar_dados_mercado()
    >>> dados["BOVA11"]["preco"]
    118.32
    >>> dados["IVV"]["preco"]
    582.10
    >>> dados["IVV"]["preco_brl"]
    3319.57
    """
    usdbrl = buscar_usdbrl()
    resultado: dict[str, dict] = {}

    for nome, ticker_sa in TICKERS.items():
        try:
            hist = yf.Ticker(ticker_sa).history(period=HISTORICO_PERIODO)
        except Exception:
            continue

        if hist.empty or len(hist) < 2:
            continue

        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        preco_atual: float = float(hist["Close"].iloc[-1])
        preco_ontem: float = float(hist["Close"].iloc[-2])
        variacao_pct: float = (preco_atual - preco_ontem) / preco_ontem

        em_usd = nome in TICKERS_USD
        preco_brl = round(preco_atual * usdbrl, 2) if em_usd else round(preco_atual, 2)

        # MAs are always computed in the native currency of the asset
        mas: dict[int, float | None] = {}
        for janela in MA_VISUALIZACAO:
            col = f"MA{janela}"
            hist[col] = hist["Close"].rolling(janela).mean()
            mas[janela] = (
                round(float(hist[col].iloc[-1]), 2) if len(hist) >= janela else None
            )

        ma_decisao = mas.get(MA_PERIODO)

        resultado[nome] = {
            "preco": round(preco_atual, 2),
            "preco_brl": preco_brl,
            "moeda": "USD" if em_usd else "BRL",
            "usdbrl": usdbrl,
            "variacao_pct": round(variacao_pct, 6),
            "ma_decisao": ma_decisao,
            "mas": mas,
            "hist": hist,
        }

    return resultado


def variacao_fmt(variacao_pct: float) -> str:
    """Format a fractional return for display.

    Parameters
    ----------
    variacao_pct : float
        e.g. -0.015

    Returns
    -------
    str
        e.g. '-1.50 %'
    """
    sinal = "+" if variacao_pct >= 0 else ""
    return f"{sinal}{variacao_pct * 100:.2f} %"


def calcular_patrimonio(posicoes: list[dict], dados: dict[str, dict]) -> dict:
    """Compute portfolio value and allocation in BRL.

    USD-denominated assets use ``preco_brl`` for the calculation so that
    allocation percentages are consistent across all assets.

    Parameters
    ----------
    posicoes : list[dict]
        Rows from ``banco.listar_posicoes()``.
    dados : dict[str, dict]
        Output from ``buscar_dados_mercado()``.

    Returns
    -------
    dict
        - total_etf   : float — total market value in BRL
        - por_ticker  : dict[str, float] — BRL value per ticker
        - alocacao    : dict[str, float] — fraction per ticker
    """
    por_ticker: dict[str, float] = {}
    for pos in posicoes:
        ticker = pos["ticker"]
        # Always use BRL-equivalent price for allocation math
        preco_brl = dados.get(ticker, {}).get("preco_brl", 0.0)
        por_ticker[ticker] = round(pos["quantidade"] * preco_brl, 2)

    total_etf = sum(por_ticker.values())
    alocacao: dict[str, float] = (
        {t: v / total_etf for t, v in por_ticker.items()} if total_etf > 0 else {}
    )

    return {"total_etf": total_etf, "por_ticker": por_ticker, "alocacao": alocacao}


def sugerir_alocacao_aporte(
    aporte: float,
    patrimonio: dict,
    saldo_caixa: float,
    alocacao_alvo: dict[str, float],
) -> dict[str, float]:
    """Compute how to split the monthly contribution to rebalance toward target.

    Parameters
    ----------
    aporte : float
        Contribution amount in BRL (e.g. 5000.0).
    patrimonio : dict
        Output from ``calcular_patrimonio()``.
    saldo_caixa : float
        Current cash balance in BRL.
    alocacao_alvo : dict[str, float]
        Target fractions, e.g. {"BOVA11": 0.70, ...}.

    Returns
    -------
    dict[str, float]
        BRL amount to invest in each ticker.

    Examples
    --------
    >>> sugerir_alocacao_aporte(5000, patrimonio, 1000, ALOCACAO_ALVO)
    {"BOVA11": 3500.0, "IVV": 1000.0, "HASH11": 500.0}
    """
    total_atual = patrimonio["total_etf"] + saldo_caixa
    total_futuro = total_atual + aporte

    sugestao: dict[str, float] = {}
    sobra = aporte

    for ticker, alvo_pct in alocacao_alvo.items():
        valor_alvo = total_futuro * alvo_pct
        valor_atual = patrimonio["por_ticker"].get(ticker, 0.0)
        delta = max(0.0, valor_alvo - valor_atual)
        sugestao[ticker] = round(min(delta, sobra), 2)
        sobra -= sugestao[ticker]
        if sobra < 0:
            sobra = 0.0

    return sugestao
