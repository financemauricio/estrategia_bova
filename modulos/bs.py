"""Black-Scholes pricing and related market analytics.

Provides theoretical option prices using historical volatility and the
live Selic rate (fetched from the Banco Central do Brasil public API).
No external dependencies beyond the Python standard library and pandas.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Selic rate
# ---------------------------------------------------------------------------

@st.cache_data(ttl=86_400, show_spinner=False)
def buscar_selic() -> float:
    """Return the current annual Selic rate as a decimal (e.g. 0.1325).

    Fetches the latest value from the BCB (Banco Central do Brasil) public
    time-series API. Falls back to 0.1075 on any network error.

    Returns
    -------
    float
        Annual rate, e.g. 0.1325 for 13.25 %.
    """
    import requests  # available via yfinance's dependency chain

    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11"
        "/dados/ultimos/1?formato=json"
    )
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return float(resp.json()[0]["valor"]) / 100
    except Exception:
        return 0.1075  # safe fallback


# ---------------------------------------------------------------------------
# Historical volatility
# ---------------------------------------------------------------------------

def calcular_vol_historica(hist: pd.DataFrame, janela: int = 20) -> float:
    """Compute annualised historical volatility from daily log-returns.

    Parameters
    ----------
    hist : pd.DataFrame
        Price history with a ``Close`` column.
    janela : int
        Number of trading days to use (default 20 ≈ 1 month).

    Returns
    -------
    float
        Annualised volatility (e.g. 0.25 for 25 %).

    Raises
    ------
    ValueError
        If ``hist`` has fewer rows than ``janela``.
    """
    log_ret = (hist["Close"] / hist["Close"].shift(1)).apply(math.log).dropna()
    if len(log_ret) < janela:
        raise ValueError(f"Histórico insuficiente: {len(log_ret)} < {janela}")
    vol_diaria = float(log_ret.tail(janela).std())
    return vol_diaria * math.sqrt(252)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def preco_put_bs(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """European PUT price via Black-Scholes.

    Parameters
    ----------
    S : float
        Current underlying price.
    K : float
        Strike price.
    T : float
        Time to expiry in years (e.g. 30/252).
    r : float
        Annual risk-free rate (decimal).
    sigma : float
        Annual volatility (decimal).

    Returns
    -------
    float
        Theoretical PUT price.

    Examples
    --------
    >>> preco_put_bs(120, 120, 30/252, 0.1325, 0.25)
    4.37
    """
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def preco_call_bs(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """European CALL price via Black-Scholes.

    Parameters
    ----------
    S : float
        Current underlying price.
    K : float
        Strike price.
    T : float
        Time to expiry in years.
    r : float
        Annual risk-free rate (decimal).
    sigma : float
        Annual volatility (decimal).

    Returns
    -------
    float
        Theoretical CALL price.
    """
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
