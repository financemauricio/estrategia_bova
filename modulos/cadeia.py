"""Cadeia real de opções da B3 (opcoes.net.br), de graça e sem login.

A API devolve o último negócio de cada série (fechamento do dia anterior),
com strike, delta, volatilidade implícita e liquidez. É a referência que
faltava: o prêmio teórico (Black-Scholes com volatilidade histórica) serve
para a regra, mas o preço que o mercado pagou está aqui.

Nada é armazenado. Uma requisição por ativo, cache de 15 min.
"""

from __future__ import annotations

import time

import requests
import streamlit as st

from config import CALL_STRIKE_OTM_ESTICADO_PCT, DELTA_PUT_RENDA

_API = "https://opcoes.net.br/api/v1"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "Chrome/120 Safari/537.36"
    ),
}
# Colunas que interessam (a API devolve 23; mapeamos pelo id).
_CAMPOS = ("s", "p", "d", "i", "n", "f", "h")


@st.cache_data(ttl=900, show_spinner=False)
def cadeia(ativo: str) -> dict:
    """Busca e decodifica a cadeia de opções de um ativo.

    Returns
    -------
    dict
        ``{"ok": True, "data": "2026-10-21", "spot": 203.5, "hv": 0.256,
        "expiracoes": [...]}`` ou ``{"ok": False, "erro": "..."}``.
    """
    z = int(time.time() // 10)
    url = (
        f"{_API}?z={z}&r0t=LastQuotesInfo"
        "&r1t=OptionsChain&r1p.columns_info=true&r1p.load=8&r1p.skip=0"
        f"&r1p.underlying_asset_id={ativo}&r1p.underlying_quotes=true"
    )
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=25)
        resp.raise_for_status()
        return _parse(resp.json())
    except Exception as exc:  # rede, timeout, JSON inválido
        return {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}


def _f(valor) -> float | None:
    """Converte número da API (pode vir None ou string) em float."""
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _parse(payload: dict) -> dict:
    """Decodifica a resposta bruta da API (função pura, testável)."""
    requisicoes = payload.get("requests") or []
    data = None
    for req in requisicoes:
        if req.get("type") == "LastQuotesInfo":
            data = (req.get("results") or {}).get("dateLastQuotesInDB")
            break

    bruto = None
    for req in requisicoes:
        if req.get("type") == "OptionsChain":
            bruto = req.get("results") or {}
            break
    if not bruto:
        return {"ok": False, "erro": "resposta sem OptionsChain"}

    cols = [c.get("id") for c in bruto.get("columns") or []]
    sub = bruto.get("underlying_asset") or {}

    expiracoes = []
    for exp in bruto.get("expirations") or []:
        item = {
            "vencimento": exp.get("dt"),
            "dias": int(exp.get("dc") or 0),
            "semanal": bool(exp.get("w")),
            "calls": _linhas(exp.get("calls"), cols),
            "puts": _linhas(exp.get("puts"), cols),
        }
        if item["calls"] or item["puts"]:
            expiracoes.append(item)

    return {
        "ok": True,
        "data": data,
        "spot": _f(sub.get("p")),
        "hv": _f(sub.get("evl")),
        "iv_c": _f(sub.get("iv_c")),
        "iv_p": _f(sub.get("iv_p")),
        "expiracoes": expiracoes,
    }


def _linhas(rows, cols) -> list[dict]:
    """Converte as linhas (listas) em dicionários, descartando sem negócio."""
    saida = []
    for row in rows or []:
        r = dict(zip(cols, row))
        preco = _f(r.get("p"))
        strike = _f(r.get("s"))
        if preco is None or preco <= 0 or strike is None or strike <= 0:
            continue
        saida.append(
            {
                "strike": strike,
                "preco": preco,
                "delta": _f(r.get("d")),
                "iv_bruta": _f(r.get("i")),
                "negocios": int(_f(r.get("n")) or 0),
                "financeiro": _f(r.get("f")),
                "data": r.get("h"),
            }
        )
    saida.sort(key=lambda o: o["strike"])
    return saida


