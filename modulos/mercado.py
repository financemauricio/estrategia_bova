"""Market data layer — fetches prices and moving averages via yfinance.

Results are cached for REFRESH_INTERVAL_SECONDS to avoid hammering the API on
every Streamlit re-run.
"""

from __future__ import annotations

import streamlit as st
import yfinance as yf
import pandas as pd

from config import TICKERS, MA_PERIODO, MA_VISUALIZACAO, HISTORICO_PERIODO, REFRESH_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# Cached fetcher
# ---------------------------------------------------------------------------

@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def buscar_dados_mercado() -> dict[str, dict]:
    """Fetch current price, daily variation and MA200 for all tickers.

    Returns
    -------
    dict[str, dict]
        Keys are asset names ('BOVA11', 'IVVB11', 'HASH11').
        Each value is a dict with:
        - preco       : float — latest closing price
        - variacao_pct: float — today's return (fraction, e.g. -0.015 = -1.5 %)
        - ma_decisao  : float | None — MA used for strategy (MA_PERIODO)
        - mas          : dict[int, float|None] — all MAs in MA_VISUALIZACAO
        - hist        : pd.DataFrame — full history with MA columns (used for charts)

    Examples
    --------
    >>> dados = buscar_dados_mercado()
    >>> dados["BOVA11"]["preco"]
    118.32
    """
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

        # Calculate all MAs for visualisation
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
            "variacao_pct": round(variacao_pct, 6),
            "ma_decisao": ma_decisao,
            "mas": mas,
            "hist": hist,
        }

    return resultado


def variacao_fmt(variacao_pct: float) -> str:
    """Format a fractional return as a coloured string for display.

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
    """Compute portfolio value and allocation from positions and market data.

    Parameters
    ----------
    posicoes : list[dict]
        Rows from ``banco.listar_posicoes()``.
    dados : dict[str, dict]
        Output from ``buscar_dados_mercado()``.

    Returns
    -------
    dict
        - total_etf   : float — market value of all ETF positions
        - por_ticker  : dict[str, float] — market value per ticker
        - alocacao    : dict[str, float] — fraction of total_etf per ticker
    """
    por_ticker: dict[str, float] = {}
    for pos in posicoes:
        ticker = pos["ticker"]
        preco = dados.get(ticker, {}).get("preco", 0.0)
        por_ticker[ticker] = round(pos["quantidade"] * preco, 2)

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
        Contribution amount (e.g. 5000.0).
    patrimonio : dict
        Output from ``calcular_patrimonio()``.
    saldo_caixa : float
        Current cash balance.
    alocacao_alvo : dict[str, float]
        Target fractions, e.g. {"BOVA11": 0.70, ...}.

    Returns
    -------
    dict[str, float]
        BRL amount to invest in each ticker.

    Examples
    --------
    >>> sugerir_alocacao_aporte(5000, patrimonio, 1000, ALOCACAO_ALVO)
    {"BOVA11": 3500.0, "IVVB11": 1000.0, "HASH11": 500.0}
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
