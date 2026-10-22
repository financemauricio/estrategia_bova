"""Wheel rule engine — asset-agnostic, no portfolio data required.

For each asset it answers one question:

    "Vender PUT ou CALL hoje? Em que strike? O prêmio paga o risco?"

Rules
-----
1. Bias: spot below MA{MA_PERIODO} → PUT; above → CALL.
2. Strike: PUT at delta ≈ -0.25 (≈25 % exercise chance); CALL at +3 % OTM.
3. Premium floor: theoretical premium must reach PREMIO_MIN per share.
4. Priority: a strong daily move in the bias direction (≤ -1.5 % / ≥ +2 %).
"""

from __future__ import annotations

import math

from config import (
    CALL_STRIKE_OTM_PCT,
    DELTA_PUT_ALVO,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    PREMIO_MIN_PCT,
)


def premio_minimo(preco: float, pct: float = PREMIO_MIN_PCT) -> float:
    """Minimum premium per share for a given spot (rounded to cents)."""
    return round(preco * pct, 2)


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def avaliar_ativo(
    nome: str,
    dados_ativo: dict,
    selic: float,
    dias: int,
    premio_min_pct: float = PREMIO_MIN_PCT,
    delta_alvo: float = DELTA_PUT_ALVO,
) -> dict:
    """Run the wheel rule for one asset.

    Parameters
    ----------
    nome : str
        Display name, e.g. 'VALE3'.
    dados_ativo : dict
        One entry of ``mercado.buscar_dados_mercado()``.
    selic : float
        Annual risk-free rate as decimal (e.g. 0.1075).
    dias : int
        Days to the chosen expiry.
    premio_min_pct : float
        Minimum premium as a fraction of spot (default 0.6 %).
    delta_alvo : float
        Target PUT delta (negative).

    Returns
    -------
    dict
        acao, vies, strike_sugerido, premio_teorico, prob_exercicio,
        prioridade, premio_ok, passos (list of dicts), mensagem.
    """
    from modulos import bs, opcoes_b3

    preco = dados_ativo.get("preco")
    ma = dados_ativo.get("ma_decisao")
    variacao = dados_ativo.get("variacao_pct", 0.0)
    vol = dados_ativo.get("vol")

    base = {
        "ativo": nome,
        "preco": preco,
        "ma_decisao": ma,
        "variacao_pct": variacao,
        "vol": vol,
        "dias": dias,
        "selic": selic,
    }

    # Step 1 — bias
    if not preco or not ma:
        return {
            **base,
            "acao": "AGUARDAR",
            "vies": "INDEFINIDO",
            "strike_sugerido": None,
            "premio_teorico": None,
            "prob_exercicio": None,
            "prioridade": False,
            "premio_ok": False,
            "passos": [{"ok": False, "texto": "Dados de mercado insuficientes."}],
            "mensagem": "Sem preço ou média móvel — aguarde a próxima atualização.",
        }

    acima = preco > ma
    vies = "CALL" if acima else "PUT"
    distancia = (preco - ma) / ma

    # Step 2 — strike and premium
    strike = None
    premio = None
    prob = None
    if vol and vol > 0:
        T = max(dias, 1) / 252
        if vies == "PUT":
            strike = opcoes_b3.strike_para_delta(preco, delta_alvo, dias, selic, vol)
            if strike:
                premio = bs.preco_put_bs(preco, strike, T, selic, vol)
                d1 = (math.log(preco / strike) + (selic + 0.5 * vol**2) * T) / (vol * math.sqrt(T))
                d2 = d1 - vol * math.sqrt(T)
                prob = 1.0 - _norm_cdf(d2)
        else:
            strike = round(preco * (1 + CALL_STRIKE_OTM_PCT), 2)
            premio = bs.preco_call_bs(preco, strike, T, selic, vol)
            d1 = (math.log(preco / strike) + (selic + 0.5 * vol**2) * T) / (vol * math.sqrt(T))
            d2 = d1 - vol * math.sqrt(T)
            prob = _norm_cdf(d2)

    premio_min = premio_minimo(preco, premio_min_pct) if preco else 0.0
    premio_ok = bool(premio and premio >= premio_min)

    # Step 3 — priority from the daily move
    queda_forte = variacao <= LIMIAR_QUEDA_PUT
    alta_forte = variacao >= LIMIAR_ALTA_CALL
    prioridade = (vies == "PUT" and queda_forte) or (vies == "CALL" and alta_forte)

    if not premio_ok:
        acao = "AGUARDAR"
        mensagem = (
            f"Prêmio teórico {f'R$ {premio:.2f}' if premio else 'indisponível'} "
            f"abaixo do mínimo R$ {premio_min:.2f} — ficar de fora também é posição."
        )
    else:
        acao = f"VENDER {vies}"
        mensagem = (
            f"Vender {vies} {'ATM' if vies == 'PUT' else '+3 % OTM'} com strike "
            f"R$ {strike:.2f} — prêmio teórico R$ {premio:.2f} "
            f"({prob*100:.0f} % de chance de exercício)."
        )
        if prioridade:
            mensagem += " PRIORIDADE MÁXIMA — movimento forte no dia."

    passos = [
        {
            "ok": True,
            "titulo": f"{nome} vs MA{MA_PERIODO}",
            "texto": (
                f"Preço R$ {preco:.2f} {'acima' if acima else 'abaixo'} da média "
                f"({distancia*100:+.2f} %) → viés {vies}."
            ),
        },
        {
            "ok": strike is not None,
            "titulo": "Strike sugerido",
            "texto": f"R$ {strike:.2f}" if strike else "Indisponível (sem volatilidade).",
        },
        {
            "ok": premio_ok,
            "titulo": f"Prêmio mínimo R$ {premio_min:.2f} ({premio_min_pct*100:.1f} % do preço)",
            "texto": f"Teórico R$ {premio:.2f}" if premio else "Indisponível.",
        },
        {
            "ok": prioridade,
            "titulo": "Movimento do dia",
            "texto": f"{variacao*100:+.2f} %" + (" — movimento forte." if prioridade else " — sem gatilho."),
        },
    ]

    return {
        **base,
        "acao": acao,
        "vies": vies,
        "strike_sugerido": strike,
        "premio_teorico": round(premio, 2) if premio else None,
        "premio_min": premio_min,
        "prob_exercicio": prob,
        "prioridade": prioridade,
        "premio_ok": premio_ok,
        "passos": passos,
        "mensagem": mensagem,
    }


