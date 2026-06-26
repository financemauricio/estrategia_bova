"""Fund-style performance vs benchmark indices (IBOV/BOVA11, IVV, HASH11).

Reconstructs daily net asset value from dated cash and position events, then
calculates fund performance through a quota/NAV series. External flows issue or
redeem quotas; internal activity changes NAV.
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

    Uses the first dated economic event available.
    """
    datas: list[dt.date] = []
    if posicoes:
        datas.extend(
            _to_date(p.get("data_entrada") or p.get("atualizado_em") or dt.date.today())
            for p in posicoes
        )
    if aportes:
        datas.extend(_to_date(a["data"]) for a in aportes)
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
    """Simulate daily fund net asset value (ETFs mark-to-market + cash)."""
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
        qtds = {
                "BOVA11": float(ap.get("bova11_qtd") or 0),
                "IVV":    float(ap.get("ivvb11_qtd") or 0),
                "HASH11": float(ap.get("hash11_qtd") or 0),
        }
        if any(qtds.values()):
            # Cash entry and investment outflow are already in caixa. Here we
            # only add the acquired ETF quantities to avoid counting flows twice.
            eventos.append((d, "aporte_qtd", 0.0, qtds))

    # Positions registered manually (no matching aporte rows)
    if posicoes:
        holdings = {p["ticker"]: float(p["quantidade"]) for p in posicoes}
        qtd_aportes = {t: 0.0 for t in TICKERS}
        for ap in aportes:
            qtd_aportes["BOVA11"] += float(ap.get("bova11_qtd") or 0)
            qtd_aportes["IVV"]    += float(ap.get("ivvb11_qtd") or 0)
            qtd_aportes["HASH11"] += float(ap.get("hash11_qtd") or 0)
        for pos in posicoes:
            ticker = pos["ticker"]
            missing = max(0.0, holdings.get(ticker, 0.0) - qtd_aportes.get(ticker, 0.0))
            if missing <= 0:
                continue
            pos_date = _to_date(
                pos.get("data_entrada") or pos.get("atualizado_em") or dt.date.today()
            )
            # Add holdings that were not reconstructed from aportes.
            eventos.append((pos_date, "posicao_inicial", 0.0, {ticker: missing}))

    eventos.sort(key=lambda x: x[0])
    ev_idx = 0
    valores: list[float] = []

    for dia in precos.index:
        d = dia.date() if hasattr(dia, "date") else dia
        while ev_idx < len(eventos) and eventos[ev_idx][0] <= d:
            _, tipo, valor, extra = eventos[ev_idx]
            if tipo in ("aporte_qtd", "posicao_inicial") and extra:
                for t, dq in extra.items():
                    qtd[t] = qtd.get(t, 0.0) + dq
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


def _fluxos_externos(
    index: pd.Index,
    aportes: list[dict],
    caixa: list[dict],
) -> pd.Series:
    """Return dated external flows: contributions positive, withdrawals negative."""
    fluxos = pd.Series(0.0, index=index)

    def add_fluxo(data_evento: dt.date, valor: float) -> None:
        elegiveis = fluxos.index[fluxos.index.date >= data_evento]
        if len(elegiveis) == 0:
            return
        fluxos.loc[elegiveis[0]] += valor

    for ap in sorted(aportes, key=lambda x: _to_date(x["data"])):
        data_ap = _to_date(ap["data"])
        valor_total = float(ap["valor_total"])
        if valor_total <= 0:
            continue
        add_fluxo(data_ap, valor_total)

    for mov in sorted(caixa, key=lambda x: _to_date(x["data"])):
        descricao = str(mov.get("descricao") or "").lower()
        if any(tag in descricao for tag in ("prêmio", "premio", "recompra", "exercício", "exercicio", "aporte investido")):
            continue
        if "aporte recebido" in descricao:
            continue
        is_external = any(tag in descricao for tag in ("deposito", "depósito", "saque", "resgate"))
        if not is_external:
            continue
        data_mov = _to_date(mov["data"])
        sinal = 1.0 if mov["tipo"] == "ENTRADA" else -1.0
        add_fluxo(data_mov, sinal * float(mov["valor"]))

    return fluxos


def _serie_cotas(
    patrimonio: pd.Series,
    fluxos_externos: pd.Series,
    cota_inicial: float = 100.0,
) -> pd.DataFrame:
    """Build a fund quota series where external flows issue/redeem quotas."""
    pl = patrimonio.dropna()
    positivo = pl[pl > 0]
    if positivo.empty:
        return pd.DataFrame(index=patrimonio.index)

    inicio = positivo.index[0]
    pl = pl[pl.index >= inicio]
    fluxos = fluxos_externos.reindex(pl.index).fillna(0.0)

    cotas = float(pl.iloc[0]) / cota_inicial
    valor_cota = cota_inicial
    rows: list[dict[str, float]] = []

    for dia, pl_dia in pl.items():
        fluxo = float(fluxos.loc[dia])
        if dia != inicio and fluxo and cotas > 0:
            pl_pre_fluxo = float(pl_dia) - fluxo
            cota_pre_fluxo = (
                pl_pre_fluxo / cotas if pl_pre_fluxo > 0 else valor_cota
            )
            if cota_pre_fluxo > 0:
                cotas += fluxo / cota_pre_fluxo
        if cotas <= 0:
            cotas = 0.0
            valor_cota = 0.0
        else:
            valor_cota = float(pl_dia) / cotas
        rows.append({
            "patrimonio": float(pl_dia),
            "fluxo_externo": fluxo,
            "cotas": cotas,
            "valor_cota": valor_cota,
            "retorno_cota_pct": (valor_cota / cota_inicial - 1.0) * 100.0,
        })

    return pd.DataFrame(rows, index=pl.index)


