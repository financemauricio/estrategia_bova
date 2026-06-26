"""Portfolio performance vs benchmark indices (IBOV/BOVA11, IVV, HASH11).

Reconstructs daily portfolio value from aportes, caixa ledger and ETF
positions, then compares cumulative returns (%) against each benchmark
normalised to the same start date.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from config import ALOCACAO_ALVO, TICKERS, TICKER_USDBRL, REFRESH_INTERVAL_SECONDS

_BENCHMARK_LABELS: dict[str, str] = {
    "BOVA11": "IBOV (BOVA11)",
    "IVV":    "S&P 500 (IVV)",
    "HASH11": "HASH11",
}


def _to_date(val: Any) -> dt.date:
    if isinstance(val, dt.date) and not isinstance(val, dt.datetime):
        return val
    if isinstance(val, dt.datetime):
        return val.date()
    if isinstance(val, str):
        return dt.date.fromisoformat(val[:10])
    return dt.date.today()


def _data_inicio_carteira(
    aportes: list[dict],
    caixa: list[dict],
    posicoes: list[dict],
    opcoes: list[dict],
) -> dt.date | None:
    """Return the date the portfolio was assembled (ETF holdings in place).

    Priority: first ETF position → first aporte → earliest ledger event.
    Cash-only days before ETFs are excluded so returns are not distorted.
    """
    if posicoes:
        return min(
            _to_date(p.get("atualizado_em") or dt.date.today()) for p in posicoes
        )
    if aportes:
        return min(_to_date(a["data"]) for a in aportes)
    datas: list[dt.date] = []
    for c in caixa:
        datas.append(_to_date(c["data"]))
    for o in opcoes:
        datas.append(_to_date(o["data_abertura"]))
    return min(datas) if datas else None


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner=False)
def _buscar_precos_brl(data_inicio: dt.date) -> pd.DataFrame:
    """Fetch daily close prices in BRL for portfolio ETFs from ``data_inicio``."""
    inicio_str = data_inicio.isoformat()
    frames: dict[str, pd.Series] = {}

    try:
        fx = yf.Ticker(TICKER_USDBRL).history(
            start=inicio_str, auto_adjust=True,
        )
        if not fx.empty:
            fx.index = pd.to_datetime(fx.index).tz_localize(None)
            fx_s = fx["Close"]
        else:
            fx_s = None
    except Exception:
        fx_s = None

    for nome, yf_ticker in TICKERS.items():
        try:
            hist = yf.Ticker(yf_ticker).history(
                start=inicio_str, auto_adjust=True,
            )
        except Exception:
            continue
        if hist.empty:
            continue
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        close = hist["Close"].copy()
        if nome == "IVV" and fx_s is not None:
            aligned = pd.concat([close, fx_s], axis=1, join="inner")
            aligned.columns = ["ativo", "fx"]
            close = aligned["ativo"] * aligned["fx"]
        frames[nome] = close

    if not frames:
        return pd.DataFrame()

    df = pd.DataFrame(frames).sort_index().ffill()
    return df[df.index.date >= data_inicio]


def _reconstruir_patrimonio(
    precos: pd.DataFrame,
    aportes: list[dict],
    caixa: list[dict],
    posicoes: list[dict],
) -> pd.Series:
    """Simulate daily portfolio value (ETFs mark-to-market + cash)."""
    if precos.empty:
        return pd.Series(dtype=float)

    cash = 0.0
    qtd = {t: 0.0 for t in TICKERS}

    # Sort ledger events chronologically
    eventos: list[tuple[dt.date, str, float, dict | None]] = []

    for mov in sorted(caixa, key=lambda x: _to_date(x["data"])):
        d = _to_date(mov["data"])
        sinal = 1.0 if mov["tipo"] == "ENTRADA" else -1.0
        eventos.append((d, "caixa", sinal * float(mov["valor"]), None))

    for ap in sorted(aportes, key=lambda x: _to_date(x["data"])):
        d = _to_date(ap["data"])
        eventos.append((d, "aporte_caixa", float(ap["valor_total"]), None))
        investido = (
            float(ap.get("bova11_valor") or 0)
            + float(ap.get("ivvb11_valor") or 0)
            + float(ap.get("hash11_valor") or 0)
        )
        if investido > 0:
            eventos.append((d, "aporte_invest", -investido, {
                "BOVA11": float(ap.get("bova11_qtd") or 0),
                "IVV":    float(ap.get("ivvb11_qtd") or 0),
                "HASH11": float(ap.get("hash11_qtd") or 0),
            }))

    # Positions registered manually (no matching aporte rows)
    if posicoes:
        pos_date = min(_to_date(p.get("atualizado_em") or dt.date.today()) for p in posicoes)
        holdings = {p["ticker"]: float(p["quantidade"]) for p in posicoes}
        # Only apply implicit purchase if aportes did not already build holdings
        qtd_aportes = {t: 0.0 for t in TICKERS}
        for ap in aportes:
            qtd_aportes["BOVA11"] += float(ap.get("bova11_qtd") or 0)
            qtd_aportes["IVV"]    += float(ap.get("ivvb11_qtd") or 0)
            qtd_aportes["HASH11"] += float(ap.get("hash11_qtd") or 0)
        if sum(qtd_aportes.values()) < 0.01:
            # Holdings registered manually — do not debit caixa (may pre-exist the ledger)
            eventos.append((pos_date, "posicao_inicial", 0.0, holdings))

    eventos.sort(key=lambda x: x[0])
    ev_idx = 0
    valores: list[float] = []

    for dia in precos.index:
        d = dia.date() if hasattr(dia, "date") else dia
        while ev_idx < len(eventos) and eventos[ev_idx][0] <= d:
            _, tipo, valor, extra = eventos[ev_idx]
            if tipo == "aporte_invest" and extra:
                cash += valor
                for t, dq in extra.items():
                    qtd[t] = qtd.get(t, 0.0) + dq
            elif tipo == "posicao_inicial" and extra:
                cash += valor
                for t, dq in extra.items():
                    qtd[t] = dq
            else:
                cash += valor
            ev_idx += 1

        etf_val = 0.0
        row = precos.loc[dia]
        for t in TICKERS:
            if t in row and pd.notna(row[t]) and qtd.get(t, 0) > 0:
                etf_val += qtd[t] * float(row[t])
        valores.append(etf_val + cash)

    return pd.Series(valores, index=precos.index, name="Carteira")


def _retorno_acumulado(series: pd.Series) -> pd.Series:
    """Normalise a price/value series to cumulative return (%) from first valid point."""
    s = series.dropna()
    if s.empty:
        return s
    base = float(s.iloc[0])
    if base <= 0:
        positivo = s[s > 0]
        if positivo.empty:
            return pd.Series(0.0, index=s.index)
        base = float(positivo.iloc[0])
        s = s[s.index >= positivo.index[0]]
    return (s / base - 1.0) * 100.0


def _retorno_sobre_aportes(
    patrimonio: pd.Series,
    aportes: list[dict],
) -> pd.Series:
    """Compute portfolio return relative to total contributed capital.

    This prevents contributions from being counted as performance gains.
    """
    if not aportes:
        return _retorno_acumulado(patrimonio)

    contribuicoes = pd.Series(0.0, index=patrimonio.index)
    for ap in sorted(aportes, key=lambda x: _to_date(x["data"])):
        data_ap = _to_date(ap["data"])
        valor_total = float(ap["valor_total"])
        if valor_total <= 0:
            continue
        contribuicoes.loc[contribuicoes.index.date >= data_ap] += valor_total

    valido = contribuicoes > 0
    if not valido.any():
        return _retorno_acumulado(patrimonio)

    retorno = pd.Series(index=patrimonio.index, dtype=float)
    retorno[valido] = (
        (patrimonio[valido] - contribuicoes[valido])
        / contribuicoes[valido]
        * 100.0
    )
    return retorno.dropna()


def _benchmark_misto(retornos_pct: pd.DataFrame) -> pd.Series:
    """Weighted blend of benchmark returns using ALOCACAO_ALVO weights."""
    blend = pd.Series(0.0, index=retornos_pct.index)
    peso_usado = 0.0
    for ticker, label in _BENCHMARK_LABELS.items():
        if label not in retornos_pct.columns:
            continue
        w = ALOCACAO_ALVO.get(ticker, 0.0)
        blend += retornos_pct[label] * w
        peso_usado += w
    return blend / peso_usado if peso_usado > 0 else blend


def _calcular_performance(
    aportes: list[dict],
    caixa: list[dict],
    posicoes: list[dict],
    opcoes: list[dict],
) -> dict[str, Any] | None:
    """Core performance logic (uncached — accepts DB rows)."""
    data_inicio = _data_inicio_carteira(aportes, caixa, posicoes, opcoes)
    if not data_inicio:
        return None

    precos = _buscar_precos_brl(data_inicio)
    if precos.empty:
        return None

    patrimonio = _reconstruir_patrimonio(precos, aportes, caixa, posicoes)
    if patrimonio.empty or patrimonio.max() <= 0:
        return None

    retornos = pd.DataFrame(index=precos.index)
    retornos["Carteira"] = _retorno_sobre_aportes(patrimonio, aportes)

    for ticker in TICKERS:
        if ticker in precos.columns:
            retornos[_BENCHMARK_LABELS[ticker]] = _retorno_acumulado(precos[ticker])

    retornos["Benchmark 70/20/10"] = _benchmark_misto(retornos)

    ultimo = retornos.iloc[-1]
    carteira_ret = float(ultimo["Carteira"])
    resumo: dict[str, Any] = {
        "carteira_pct": carteira_ret,
        "data_inicio": data_inicio,
        "patrimonio_atual": float(patrimonio.iloc[-1]),
        "alphas": {},
    }
    for col in retornos.columns:
        if col == "Carteira":
            continue
        bench_ret = float(ultimo[col])
        resumo["alphas"][col] = carteira_ret - bench_ret

    return {
        "data_inicio": data_inicio,
        "retornos": retornos,
        "patrimonio": patrimonio,
        "resumo": resumo,
    }


@st.cache_data(ttl=REFRESH_INTERVAL_SECONDS, show_spinner="Calculando performance…")
def calcular_performance() -> dict[str, Any] | None:
    """Build cumulative-return series for portfolio and benchmarks.

    Loads fresh data from the database inside the cache (no list arguments —
    Streamlit cannot hash mutable list params).

    Returns
    -------
    dict or None
        - data_inicio : date
        - retornos    : DataFrame (% cumulative)
        - patrimonio  : Series (BRL)
        - resumo      : dict of latest return % and alpha vs each benchmark
    """
    from modulos import banco

    return _calcular_performance(
        banco.listar_aportes(),
        banco.listar_caixa(limit=None),
        banco.listar_posicoes(),
        banco.listar_opcoes(),
    )


def grafico_performance(retornos: pd.DataFrame) -> go.Figure:
    """Build a line chart of cumulative returns (%)."""
    cores = {
        "Carteira":           "#3498db",
        "IBOV (BOVA11)":      "#e74c3c",
        "S&P 500 (IVV)":      "#2ecc71",
        "HASH11":             "#f39c12",
        "Benchmark 70/20/10": "#9b59b6",
    }
    fig = go.Figure()
    for col in retornos.columns:
        fig.add_trace(go.Scatter(
            x=retornos.index,
            y=retornos[col],
            mode="lines",
            name=col,
            line=dict(width=3 if col == "Carteira" else 1.5, color=cores.get(col, "#888")),
        ))
    fig.add_hline(y=0, line_dash="dot", line_color="#555", opacity=0.6)
    fig.update_layout(
        xaxis_title="Data",
        yaxis_title="Retorno acumulado (%)",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.18,
            x=0,
            xanchor="left",
        ),
        height=400,
        margin=dict(t=20, b=80, l=20, r=20),
        hovermode="x unified",
    )
    fig.update_yaxes(ticksuffix="%")
    return fig