def avaliar_carteira(dados_mercado: dict, selic: float, dias: int) -> list[dict]:
    """Evaluate every monitored asset, returning one result dict per asset."""
    return [
        avaliar_ativo(nome, dados, selic, dias)
        for nome, dados in dados_mercado.items()
    ]


def avaliar_premio_real(
    dados_ativo: dict,
    tipo: str,
    strike: float,
    premio_real: float,
    selic: float,
    dias: int,
    premio_min_pct: float = PREMIO_MIN_PCT,
) -> dict:
    """Evaluate the premium the user actually sees in the broker.

    This is the honest path: theoretical Black-Scholes with historical
    volatility does not match Brazilian market implied volatility, so the
    real bid is what decides. Nothing is stored — it is a live calculation.
    """
    from modulos import bs, opcoes_b3

    preco = dados_ativo.get("preco") or 0.0
    T = max(dias, 1) / 252
    iv = bs.vol_implicita(premio_real, preco, strike, T, selic, tipo) if preco > 0 else None
    prob = None
    delta = None
    if iv:
        d1 = (math.log(preco / strike) + (selic + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)
        prob = (1.0 - _norm_cdf(d2)) if tipo == "PUT" else _norm_cdf(d2)
        delta = bs.delta_opcao(tipo, preco, strike, T, selic, iv)

    premio_min = premio_minimo(preco, premio_min_pct) if preco else 0.0
    ret_ciclo = (premio_real / strike * 100) if strike > 0 else None
    ret_anual = (ret_ciclo * 252 / max(dias, 1)) if ret_ciclo is not None else None

    # Strike that would give the target delta using the market's own IV
    strike_alvo = None
    if tipo == "PUT" and iv:
        strike_alvo = opcoes_b3.strike_para_delta(preco, DELTA_PUT_ALVO, dias, selic, iv)

    return {
        "iv": iv,
        "prob_exercicio": prob,
        "delta": delta,
        "premio_min": premio_min,
        "premio_ok": premio_real >= premio_min,
        "ret_ciclo_pct": ret_ciclo,
        "ret_anual_pct": ret_anual,
        "strike_alvo": strike_alvo,
    }
