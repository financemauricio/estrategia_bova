import datetime as dt

import pandas as pd

from modulos.cotacoes import descricao_cotacao, hora_curta
from modulos.mercado import _atualizar_ultima_barra, corrigir_ultima_barra


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


def _hist_recente() -> pd.DataFrame:
    hoje = pd.Timestamp.now().normalize()
    ontem = hoje - pd.Timedelta(days=1)
    rows = [
        {"Open": 204.0, "High": 205.0, "Low": 203.0, "Close": 204.5},
        {"Open": 203.0, "High": 204.0, "Low": 202.0, "Close": 203.0},
    ]
    return pd.DataFrame(rows, index=pd.DatetimeIndex([ontem, hoje]))


def test_consenso_atualiza_ultima_barra() -> None:
    h = _atualizar_ultima_barra(_hist_recente(), 203.9)
    assert float(h["Close"].iloc[-1]) == 203.9
    assert float(h["High"].iloc[-1]) >= 203.9


def test_consenso_absurdo_nao_toca_na_barra() -> None:
    h = _atualizar_ultima_barra(_hist_recente(), 50.0)  # >10 % de distância
    assert float(h["Close"].iloc[-1]) == 203.0


def test_consenso_nao_altera_barra_antiga() -> None:
    antiga = _hist_recente()
    antiga.index = antiga.index - pd.Timedelta(days=30)
    h = _atualizar_ultima_barra(antiga, 203.9)
    assert float(h["Close"].iloc[-1]) == 203.0


def test_descricao_mostra_fonte_e_hora_da_sessao() -> None:
    hora = dt.datetime(2026, 10, 21, 17, 19)
    cot = {
        "preco": 203.5,
        "hora": hora,
        "confianca": "alta",
        "dispersao_pct": 0.0,
        "fontes": [{"fonte": "Yahoo"}, {"fonte": "brapi"}],
    }
    texto = descricao_cotacao(cot)
    assert "17:19" in texto and "concordam" in texto


def test_descricao_fora_da_sessao_vira_fechamento() -> None:
    cot = {
        "preco": 203.5,
        "hora": dt.datetime(2026, 10, 21, 22, 24),
        "confianca": "unica",
        "dispersao_pct": 0.0,
        "fontes": [{"fonte": "brapi"}],
    }
    assert descricao_cotacao(cot).startswith("fechamento de 21/10")
    assert hora_curta(cot) == "fech. 21/10"
