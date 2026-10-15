from modulos.opcoes_b3 import delta_put, filtrar_puts_regra, strike_para_delta


def _cadeia() -> list:
    return [
        {"codigo": "BOVAW190", "tipo": "PUT", "strike": 203.65, "bid": 3.93, "ask": 4.0, "volume": 100},
        {"codigo": "BOVAW185", "tipo": "PUT", "strike": 197.54, "bid": 1.86, "ask": 1.9, "volume": 80},
        {"codigo": "BOVAW180", "tipo": "PUT", "strike": 193.47, "bid": 1.02, "ask": 1.1, "volume": 50},
        {"codigo": "BOVAW175", "tipo": "PUT", "strike": 189.39, "bid": 0.51, "ask": 0.6, "volume": 10},
        {"codigo": "BOVAA210", "tipo": "CALL", "strike": 210.0, "bid": 2.0, "ask": 2.1, "volume": 60},
    ]


def test_delta_put_atm_maior_que_otm() -> None:
    d_atm = delta_put(203.65, 203.65, 30, 0.1075, 0.184)
    d_otm = delta_put(203.65, 193.47, 30, 0.1075, 0.184)
    assert d_atm is not None and d_otm is not None
    assert abs(d_atm) > abs(d_otm)  # ATM tem mais chance de exercício
    assert -0.5 < d_atm < -0.3
    assert -0.2 < d_otm < -0.1


def test_delta_put_invalido_retorna_none() -> None:
    assert delta_put(0, 100, 30, 0.1, 0.2) is None
    assert delta_put(100, 100, 0, 0.1, 0.2) is None


def test_filtrar_puts_regra_marca_candidata() -> None:
    rows = filtrar_puts_regra(_cadeia(), 203.65, 30, 0.1075, 0.184)
    por_cod = {r["codigo"]: r for r in rows}
    # -3% (delta ~-0.24, bid 1.86): dentro da regra
    assert por_cod["BOVAW185"]["candidata"] is True
    # ATM tem delta fora da banda; -7% tem bid abaixo do mínimo
    assert por_cod["BOVAW190"]["candidata"] is False
    assert por_cod["BOVAW175"]["candidata"] is False
    # CALLs nunca entram na regra de PUT
    assert all(r["tipo"] == "PUT" for r in rows)
    # candidata vem primeiro
    assert rows[0]["candidata"] is True


def test_strike_para_delta_acerta_alvo() -> None:
    k = strike_para_delta(203.65, -0.25, 30, 0.1075, 0.184)
    assert k is not None
    d = delta_put(203.65, k, 30, 0.1075, 0.184)
    assert d is not None and abs(d + 0.25) < 0.01
    assert 190 < k < 203.65
