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


def corrigir_ultima_barra(hist: pd.DataFrame, spot_brapi: float | None) -> tuple[pd.DataFrame, str]:
    """Fix a corrupt last bar (zeroed Open/High/Low from yfinance). Pure function.

    - If the last bar is complete, return it unchanged (source 'yfinance').
    - If corrupt and a sane brapi spot exists (within 5% of previous close),
      stamp the last bar flat at the brapi price (source 'brapi').
    - Otherwise drop the corrupt bar and use the previous close (source 'yfinance*').
    """
    if hist.empty or "Close" not in hist.columns:
        return hist, "yfinance"
    ultima = hist.iloc[-1]
    completa = True
    for col in ("Open", "High", "Low"):
        if col in hist.columns and not ultima[col] > 0:
            completa = False
    if completa or len(hist) < 2:
        return hist, "yfinance"
    prev_close = float(hist["Close"].iloc[-2])
    if spot_brapi and spot_brapi > 0 and prev_close > 0:
        if abs(spot_brapi - prev_close) / prev_close <= 0.05:
            fix = hist.copy()
            for col in ("Open", "High", "Low", "Close"):
                if col in fix.columns:
                    fix.iloc[-1, fix.columns.get_loc(col)] = spot_brapi
            return fix, "brapi"
    return hist.iloc[:-1].copy(), "yfinance*"


def _spots_brapi() -> dict[str, float]:
    """Spot prices from brapi (free tier OK). Returns {} when unavailable."""
    try:
        from modulos import opcoes_b3
        if not opcoes_b3.token_configurado():
            return {}
        return opcoes_b3.buscar_cotacoes(["BOVA11", "HASH11"])
    except Exception:
        return {}
def _preservar_ultimo_ohlc_invalido(hist: pd.DataFrame) -> pd.DataFrame:
    """Keep the last row if only Open/High/Low are zero but Close is valid."""
    if hist.empty or "Close" not in hist.columns:
        return hist

    ultimo = hist.index == hist.index[-1]
    valido = hist["Close"] > 0

    for col_ohlc in ["Open", "High", "Low"]:
        if col_ohlc in hist.columns:
            valido &= (hist[col_ohlc] > 0) | (ultimo & (hist["Close"] > 0))

    return hist[valido]


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
    spots_brapi = _spots_brapi()
    resultado: dict[str, dict] = {}

    for nome, ticker_sa in TICKERS.items():
        try:
            hist = yf.Ticker(ticker_sa).history(period=HISTORICO_PERIODO)
        except Exception:
            continue

        if hist.empty or len(hist) < 2:
            continue

        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        # Drop rows with any zero OHLC value (partial/corrupt intraday bars).
        # Preserve the final row if it contains only Close and valid Close price.
        hist = _preservar_ultimo_ohlc_invalido(hist)
        # Fix corrupt last bar (zeroed O/H/L) with brapi spot when sane.
        hist, fonte_preco = corrigir_ultima_barra(hist, spots_brapi.get(nome))
        # Drop rows with anomalous daily move > 50 %
        var_diaria = hist["Close"].pct_change().abs()
        hist = hist[(var_diaria < 0.50) | var_diaria.isna()].copy()

        if len(hist) < 2:
            continue

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
            "fonte_preco": fonte_preco,
            "moeda": "USD" if em_usd else "BRL",
            "usdbrl": usdbrl,
            "variacao_pct": round(variacao_pct, 6),
            "ma_decisao": ma_decisao,
            "mas": mas,
            "hist": hist,
        }

    return resultado


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def buscar_dados_ativo_opcao(ticker_b3: str) -> dict:
    """Fetch price and recent history for any B3 stock used as option underlying.

    Tries ``{ticker_b3}.SA`` first; falls back to appending common suffixes
    (3, 4, 11) if the ticker is a bare 4-letter prefix.

    Parameters
    ----------
    ticker_b3 : str
        Ticker as stored in the options table, e.g. 'PETR4', 'BOVA11'.

    Returns
    -------
    dict
        - preco : float | None
        - hist  : pd.DataFrame | None
    """
    candidatos = [f"{ticker_b3}.SA"]
    if not any(ticker_b3.endswith(s) for s in ("3", "4", "11")):
        candidatos += [f"{ticker_b3}3.SA", f"{ticker_b3}4.SA", f"{ticker_b3}11.SA"]

    for sa in candidatos:
        try:
            hist = yf.Ticker(sa).history(period="120d")
        except Exception:
            continue
        if hist.empty or len(hist) < 21:
            continue
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        hist = _preservar_ultimo_ohlc_invalido(hist)
        if len(hist) < 21:
            continue
        return {"preco": float(hist["Close"].iloc[-1]), "hist": hist}

    return {"preco": None, "hist": None}


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
