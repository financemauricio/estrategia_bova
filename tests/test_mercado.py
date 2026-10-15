import pandas as pd

from modulos.mercado import corrigir_ultima_barra


def _hist(corrompida: bool = True) -> pd.DataFrame:
    rows = [
        {"Open": 204.0, "High": 205.0, "Low": 203.0, "Close": 204.5},
        {"Open": 0.0 if corrompida else 203.9, "High": 0.0 if corrompida else 204.8,
         "Low": 0.0 if corrompida else 202.8, "Close": 203.65},
    ]
    return pd.DataFrame(rows, index=pd.to_datetime(["2026-10-13", "2026-10-14"]))


def test_barra_completa_nao_muda() -> None:
    h, fonte = corrigir_ultima_barra(_hist(False), 203.65)
    assert fonte == "yfinance" and len(h) == 2


def test_barra_corrompida_usa_brapi() -> None:
    h, fonte = corrigir_ultima_barra(_hist(True), 203.65)
    assert fonte == "brapi"
    assert float(h["Close"].iloc[-1]) == 203.65
    assert float(h["Open"].iloc[-1]) == 203.65  # sem vela zerada no gráfico


def test_brapi_absurdo_descarta_barra() -> None:
    h, fonte = corrigir_ultima_barra(_hist(True), 500.0)  # >5% do anterior
    assert fonte == "yfinance*" and len(h) == 1


def test_sem_brapi_descarta_barra() -> None:
    h, fonte = corrigir_ultima_barra(_hist(True), None)
    assert fonte == "yfinance*" and len(h) == 1
