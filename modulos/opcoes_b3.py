"""B3 option chain via brapi.dev — real puts/calls codes and bid/ask quotes.

Endpoints (require free token from https://b3ag0-br-ar1-nic-noc-n-s):
    GET /api/v2/options/expirations?underlying=BOVA11
    GET /api/v2/options/chain?underlying=BOVA11&expiration=YYYY-MM-DD

Quotes on the free tier are delayed (~15 min) — good enough for
picking the series and checking the rule, NOT for scalping.
Always confirm the final price in the Home Broker before operating.
"""

from __future__ import annotations

import math
import os

import streamlit as st

BRAPI_BASE = "https://brapi.dev"

# Rule defaults (mirrors config.py — imported lazily to avoid cycles)
DELTA_PUT_MIN = -0.30
DELTA_PUT_MAX = -0.20


def _get_token() -> str:
    """Return BRAPI_TOKEN from Streamlit secrets or environment."""
    try:
        token = st.secrets.get("BRAPI_TOKEN", "")
        if token:
            return str(token)
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    return os.getenv("BRAPI_TOKEN", "")


def token_configurado() -> bool:
    """True when a brapi token is available."""
    return bool(_get_token())


def _get(url: str, params: dict | None = None) -> dict | list:
    import requests

    token = _get_token()
    if not token:
        raise RuntimeError(
            "BRAPI_TOKEN não configurado. Crie grátis em brapi.dev e adicione "
            "em `.streamlit/secrets.toml` (local) ou nos Secrets do Streamlit Cloud."
        )
    resp = requests.get(
        url,
        params=params or {},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3_600, show_spinner=False)
def buscar_vencimentos(underlying: str = "BOVA11") -> list[str]:
    """Return available option expiry dates (YYYY-MM-DD) for an underlying."""
    data = _get(f"{BRAPI_BASE}/api/v2/options/expirations", {"underlying": underlying.upper()})
    if isinstance(data, dict):
        for key in ("expirations", "results", "expiracoes", "datas"):
            if isinstance(data.get(key), list):
                return [str(x)[:10] for x in data[key]]
        # single dict shape
        return []
    if isinstance(data, list):
        return [str(x)[:10] for x in data]
    return []


def _extrair_serie(raw: dict) -> dict | None:
    """Normalise one option entry from brapi's chain payload (defensive)."""
    if not isinstance(raw, dict):
        return None
    codigo = raw.get("symbol") or raw.get("code") or raw.get("codigo") or raw.get("ticker")
    tipo = str(raw.get("type") or raw.get("tipo") or raw.get("optionType") or "").upper()
    if "PUT" in tipo:
        tipo = "PUT"
    elif "CALL" in tipo:
        tipo = "CALL"
    else:
        return None
    try:
        strike = float(raw.get("strike") or raw.get("strikePrice") or raw.get("preco_exercicio") or 0)
    except (TypeError, ValueError):
        return None
    if not codigo or strike <= 0:
        return None

    def _num(*keys: str) -> float | None:
        for k in keys:
            try:
                v = raw.get(k)
                if v is not None and float(v) > 0:
                    return float(v)
            except (TypeError, ValueError):
                continue
        return None

    return {
        "codigo": str(codigo).upper(),
        "tipo": tipo,
        "strike": strike,
        "bid": _num("bid", "bidPrice", "bestBid"),
        "ask": _num("ask", "askPrice", "bestAsk"),
        "last": _num("last", "close", "regularMarketPrice", "price", "lastPrice"),
        "volume": int(raw.get("volume") or 0),
    }


@st.cache_data(ttl=300, show_spinner="Buscando cadeia de opções na B3...")
def buscar_cadeia(underlying: str = "BOVA11", expiration: str = "") -> list[dict]:
    """Return normalised option series for one expiry date."""
    params = {"underlying": underlying.upper()}
    if expiration:
        params["expiration"] = expiration
    data = _get(f"{BRAPI_BASE}/api/v2/options/chain", params)
    raws: list = []
    if isinstance(data, dict):
        for key in ("options", "chain", "results", "series"):
            if isinstance(data.get(key), list):
                raws = data[key]
                break
        else:
            # maybe {puts: [...], calls: [...]}
            for key in ("puts", "calls"):
                if isinstance(data.get(key), list):
                    raws += data[key]
    elif isinstance(data, list):
        raws = data
    series = []
    for r in raws:
        s = _extrair_serie(r)
        if s:
            series.append(s)
    return series


def delta_put(spot: float, strike: float, dias: int, selic: float, vol: float) -> float | None:
    """Put delta (N(d1)-1) via Black-Scholes. Pure function — easy to test."""
    if spot <= 0 or strike <= 0 or dias <= 0 or vol <= 0:
        return None
    T = max(dias, 1) / 252
    d1 = (math.log(spot / strike) + (selic + 0.5 * vol ** 2) * T) / (vol * math.sqrt(T))
    return (1.0 + math.erf(d1 / math.sqrt(2.0))) / 2.0 - 1.0


def strike_para_delta(
    spot: float, delta_alvo: float, dias: int, selic: float, vol: float,
) -> float | None:
    """Strike whose put delta equals ``delta_alvo``. Pure function.

    Used when the live chain is unavailable (free brapi tier): the app
    tells the exact strike to look for in the Home Broker.
    """
    if spot <= 0 or dias <= 0 or vol <= 0 or not -0.6 < delta_alvo < 0:
        return None
    lo, hi = spot * 0.70, spot  # put delta is monotonic in strike here
    for _ in range(60):
        mid = (lo + hi) / 2
        d = delta_put(spot, mid, dias, selic, vol)
        if d is None:
            return None
        if d < delta_alvo:
            hi = mid   # delta negativo demais → strike alto demais, baixar
        else:
            lo = mid
    return round((lo + hi) / 2, 2)


def filtrar_puts_regra(    cadeia: list[dict],
    spot: float,
    dias: int,
    selic: float,
    vol: float,
    delta_min: float = DELTA_PUT_MIN,
    delta_max: float = DELTA_PUT_MAX,
    premio_min: float = 1.50,
) -> list[dict]:
    """Flag PUT series that satisfy the sell rule. Pure function.

    A series is a candidate when delta is within [delta_min, delta_max]
    AND bid >= premio_min. Sorted by distance to the middle of the band.
    """
    alvo = (delta_min + delta_max) / 2
    out = []
    for s in cadeia:
        if s.get("tipo") != "PUT":
            continue
        d = delta_put(spot, s["strike"], dias, selic, vol)
        bid = s.get("bid") or 0.0
        dentro = d is not None and delta_min <= d <= delta_max and bid >= premio_min
        out.append({**s, "delta": d, "candidata": dentro,
                    "_dist": abs(d - alvo) if d is not None else 9.9})
    return sorted(out, key=lambda r: (not r["candidata"], r["_dist"]))
