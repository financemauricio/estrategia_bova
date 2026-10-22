"""Wheel rule engine — asset-agnostic, no portfolio data required.

For each asset it answers one question:

    "Vender PUT ou CALL hoje? Em que strike? O prêmio paga o risco?"

Rules
-----
1. Bias: spot below MA{MA_PERIODO} → PUT; above → CALL.
2. Modo renda (padrão): PUT delta ≈ -0.15; CALL delta ≈ +0.15.
   Longe do dinheiro, prêmio menor, pouca chance de exercício.
3. Modo esticado (exceção): quando o ativo sobe muito (2 de 3 critérios:
   distância ≥ 8 % acima da MA50, RSI ≥ 70, ganho de 5 dias ≥ 5 %), a CALL
   vai para +3 % OTM. Prêmio maior; se exercido, vende a um preço esticado.
4. Premium floor: modo renda 0.4 % do spot; modo esticado 1.0 %.
5. Priority: a strong daily move in the bias direction (≤ -1.5 % / ≥ +2 %).
"""

from __future__ import annotations

import math

from config import (
    CALL_STRIKE_OTM_ESTICADO_PCT,
    DELTA_CALL_RENDA,
    DELTA_PUT_RENDA,
    DIST_MA_ESTICADO_PCT,
    ESTICADO_MIN_CRITERIOS,
    GANHO_5D_ESTICADO_PCT,
    LIMIAR_ALTA_CALL,
    LIMIAR_QUEDA_PUT,
    MA_PERIODO,
    PREMIO_MIN_ESTICADO_PCT,
    PREMIO_MIN_RENDA_PCT,
    RSI_ESTICADO,
)


def premio_minimo(preco: float, pct: float = PREMIO_MIN_RENDA_PCT) -> float:
    """Minimum premium per share for a given spot (rounded to cents)."""
    return round(preco * pct, 2)


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def detectar_esticado(
    dados_ativo: dict,
    preco: float | None,
    ma: float | None,
) -> tuple[bool, dict]:
    """Return ``(is_stretched, details)`` using the three objective triggers.

    The mode is an exception, not the default: it needs at least
    ``ESTICADO_MIN_CRITERIOS`` of the three price/momentum criteria.
    """
    dist = (preco - ma) / ma if (preco and ma and ma > 0) else None
    rsi = dados_ativo.get("rsi")
    ret5 = dados_ativo.get("retorno_5d")

    criterios = {
        "dist": bool(dist is not None and dist >= DIST_MA_ESTICADO_PCT),
        "rsi": bool(rsi is not None and rsi >= RSI_ESTICADO),
        "ret5": bool(ret5 is not None and ret5 >= GANHO_5D_ESTICADO_PCT),
    }
    ativos = sum(criterios.values())
    return ativos >= ESTICADO_MIN_CRITERIOS, {
        "dist": dist,
        "rsi": rsi,
        "retorno_5d": ret5,
        "criterios": criterios,
        "ativos": ativos,
    }


def descrever_gatilhos(gatilhos: dict) -> str:
    """Human-readable trigger values, e.g. ``dist. MA50 +9.1 % · RSI 72 · 5d +6.0 %``."""
    if not gatilhos:
        return "sem dados de gatilho"
    partes = []
    if gatilhos.get("dist") is not None:
        partes.append(f"dist. MA50 {gatilhos['dist'] * 100:+.1f} %")
    if gatilhos.get("rsi") is not None:
        partes.append(f"RSI {gatilhos['rsi']:.0f}")
    if gatilhos.get("retorno_5d") is not None:
        partes.append(f"5d {gatilhos['retorno_5d'] * 100:+.1f} %")
    return " · ".join(partes) if partes else "sem dados de gatilho"


