"""Market data layer — prices, moving averages and volatility via yfinance.

Nothing here touches a database: the app is read-only market analysis.

Last-bar corruption: yfinance sometimes returns the current session with
Open/High/Low = 0 while Close is valid. That produces a broken candle and a
wrong daily variation. When brapi is configured we stamp the bar with its
spot price; otherwise we drop the bar and use the previous close.
"""

from __future__ import annotations

import streamlit as st
import yfinance as yf
import pandas as pd

from config import (
    TICKERS,
    MA_PERIODO,
    MA_VISUALIZACAO,
    HISTORICO_PERIODO,
    REFRESH_INTERVAL_SECONDS,
)


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


def corrigir_ultima_barra(hist: pd.DataFrame, spot_brapi: float | None) -> tuple[pd.DataFrame, str]:
    """Fix a corrupt last bar (zeroed Open/High/Low from yfinance).

    - Complete bar → unchanged (source ``yfinance``).
    - Corrupt bar + sane brapi spot (within 5 % of previous close) → the bar is
      stamped flat at that price (source ``brapi``).
    - Otherwise → corrupt bar dropped, previous close used (source ``yfinance*``).
    """
    if hist.empty or "Close" not in hist.columns:
        return hist, "yfinance"

    ultima = hist.iloc[-1]
    completa = all(
        col not in hist.columns or ultima[col] > 0
        for col in ("Open", "High", "Low")
    )
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
    """Spot prices from brapi (free tier). Empty dict when unavailable."""
    try:
        from modulos import opcoes_b3

        if not opcoes_b3.token_configurado():
            return {}
        return opcoes_b3.buscar_cotacoes(list(TICKERS))
    except Exception:
        return {}


def _vol_anual(hist: pd.DataFrame, janela: int = 20) -> float | None:
    """Annualised volatility from the last ``janela`` log-returns."""
    from modulos import bs

    try:
        return bs.calcular_vol_historica(hist, janela=janela)
    except Exception:
        return None


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def buscar_dados_mercado() -> dict[str, dict]:
    """Fetch price, daily variation, MAs and volatility for every asset.

    Returns
    -------
    dict[str, dict]
        Per asset: preco, variacao_pct, ma_decisao, mas, vol, hist, fonte_preco.
    """
    spots_brapi = _spots_brapi()
    resultado: dict[str, dict] = {}

    for nome, yf_ticker in TICKERS.items():
        try:
            hist = yf.Ticker(yf_ticker).history(period=HISTORICO_PERIODO)
        except Exception:
            continue

        if hist.empty or len(hist) < 2:
            continue

        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        hist = _preservar_ultimo_ohlc_invalido(hist)
        hist, fonte_preco = corrigir_ultima_barra(hist, spots_brapi.get(nome))

        # Drop anomalous daily moves > 50 %
        var_diaria = hist["Close"].pct_change().abs()
        hist = hist[(var_diaria < 0.50) | var_diaria.isna()].copy()

        if len(hist) < 2:
            continue

        preco_atual = float(hist["Close"].iloc[-1])
        preco_ontem = float(hist["Close"].iloc[-2])
        variacao_pct = (preco_atual - preco_ontem) / preco_ontem

        mas: dict[int, float | None] = {}
        for janela in MA_VISUALIZACAO:
            col = f"MA{janela}"
            hist[col] = hist["Close"].rolling(janela).mean()
            mas[janela] = (
                round(float(hist[col].iloc[-1]), 2) if len(hist) >= janela else None
            )

        resultado[nome] = {
            "preco": round(preco_atual, 2),
            "variacao_pct": round(variacao_pct, 6),
            "ma_decisao": mas.get(MA_PERIODO),
            "mas": mas,
            "vol": _vol_anual(hist),
            "hist": hist,
            "fonte_preco": fonte_preco,
        }

    return resultado


def variacao_fmt(variacao_pct: float) -> str:
    """Format a fractional return, e.g. -0.015 → '-1.50 %'."""
    sinal = "+" if variacao_pct >= 0 else ""
    return f"{sinal}{variacao_pct * 100:.2f} %"


def formatar_reais(valor: float | None) -> str:
    """Format a number as BRL, or '—' when missing."""
    return f"R$ {valor:,.2f}" if valor is not None else "—"
