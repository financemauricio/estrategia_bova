"""Tests for implied volatility and real-premium evaluation (pure math)."""

import pytest

from modulos.bs import preco_call_bs, preco_put_bs, vol_implicita
from modulos.estrategia import avaliar_premio_real


def test_vol_implicita_recupera_a_vol_usada_no_preco() -> None:
    S, K, T, r, sigma = 63.90, 64.0, 30 / 252, 0.1375, 0.28
    premio = preco_put_bs(S, K, T, r, sigma)
    iv = vol_implicita(premio, S, K, T, r, "PUT")
    assert iv is not None
    assert iv == pytest.approx(sigma, abs=0.005)


def test_vol_implicita_call() -> None:
    S, K, T, r, sigma = 203.5, 209.61, 30 / 252, 0.1375, 0.22
    premio = preco_call_bs(S, K, T, r, sigma)
    iv = vol_implicita(premio, S, K, T, r, "CALL")
    assert iv is not None and iv == pytest.approx(sigma, abs=0.005)


def test_vol_implicita_premio_impossivel() -> None:
    # Prêmio acima de 300 % de vol não é recuperável
    assert vol_implicita(999.0, 63.9, 64.0, 30 / 252, 0.1375, "PUT") is None


def test_premio_real_marca_aprovado() -> None:
    dados = {"preco": 63.90, "ma_decisao": 72.0, "variacao_pct": -0.01, "vol": 0.19, "hist": None}
    av = avaliar_premio_real(dados, "PUT", 64.0, 2.00, selic=0.1375, dias=30)
    assert av["iv"] == pytest.approx(0.28, abs=0.01)
    assert av["premio_ok"] is True
    assert av["ret_anual_pct"] > 20


def test_premio_real_reprova_premio_magro() -> None:
    dados = {"preco": 63.90, "ma_decisao": 72.0, "variacao_pct": -0.01, "vol": 0.19, "hist": None}
    av = avaliar_premio_real(dados, "PUT", 60.0, 0.10, selic=0.1375, dias=30)
    assert av["premio_ok"] is False