def avaliar_ativo(
    nome: str,
    dados_ativo: dict,
    selic: float,
    dias: int,
    premio_min_pct: float | None = None,
    delta_put: float = DELTA_PUT_RENDA,
    delta_call: float = DELTA_CALL_RENDA,
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
    premio_min_pct : float | None
        Optional override. When None, uses the mode floor (0.4 % renda,
        1.0 % esticado).
    delta_put, delta_call : float
        Target deltas for the base (renda) mode.

    Returns
    -------
    dict
        acao, vies, modo, gatilhos, strike_sugerido, premio_teorico,
        premio_min, premio_ok, prob_exercicio, prioridade, passos, mensagem.
    """
    from modulos import bs, opcoes_b3

    preco = dados_ativo.get("preco")
    ma = dados_ativo.get("ma_decisao")
    variacao = dados_ativo.get("variacao_pct", 0.0)
    vol = dados_ativo.get("vol")
    rsi = dados_ativo.get("rsi")
    ret5 = dados_ativo.get("retorno_5d")

    base = {
        "ativo": nome,
        "preco": preco,
        "ma_decisao": ma,
        "variacao_pct": variacao,
        "vol": vol,
        "rsi": rsi,
        "retorno_5d": ret5,
        "dias": dias,
        "selic": selic,
    }

    # Step 1 — bias
    if not preco or not ma:
        return {
            **base,
            "acao": "AGUARDAR",
            "vies": "INDEFINIDO",
            "modo": "—",
            "gatilhos": {},
            "strike_sugerido": None,
            "premio_teorico": None,
            "premio_min": 0.0,
            "premio_min_pct": PREMIO_MIN_RENDA_PCT,
            "delta_alvo": None,
            "prob_exercicio": None,
            "prioridade": False,
            "premio_ok": False,
            "passos": [{"ok": False, "texto": "Dados de mercado insuficientes."}],
            "mensagem": "Sem preço ou média móvel — aguarde a próxima atualização.",
        }

    acima = preco > ma
    vies = "CALL" if acima else "PUT"
    distancia = (preco - ma) / ma

    # Step 2 — mode (only the CALL side has an aggressive mode)
    esticado, gatilhos = (False, {})
    if vies == "CALL":
        esticado, gatilhos = detectar_esticado(dados_ativo, preco, ma)
    modo = "ESTICADO" if esticado else "RENDA"
    if premio_min_pct is None:
        premio_min_pct = (
            PREMIO_MIN_ESTICADO_PCT if modo == "ESTICADO" else PREMIO_MIN_RENDA_PCT
        )

    # Step 3 — strike and premium
    strike = None
    premio = None
    prob = None
    delta_alvo: float | None = None
    if vol and vol > 0:
        T = max(dias, 1) / 252
        if vies == "PUT":
            delta_alvo = delta_put
            strike = opcoes_b3.strike_para_delta(preco, delta_put, dias, selic, vol)
            if strike:
                premio = bs.preco_put_bs(preco, strike, T, selic, vol)
                d1 = (math.log(preco / strike) + (selic + 0.5 * vol**2) * T) / (vol * math.sqrt(T))
                d2 = d1 - vol * math.sqrt(T)
                prob = 1.0 - _norm_cdf(d2)
        elif modo == "ESTICADO":
            # Regra antiga: strike 3 % acima do preço. Aqui o objetivo é
            # colher prêmio alto e, se exercido, vender num preço esticado.
            strike = round(preco * (1 + CALL_STRIKE_OTM_ESTICADO_PCT), 2)
            premio = bs.preco_call_bs(preco, strike, T, selic, vol)
            d1 = (math.log(preco / strike) + (selic + 0.5 * vol**2) * T) / (vol * math.sqrt(T))
            d2 = d1 - vol * math.sqrt(T)
            prob = _norm_cdf(d2)
        else:
            delta_alvo = delta_call
            strike = opcoes_b3.strike_para_delta_call(preco, delta_call, dias, selic, vol)
            if strike:
                premio = bs.preco_call_bs(preco, strike, T, selic, vol)
                d1 = (math.log(preco / strike) + (selic + 0.5 * vol**2) * T) / (vol * math.sqrt(T))
                d2 = d1 - vol * math.sqrt(T)
                prob = _norm_cdf(d2)

    premio_min = premio_minimo(preco, premio_min_pct) if preco else 0.0
    premio_ok = bool(premio and premio >= premio_min)

    # Step 4 — priority from the daily move
    queda_forte = variacao <= LIMIAR_QUEDA_PUT
    alta_forte = variacao >= LIMIAR_ALTA_CALL
    prioridade = (vies == "PUT" and queda_forte) or (vies == "CALL" and alta_forte)

    if not premio_ok:
        acao = "AGUARDAR"
        mensagem = (
            f"Prêmio teórico {f'R$ {premio:.2f}' if premio else 'indisponível'} "
            f"abaixo do mínimo R$ {premio_min:.2f} "
            f"({premio_min_pct*100:.1f} % do preço, modo {modo.lower()}) — "
            "ficar de fora também é posição."
        )
    else:
        acao = f"VENDER {vies}"
        if vies == "PUT":
            mensagem = (
                f"Vender PUT com strike R$ {strike:.2f} — prêmio teórico "
                f"R$ {premio:.2f} ({prob*100:.0f} % de chance de exercício). "
                f"Modo renda: delta {delta_put:.2f}, longe do dinheiro."
            )
        elif modo == "ESTICADO":
            mensagem = (
                f"Vender CALL coberta a +{CALL_STRIKE_OTM_ESTICADO_PCT*100:.0f} % OTM "
                f"(strike R$ {strike:.2f}) — modo esticado "
                f"({gatilhos.get('ativos', 0)}/3: {descrever_gatilhos(gatilhos)}). "
                f"Prêmio teórico R$ {premio:.2f} "
                f"({prob*100:.0f} % de chance de exercício). "
                "Se exercido, você vende a um preço esticado."
            )
        else:
            mensagem = (
                f"Vender CALL coberta com strike R$ {strike:.2f} — prêmio teórico "
                f"R$ {premio:.2f} ({prob*100:.0f} % de chance de exercício). "
                f"Modo renda: delta {delta_call:+.2f}, longe do dinheiro."
            )
        if prioridade:
            mensagem += " PRIORIDADE MÁXIMA — movimento forte no dia."

    if vies == "PUT":
        modo_texto = (
            f"Renda — PUT com delta {delta_put:.2f} "
            f"(≈{abs(delta_put)*100:.0f} % de chance por ciclo)."
        )
    elif modo == "ESTICADO":
        modo_texto = (
            f"Esticado — {gatilhos.get('ativos', 0)}/3 critérios: "
            f"{descrever_gatilhos(gatilhos)}. CALL a "
            f"+{CALL_STRIKE_OTM_ESTICADO_PCT*100:.0f} % OTM."
        )
    else:
        modo_texto = (
            f"Renda — CALL com delta {delta_call:.2f} "
            f"(≈{delta_call*100:.0f} % de chance por ciclo)."
        )

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
            "ok": True,
            "titulo": f"Modo {modo.lower()}",
            "texto": modo_texto,
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
        "modo": modo,
        "gatilhos": gatilhos,
        "strike_sugerido": strike,
        "premio_teorico": round(premio, 2) if premio else None,
        "premio_min": premio_min,
        "premio_min_pct": premio_min_pct,
        "delta_alvo": delta_alvo,
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
    premio_min_pct: float = PREMIO_MIN_RENDA_PCT,
    delta_put: float = DELTA_PUT_RENDA,
    delta_call: float = DELTA_CALL_RENDA,
) -> dict:
    """Evaluate the premium the user actually sees in the broker.

    This is the honest path: theoretical Black-Scholes with historical
    volatility does not match Brazilian market implied volatility, so the
    real bid is what decides. Nothing is stored — it is a live calculation.
    """
    from modulos import bs, opcoes_b3

    tipo = tipo.upper()
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
    if iv:
        if tipo == "PUT":
            strike_alvo = opcoes_b3.strike_para_delta(preco, delta_put, dias, selic, iv)
        else:
            strike_alvo = opcoes_b3.strike_para_delta_call(preco, delta_call, dias, selic, iv)

    return {
        "iv": iv,
        "prob_exercicio": prob,
        "delta": delta,
        "delta_alvo": delta_put if tipo == "PUT" else delta_call,
        "premio_min": premio_min,
        "premio_ok": premio_real >= premio_min,
        "ret_ciclo_pct": ret_ciclo,
        "ret_anual_pct": ret_anual,
        "strike_alvo": strike_alvo,
    }
