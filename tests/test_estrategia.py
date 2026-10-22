"""Tests for the per-asset wheel rule (pure logic, no network)."""

from modulos.estrategia import avaliar_ativo


def _dados(preco: float, ma: float, var: float, vol: float = 0.30) -> dict:
    return {
        "preco": preco,
        "ma_decisao": ma,
        "variacao_pct": var,
        "vol": vol,
        "hist": None,
    }


def test_abaixo_da_ma_sugere_put() -> None:
    r = avaliar_ativo("VALE3", _dados(60.0, 65.0, -0.02), selic=0.1075, dias=30)
    assert r["vies"] == "PUT"
    assert r["acao"] == "VENDER PUT"
    assert r["strike_sugerido"] is not None and r["strike_sugerido"] < 60.0
    assert r["prioridade"] is True  # queda >= 1.5 %


def test_acima_da_ma_sugere_call_otm() -> None:
    r = avaliar_ativo("ITUB4", _dados(35.0, 32.0, 0.005), selic=0.1075, dias=30)
    assert r["vies"] == "CALL"
    assert r["strike_sugerido"] == round(35.0 * 1.03, 2)
    assert r["prioridade"] is False


def test_premio_abaixo_do_minimo_aguarda() -> None:
    # Volatilidade mínima → prêmio teórico irrelevante
    r = avaliar_ativo("PRIO3", _dados(40.0, 45.0, 0.0, vol=0.001), selic=0.1075, dias=30)
    assert r["acao"] == "AGUARDAR"
    assert r["premio_ok"] is False


def test_sem_dados_aguarda() -> None:
    r = avaliar_ativo("BOVA11", {"preco": None, "ma_decisao": None}, selic=0.1075, dias=30)
    assert r["acao"] == "AGUARDAR"
    assert r["vies"] == "INDEFINIDO"
