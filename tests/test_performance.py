from modulos.performance import _calcular_contribuicao_opcoes


def test_calcular_contribuicao_opcoes_soma_fluxos_de_caixa() -> None:
    caixa = [
        {"descricao": "Prêmio recebido — op#1 PUT", "valor": 100.0, "tipo": "ENTRADA"},
        {"descricao": "Recompra — op#1 PUT", "valor": 20.0, "tipo": "SAIDA"},
        {"descricao": "Exercício de PUT", "valor": 10.0, "tipo": "SAIDA"},
    ]

    resultado = _calcular_contribuicao_opcoes(caixa)

    assert resultado["premios"] == 100.0
    assert resultado["recompras"] == 20.0
    assert resultado["exercicios"] == -10.0
    assert resultado["liquido"] == 90.0
