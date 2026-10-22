"""Multi-source quote: Yahoo + brapi + Status Invest, with timestamp and
divergence check.

The current price is the app's main input, so it is fetched from independent
sources, compared, and returned with the time it refers to.
Nothing is stored.
"""

from __future__ import annotations

import datetime as dt
import re

import requests
import streamlit as st

_YAHOO = "https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}"
_BRAPI = "https://brapi.dev/api/quote/{ticker}"
_STATUSINVEST = "https://statusinvest.com.br/{tipo}/{ativo}"
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

# Brazilian market time (B3): UTC-3, no DST since 2019.
BRT = dt.timezone(dt.timedelta(hours=-3))


def agora_brt() -> dt.datetime:
    """Current time in São Paulo (UTC-3), regardless of server timezone."""
    return dt.datetime.now(BRT)


def mercado_aberto(agora: dt.datetime | None = None) -> bool:
    """B3 regular session: weekdays, 10:00–18:00 BRT (holidays ignored)."""
    agora = agora or agora_brt()
    return agora.weekday() < 5 and 10 <= agora.hour < 18


def _yahoo(ticker: str) -> dict | None:
    """Latest trade from Yahoo chart metadata (has a real trading time)."""
    for host in ("query1", "query2"):
        try:
            resp = requests.get(
                _YAHOO.format(host=host, ticker=ticker),
                params={"interval": "5m", "range": "1d"},
                headers=_UA,
                timeout=15,
            )
            resp.raise_for_status()
            meta = resp.json()["chart"]["result"][0]["meta"]
            preco = float(meta.get("regularMarketPrice") or 0)
            ts = meta.get("regularMarketTime")
            if preco <= 0 or not ts:
                continue
            hora = dt.datetime.fromtimestamp(ts, dt.timezone.utc).astimezone(
                dt.timezone(dt.timedelta(hours=-3))
            )
            anterior = meta.get("chartPreviousClose") or meta.get("previousClose")
            return {
                "fonte": "Yahoo",
                "preco": preco,
                "hora": hora,
                "ts": float(ts),
                "anterior": float(anterior) if anterior else None,
            }
        except Exception:
            continue
    return None


def _brapi(ativo: str) -> dict | None:
    """Latest quote from brapi (free tier).

    brapi's ``regularMarketTime`` is the feed update time, not the trade time,
    so it is intentionally not used as the quote's timestamp.
    """
    try:
        from modulos import opcoes_b3

        token = opcoes_b3._get_token()
        if not token:
            return None
        resp = requests.get(
            _BRAPI.format(ticker=ativo),
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        res = resp.json()["results"][0]
        preco = float(res.get("regularMarketPrice") or 0)
        if preco <= 0:
            return None
        anterior = res.get("regularMarketPreviousClose")
        return {
            "fonte": "brapi",
            "preco": preco,
            "hora": None,
            "ts": 0.0,
            "anterior": float(anterior) if anterior else None,
        }
    except Exception:
        return None


def _statusinvest(nome: str) -> dict | None:
    """Cross-check price from Status Invest (scraped, no trade timestamp).

    ETFs on B3 use the ``11`` suffix; everything else here is a stock.
    """
    tipo = "etfs" if nome.upper().endswith("11") else "acoes"
    try:
        resp = requests.get(
            _STATUSINVEST.format(tipo=tipo, ativo=nome.lower()),
            headers=_UA,
            timeout=20,
        )
        resp.raise_for_status()
        achado = re.search(
            r'Valor atual.*?<strong class="value">([\d.,]+)</strong>',
            resp.text,
            re.S,
        )
        if not achado:
            return None
        preco = float(achado.group(1).replace(".", "").replace(",", "."))
        if preco <= 0:
            return None
        return {
            "fonte": "Status Invest",
            "preco": preco,
            "hora": None,
            "ts": 0.0,
            "anterior": None,
        }
    except Exception:
        return None


@st.cache_data(ttl=90, show_spinner=False)
def cotacao(nome: str, yf_ticker: str) -> dict:
    """Consensus price from all sources that answered.

    Returns
    -------
    dict
        preco, fonte ('consenso' | 'Yahoo' | 'brapi' | '—'), hora (datetime|None),
        confianca ('alta' | 'divergente' | 'unica' | 'sem_dados'),
        fontes (list of dict with fonte/preco/hora), dispersao_pct.
    """
    fontes = [f for f in (_yahoo(yf_ticker), _brapi(nome), _statusinvest(nome)) if f]

    if not fontes:
        return {
            "preco": None, "fonte": "—", "hora": None, "anterior": None,
            "confianca": "sem_dados", "fontes": [], "dispersao_pct": None,
        }

    precos = [f["preco"] for f in fontes]
    menor, maior = min(precos), max(precos)
    referencia = sorted(precos)[len(precos) // 2]
    dispersao = (maior - menor) / referencia if referencia else 0.0

    # Yahoo carries the exchange's real trade time; prefer it for time and price.
    yahoo = next((f for f in fontes if f["fonte"] == "Yahoo"), None)
    escolhida = yahoo or fontes[0]

    if len(fontes) == 1:
        confianca = "unica"
    elif dispersao <= 0.008:
        confianca = "alta"
    else:
        confianca = "divergente"

    anterior = next((f["anterior"] for f in (yahoo, *fontes) if f and f.get("anterior")), None)

    return {
        "preco": round(escolhida["preco"], 2),
        "fonte": "consenso" if len(fontes) > 1 and confianca == "alta" else escolhida["fonte"],
        "hora": escolhida.get("hora"),
        "anterior": round(anterior, 2) if anterior else None,
        "confianca": confianca,
        "fontes": fontes,
        "dispersao_pct": round(dispersao * 100, 3),
    }


def _hora_legivel(hora: dt.datetime | None) -> str:
    """Trade time from Yahoo, e.g. '21/10 17:19'."""
    if not hora:
        return "sem horário"
    return hora.strftime("%d/%m %H:%M")


def hora_curta(cot: dict) -> str:
    """Short label for a table cell: '17:19', 'fech. 21/10', 'hoje' or '—'."""
    if cot.get("data_referencia"):
        return "fech. " + cot["data_referencia"]
    hora = cot.get("hora")
    if hora:
        return hora.strftime("%H:%M")
    if cot.get("sessao_hoje"):
        return "hoje"
    return "—"


def descricao_cotacao(cot: dict) -> str:
    """Human-readable one-liner with the reference date and source names."""
    if not cot.get("preco"):
        return "cotação indisponível"

    if cot.get("data_referencia"):
        quando = "fechamento de " + cot["data_referencia"]
        if cot.get("mercado_aberto"):
            quando += " (o preço de hoje ainda não chegou)"
    elif cot.get("hora"):
        quando = _hora_legivel(cot["hora"])
    elif cot.get("sessao_hoje"):
        quando = "hoje, sem horário exato"
    else:
        quando = "sem horário"

    if len(cot.get("fontes", [])) > 1:
        nomes = " + ".join(f["fonte"] for f in cot["fontes"])
        if cot["confianca"] == "alta":
            texto = f"{quando} · {nomes} (concordam)"
        else:
            texto = f"{quando} · {nomes} (divergem {cot['dispersao_pct']:.2f} %)"
    else:
        fonte = cot["fontes"][0]["fonte"] if cot.get("fontes") else "—"
        texto = f"{quando} · {fonte}"

    if cot.get("mercado_aberto"):
        texto += " · fonte gratuita, atraso de até 15 min"
    return texto