def vencimento_mais_proximo(cad: dict, dias: int) -> dict | None:
    """Vencimento com número de dias mais próximo do usado na regra."""
    exps = [e for e in cad.get("expiracoes", []) if e["dias"] > 0]
    if not exps:
        return None
    return min(exps, key=lambda e: abs(e["dias"] - int(dias)))


def opcao_sugerida(
    exp: dict,
    tipo: str,
    spot: float,
    delta_alvo: float = DELTA_PUT_RENDA,
    strike_ref: float | None = None,
) -> dict | None:
    """Série mais próxima da regra.

    ``strike_ref`` manda: quando o app já calculou o strike sugerido, a
    cadeia real usa esse strike (mais fiel ao que será mostrado). Sem ele,
    mantém o fallback antigo: CALL +3 % OTM ou PUT pelo delta.
    """
    lista = exp.get("calls" if tipo.upper() == "CALL" else "puts") or []
    if not lista or not spot or spot <= 0:
        return None

    if strike_ref is not None and strike_ref > 0:
        return min(lista, key=lambda o: abs(o["strike"] - strike_ref))

    if tipo.upper() == "CALL":
        alvo = spot * (1 + CALL_STRIKE_OTM_ESTICADO_PCT)
        return min(lista, key=lambda o: abs(o["strike"] - alvo))

    com_delta = [o for o in lista if o.get("delta") is not None]
    if not com_delta:
        return None
    return min(com_delta, key=lambda o: abs((o["delta"] or 0.0) - delta_alvo))


def resumo_premio(
    cad: dict,
    tipo: str,
    spot: float,
    dias: int,
    selic: float,
    delta_alvo: float = DELTA_PUT_RENDA,
    strike_ref: float | None = None,
) -> dict | None:
    """Prêmio real (último negócio) do vencimento mais próximo de ``dias``.

    A IV é recalculada com o nosso Black-Scholes a partir do preço real —
    a IV publicada pelo site usa outra convenção e não bate com o prêmio.
    """
    if not cad.get("ok") or not spot or spot <= 0:
        return None
    exp = vencimento_mais_proximo(cad, dias)
    if not exp:
        return None

    # O prêmio é de fechamento: strike e IV precisam usar o spot daquele
    # fechamento, não o preço intraday de agora.
    ref = cad.get("spot") or spot
    op = opcao_sugerida(exp, tipo, ref, delta_alvo, strike_ref)
    if not op:
        return None

    from modulos import bs  # import tardio evita ciclo na carga do app

    T = max(exp["dias"], 1) / 252
    iv = bs.vol_implicita(op["preco"], ref, op["strike"], T, selic, tipo.upper())

    return {
        "tipo": tipo.upper(),
        "strike": op["strike"],
        "preco": op["preco"],
        "delta_mercado": op.get("delta"),
        "negocios": op.get("negocios", 0),
        "financeiro": op.get("financeiro"),
        "vencimento": exp["vencimento"],
        "dias": exp["dias"],
        "semanal": exp["semanal"],
        "data": cad.get("data"),
        "spot_mercado": ref,
        "iv": iv,
    }


def tabela(exp: dict, spot: float, largura: float = 0.10) -> list[dict]:
    """Linhas CALL/PUT por strike em torno do preço, para exibir o book."""
    if not exp or not spot:
        return []

    def _perto(lista):
        return {o["strike"]: o for o in lista if abs(o["strike"] / spot - 1) <= largura}

    calls, puts = _perto(exp.get("calls") or []), _perto(exp.get("puts") or [])
    linhas = []
    for strike in sorted(set(calls) | set(puts)):
        c, p = calls.get(strike), puts.get(strike)
        linhas.append(
            {
                "Strike": strike,
                "CALL R$": c["preco"] if c else None,
                "CALL Δ": c["delta"] if c else None,
                "PUT R$": p["preco"] if p else None,
                "PUT Δ": p["delta"] if p else None,
                "Negócios": max(
                    (c["negocios"] if c else 0), (p["negocios"] if p else 0)
                ),
            }
        )
    return linhas
