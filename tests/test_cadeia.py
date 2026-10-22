"""Testes da cadeia real de opções (parse e escolha de série)."""

from __future__ import annotations

from modulos import cadeia

_COLUNAS = ["s", "p", "d", "i", "n", "f", "h"]

_PAYLOAD = {
    "requests": [
        {
            "type": "LastQuotesInfo",
            "results": {"dateLastQuotesInDB": "2026-10-21"},
        },
        {
            "type": "OptionsChain",
            "results": {
                "columns": [{"id": c} for c in _COLUNAS],
                "underlying_asset": {
                    "p": 203.5,
                    "evl": 0.256,
                    "iv_c": 0.413,
                    "iv_p": 0.457,
                },
                "expirations": [
                    {
                        "dt": "2026-10-23",
                        "dc": 1,
                        "w": "W4",
                        "calls": [
                            [210.0, 0.21, 0.1068, 0.2774, 350, 1.0, "2026-10-21"],
                            [205.0, None, 0.30, 0.28, 0, None, None],
                        ],
                        "puts": [
                            [200.0, 1.00, -0.2669, 0.3261, 1101, 1.0, "2026-10-21"],
                        ],
                    },
                    {
                        "dt": "2026-11-19",
                        "dc": 28,
                        "w": "",
                        "calls": [
                            [209.0, 7.72, 0.4644, 0.4039, 7973, 1.0, "2026-10-21"],
                            [210.0, 7.19, 0.4465, 0.3987, 11746, 1.0, "2026-10-21"],
                        ],
                        "puts": [
                            [189.0, 4.71, -0.253, 0.5022, 224, 1.0, "2026-10-21"],
                        ],
                    },
                ],
            },
        },
    ]
}


def _cad() -> dict:
    return cadeia._parse(_PAYLOAD)


def test_parse_devolve_data_spot_e_vencimentos() -> None:
    cad = _cad()
    assert cad["ok"] is True
    assert cad["data"] == "2026-10-21"
    assert cad["spot"] == 203.5
    assert len(cad["expiracoes"]) == 2
    assert cad["expiracoes"][0]["dias"] == 1
    assert cad["expiracoes"][1]["dias"] == 28


def test_parse_descarta_serie_sem_negocio() -> None:
    semanal = _cad()["expiracoes"][0]
    strikes = [o["strike"] for o in semanal["calls"]]
    assert 210.0 in strikes
    assert 205.0 not in strikes  # p = None


def test_vencimento_mais_proximo() -> None:
    cad = _cad()
    assert cadeia.vencimento_mais_proximo(cad, 30)["vencimento"] == "2026-11-19"
    assert cadeia.vencimento_mais_proximo(cad, 1)["vencimento"] == "2026-10-23"
    assert cadeia.vencimento_mais_proximo(cad, 8)["vencimento"] == "2026-10-23"


def test_call_mensal_vale_muito_mais_que_o_semanal() -> None:
    cad = _cad()
    mensal = cadeia.resumo_premio(cad, "CALL", 203.5, 30, 0.1075)
    semanal = cadeia.resumo_premio(cad, "CALL", 203.5, 1, 0.1075)
    assert mensal is not None and semanal is not None
    assert mensal["strike"] == 210.0 and mensal["preco"] == 7.19
    assert mensal["dias"] == 28 and mensal["vencimento"] == "2026-11-19"
    assert semanal["strike"] == 210.0 and semanal["preco"] == 0.21
    assert semanal["dias"] == 1
    assert mensal["iv"] is not None and 0.25 < mensal["iv"] < 0.45


def test_put_escolhida_pelo_delta_real() -> None:
    cad = _cad()
    r = cadeia.resumo_premio(cad, "PUT", 203.5, 30, 0.1075)
    assert r is not None
    assert r["strike"] == 189.0
    assert r["delta_mercado"] == -0.253


def test_tabela_monta_book_call_e_put() -> None:
    cad = _cad()
    exp = cadeia.vencimento_mais_proximo(cad, 30)
    linhas = cadeia.tabela(exp, 203.5)
    por_strike = {l["Strike"]: l for l in linhas}
    assert por_strike[210.0]["CALL R$"] == 7.19
    assert por_strike[189.0]["PUT R$"] == 4.71


def test_payload_sem_chain_nao_quebra() -> None:
    cad = cadeia._parse({"requests": []})
    assert cad["ok"] is False
    assert cadeia.resumo_premio(cad, "CALL", 203.5, 30, 0.1075) is None
