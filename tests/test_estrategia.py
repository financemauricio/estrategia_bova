"""Tests for the per-asset wheel rule (pure logic, no network)."""

from modulos.estrategia import avaliar_ativo, detectar_esticado


def _dados(
    preco: float,
    ma: float,
    var: float,
    vol: float = 0.30,
    rsi: float | None = None,
    ret5: float | None = None,
) -> dict:
    return {
        "preco": preco,
        "ma_decisao": ma,
        "variacao_pct": var,
        "vol": vol,
        "rsi": rsi,
        "retorno_5d": ret5,
        "hist": None,
    }


def test_abaixo_da_ma_sugere_put() -> None:
    r = avaliar_ativo("VALE3", _dados(60.0, 65.0, -0.02), selic=0.1075, dias=30)
    assert r["vies"] == "PUT"
    assert r["acao"] == "VENDER PUT"
    assert r["modo"] == "RENDA"
    assert r["strike_sugerido"] is not None and r["strike_sugerido"] < 60.0
    assert r["prioridade"] is True  # queda >= 1.5 %


def test_acima_da_ma_sugere_call_renda_longe_do_dinheiro() -> None:
    r = avaliar_ativo("ITSA4", _dados(35.0, 32.0, 0.005), selic=0.1075, dias=30)
    assert r["vies"] == "CALL"
    assert r["modo"] == "RENDA"
    assert r["prioridade"] is False
    # delta +0.15 fica mais longe que o antigo +3 % OTM
    assert r["strike_sugerido"] > round(35.0 * 1.03, 2)


def test_call_esticada_usa_3_por_cento_otm() -> None:
    # 9.4 % acima da MA50 + RSI 72 + 5d +6 % = 3/3 critérios
    r = avaliar_ativo(
        "BOVA11",
        _dados(35.0, 32.0, 0.005, rsi=72.0, ret5=0.06),
        selic=0.1075,
        dias=30,
    )
    assert r["vies"] == "CALL"
    assert r["modo"] == "ESTICADO"
    assert r["strike_sugerido"] == round(35.0 * 1.03, 2)
    assert r["gatilhos"]["ativos"] == 3


def test_esticado_exige_dois_de_tres_criterios() -> None:
    ok, det = detectar_esticado(
        {"rsi": 72.0, "retorno_5d": 0.01}, preco=32.0, ma=32.0
    )
    assert ok is False and det["ativos"] == 1  # só RSI
    ok, det = detectar_esticado(
        {"rsi": 72.0, "retorno_5d": 0.06}, preco=32.0, ma=32.0
    )
    assert ok is True and det["ativos"] == 2


def test_premio_abaixo_do_minimo_aguarda() -> None:
    # Volatilidade mínima → prêmio teórico irrelevante
    r = avaliar_ativo("PRIO3", _dados(40.0, 45.0, 0.0, vol=0.001), selic=0.1075, dias=30)
    assert r["acao"] == "AGUARDAR"
    assert r["premio_ok"] is False


def test_premio_minimo_muda_com_o_modo() -> None:
    renda = avaliar_ativo("BOVA11", _dados(203.5, 210.0, 0.0), selic=0.15, dias=30)
    esticado = avaliar_ativo(
        "BOVA11",
        _dados(203.5, 185.0, 0.0, rsi=75.0, ret5=0.08),
        selic=0.15,
        dias=30,
    )
    assert renda["modo"] == "RENDA"
    assert esticado["modo"] == "ESTICADO"
    assert renda["premio_min_pct"] < esticado["premio_min_pct"]


def test_sem_dados_aguarda() -> None:
    r = avaliar_ativo("BOVA11", {"preco": None, "ma_decisao": None}, selic=0.1075, dias=30)
    assert r["acao"] == "AGUARDAR"
    assert r["vies"] == "INDEFINIDO"
