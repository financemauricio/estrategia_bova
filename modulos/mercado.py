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


def _atualizar_ultima_barra(hist: pd.DataFrame, preco: float | None) -> pd.DataFrame:
    """Stamp the latest daily bar with the consensus price (chart + MAs).

    Only when the last bar is recent (≤ 4 days) and the price is plausible
    (≤ 10 % away from that bar's close), so a stale or broken bar is never
    silently overwritten.
    """
    if not preco or hist.empty or "Close" not in hist.columns:
        return hist

    dias = (pd.Timestamp.now().normalize() - hist.index[-1].normalize()).days
    fechamento = float(hist["Close"].iloc[-1])
    if dias > 4 or fechamento <= 0 or abs(preco / fechamento - 1) > 0.10:
        return hist

    fix = hist.copy()
    fix.iloc[-1, fix.columns.get_loc("Close")] = preco
    if "High" in fix.columns:
        fix.iloc[-1, fix.columns.get_loc("High")] = max(float(fix["High"].iloc[-1]), preco)
    if "Low" in fix.columns:
        fix.iloc[-1, fix.columns.get_loc("Low")] = min(float(fix["Low"].iloc[-1]), preco)
    return fix


def _sessao_cotacao(
    hist: pd.DataFrame, preco: float, anterior: float | None, hoje
) -> tuple:
    """Session date of a quote and the close it should be compared against.

    The source's previous close reveals which session its price belongs to:

    - equals the last daily close → quote is from the next session (today);
    - equals the close before → quote is still the last session's close.

    Returns ``(sessao, preco_ontem)``.
    """
    fecho = float(hist["Close"].iloc[-1])
    penultimo = float(hist["Close"].iloc[-2])

    if anterior and anterior > 0 and fecho > 0:
        if abs(anterior - fecho) / fecho <= 0.002:
            sessao = hoje if hist.index[-1].date() < hoje else hist.index[-1].date()
            return sessao, fecho
        if abs(anterior - penultimo) / penultimo <= 0.002:
            return hist.index[-1].date(), penultimo

    if preco and fecho > 0 and abs(preco - fecho) / fecho > 0.002:
        return hoje, fecho
    return hist.index[-1].date(), penultimo


def _vol_anual(hist: pd.DataFrame, janela: int = 20) -> float | None:
    """Annualised volatility from the last ``janela`` log-returns."""
    from modulos import bs

    try:
        return bs.calcular_vol_historica(hist, janela=janela)
    except Exception:
        return None


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def _historico(yf_ticker: str) -> pd.DataFrame:
    """Daily history, cached for the refresh window."""
    try:
        hist = yf.Ticker(yf_ticker).history(period=HISTORICO_PERIODO)
    except Exception:
        return pd.DataFrame()
    if not hist.empty:
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
    return hist


def buscar_dados_mercado() -> dict[str, dict]:
    """Fetch price, daily variation, MAs and volatility for every asset.

    The current price comes from :mod:`modulos.cotacoes` (Yahoo + brapi +
    Status Invest consensus with timestamp); history comes from yfinance.

    Returns
    -------
    dict[str, dict]
        Per asset: preco, variacao_pct, ma_decisao, mas, vol, hist,
        fonte_preco, cotacao (sources, time, confidence).
    """
    from modulos import cotacoes

    resultado: dict[str, dict] = {}

    for nome, yf_ticker in TICKERS.items():
        hist = _historico(yf_ticker)
        if hist.empty or len(hist) < 2:
            continue

        cot = cotacoes.cotacao(nome, yf_ticker)

        hist = _preservar_ultimo_ohlc_invalido(hist)
        hist, fonte_preco = corrigir_ultima_barra(hist, cot.get("preco"))

        # Drop anomalous daily moves > 50 %
        var_diaria = hist["Close"].pct_change().abs()
        hist = hist[(var_diaria < 0.50) | var_diaria.isna()].copy()

        if len(hist) < 2:
            continue

        preco_hist = float(hist["Close"].iloc[-1])
        preco = float(cot["preco"]) if cot.get("preco") else preco_hist
        hoje = cotacoes.agora_brt().date()
        aberto = cotacoes.mercado_aberto()

        # Which session does the quote belong to? A source's previous close
        # reveals it: matching the last close means today's session; matching
        # the one before means the feed is still showing the last close.
        sessao, preco_ontem = _sessao_cotacao(hist, preco, cot.get("anterior"), hoje)

        variacao_pct = (preco - preco_ontem) / preco_ontem if preco_ontem else 0.0

        cot["mercado_aberto"] = aberto
        cot["sessao_hoje"] = sessao == hoje
        cot["possivel_atraso"] = bool(sessao < hoje and aberto)
        cot["data_referencia"] = sessao.strftime("%d/%m") if sessao < hoje else None

        # Only stamp the last bar when the quote belongs to that same session;
        # a live price from a newer session must not overwrite yesterday's close.
        if sessao == hist.index[-1].date():
            hist = _atualizar_ultima_barra(hist, preco)

        mas: dict[int, float | None] = {}
        for janela in MA_VISUALIZACAO:
            col = f"MA{janela}"
            hist[col] = hist["Close"].rolling(janela).mean()
            mas[janela] = (
                round(float(hist[col].iloc[-1]), 2) if len(hist) >= janela else None
            )

        resultado[nome] = {
            "preco": round(preco, 2),
            "variacao_pct": round(variacao_pct, 6),
            "ma_decisao": mas.get(MA_PERIODO),
            "mas": mas,
            "vol": _vol_anual(hist),
            "hist": hist,
            "fonte_preco": cot.get("fonte", fonte_preco),
            "cotacao": cot,
            "data_barra": hist.index[-1].strftime("%d/%m/%Y"),
        }

    return resultado


def variacao_fmt(variacao_pct: float) -> str:
    """Format a fractional return, e.g. -0.015 → '-1.50 %'."""
    sinal = "+" if variacao_pct >= 0 else ""
    return f"{sinal}{variacao_pct * 100:.2f} %"


def formatar_reais(valor: float | None) -> str:
    """Format a number as BRL, or '—' when missing."""
    return f"R$ {valor:,.2f}" if valor is not None else "—"