def _simular_retornos_por_aportes(
    preco: pd.Series,
    aportes: list[dict],
    posicoes: list[dict] | None = None,
) -> pd.Series:
    """Simulate benchmark return by investing external capital on the same dates."""
    fluxos_ordenados = [
        (_to_date(ap["data"]), float(ap["valor_total"]))
        for ap in sorted(aportes, key=lambda x: _to_date(x["data"]))
        if float(ap["valor_total"]) > 0
    ]

    qtd_aportes = {t: 0.0 for t in TICKERS}
    for ap in aportes:
        qtd_aportes["BOVA11"] += float(ap.get("bova11_qtd") or 0)
        qtd_aportes["IVV"] += float(ap.get("ivvb11_qtd") or 0)
        qtd_aportes["HASH11"] += float(ap.get("hash11_qtd") or 0)

    for pos in posicoes or []:
        ticker = pos.get("ticker")
        quantidade = float(pos.get("quantidade") or 0)
        missing_qtd = max(0.0, quantidade - qtd_aportes.get(ticker, 0.0))
        if missing_qtd <= 0:
            continue
        custo = float(pos.get("custo_total") or 0)
        if custo <= 0:
            custo = quantidade * float(pos.get("preco_medio") or 0)
        elif quantidade > 0:
            custo = custo * (missing_qtd / quantidade)
        if custo <= 0:
            continue
        fluxos_ordenados.append((
            _to_date(pos.get("data_entrada") or pos.get("atualizado_em") or dt.date.today()),
            custo,
        ))

    fluxos_ordenados.sort(key=lambda x: x[0])
    if not fluxos_ordenados or preco.empty:
        return pd.Series(dtype=float, index=preco.index)

    fluxo_idx = 0
    total_contrib = 0.0
    shares = 0.0
    valores: list[float] = []
    contribuicoes: list[float] = []

    for dia in preco.index:
        d = dia.date() if hasattr(dia, "date") else dia
        while fluxo_idx < len(fluxos_ordenados) and fluxos_ordenados[fluxo_idx][0] <= d:
            amount = fluxos_ordenados[fluxo_idx][1]
            price = float(preco.loc[dia])
            if price > 0:
                shares += amount / price
            total_contrib += amount
            fluxo_idx += 1

        valores.append(shares * float(preco.loc[dia]))
        contribuicoes.append(total_contrib)

    aporte_series = pd.Series(contribuicoes, index=preco.index)
    valor_series = pd.Series(valores, index=preco.index)

    valido = aporte_series > 0
    retorno = pd.Series(index=preco.index, dtype=float)
    if valido.any():
        retorno[valido] = (valor_series[valido] / aporte_series[valido] - 1.0) * 100.0
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

    fluxos_externos = _fluxos_externos(patrimonio.index, aportes, caixa)
    cotas = _serie_cotas(patrimonio, fluxos_externos)
    if cotas.empty:
        return None

    retornos = pd.DataFrame(index=precos.index)
    retornos["Carteira"] = cotas["retorno_cota_pct"]

    for ticker in TICKERS:
        if ticker in precos.columns:
            retornos[_BENCHMARK_LABELS[ticker]] = _simular_retornos_por_aportes(
                precos[ticker], aportes, posicoes
            )

    retornos["Benchmark 70/20/10"] = _benchmark_misto(retornos)
    retornos = retornos.dropna(how="all")
    if retornos.empty or "Carteira" not in retornos:
        return None

    ultimo = retornos.iloc[-1]
    carteira_ret = float(ultimo["Carteira"])
    ultima_cota = cotas.iloc[-1]
    resumo: dict[str, Any] = {
        "carteira_pct": carteira_ret,
        "data_inicio": data_inicio,
        "patrimonio_atual": float(patrimonio.iloc[-1]),
        "valor_cota": float(ultima_cota["valor_cota"]),
        "total_cotas": float(ultima_cota["cotas"]),
        "fluxos_externos": float(cotas["fluxo_externo"].sum()),
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
        "cotas": cotas,
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
        - retornos    : DataFrame (% cumulative, Carteira = quota return)
        - patrimonio  : Series (BRL)
        - cotas       : DataFrame with NAV/quota series
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
