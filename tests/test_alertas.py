"""Tests for the e-mail notifier selection and message helpers (no network)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from modulos import alertas
from notificar import (
    carregar_estado,
    montar_assunto,
    salvar_estado,
    selecionar_alertas,
)


def _r(
    ativo: str = "BOVA11",
    variacao: float = 0.021,
    vies: str = "CALL",
    acao: str = "VENDER CALL",
    **extra,
) -> dict:
    base = {
        "ativo": ativo,
        "preco": 100.0,
        "variacao_pct": variacao,
        "vies": vies,
        "acao": acao,
        "modo": "RENDA",
        "strike_sugerido": 110.0,
        "premio_teorico": 1.0,
        "premio_min": 0.4,
        "premio_min_pct": 0.004,
        "prob_exercicio": 0.15,
        "prioridade": False,
        "gatilhos": {},
        "cotacao": {"confianca": "alta", "possivel_atraso": False},
    }
    base.update(extra)
    return base


def test_seleciona_alta_e_queda_acima_do_limiar() -> None:
    estado = {"data": "2026-10-22", "enviados": {}}
    resultados = [
        _r("BOVA11", 0.021),
        _r("VALE3", -0.020, vies="PUT", acao="VENDER PUT"),
        _r("ITSA4", 0.019),
    ]
    novos = selecionar_alertas(resultados, estado, 0.02)
    assert [n["chave"] for n in novos] == [
        "BOVA11:ALTA:VENDER CALL:RENDA",
        "VALE3:QUEDA:VENDER PUT:RENDA",
    ]


def test_nao_repete_a_mesma_direcao_no_dia() -> None:
    estado = {
        "data": "2026-10-22",
        "enviados": {"BOVA11:ALTA:VENDER CALL:RENDA": "x"},
    }
    resultados = [_r("BOVA11", 0.03)]
    assert selecionar_alertas(resultados, estado, 0.02) == []


def test_permite_queda_depois_de_alta() -> None:
    estado = {
        "data": "2026-10-22",
        "enviados": {"BOVA11:ALTA:VENDER CALL:RENDA": "x"},
    }
    resultados = [_r("BOVA11", -0.025)]
    novos = selecionar_alertas(resultados, estado, 0.02)
    assert len(novos) == 1
    assert novos[0]["chave"] == "BOVA11:QUEDA:VENDER CALL:RENDA"


def test_permite_novo_alerta_quando_acao_ou_modo_muda() -> None:
    estado = {
        "data": "2026-10-22",
        "enviados": {"BOVA11:ALTA:VENDER CALL:RENDA": "x"},
    }
    resultados = [
        _r("BOVA11", 0.03, modo="ESTICADO"),
    ]
    novos = selecionar_alertas(resultados, estado, 0.02)
    assert len(novos) == 1
    assert novos[0]["chave"] == "BOVA11:ALTA:VENDER CALL:ESTICADO"


def test_nao_manda_downgrade_para_aguardar_no_mesmo_dia() -> None:
    estado = {
        "data": "2026-10-22",
        "enviados": {"VALE3:QUEDA:VENDER PUT:RENDA": "x"},
    }
    resultados = [_r("VALE3", -0.03, vies="PUT", acao="AGUARDAR")]
    assert selecionar_alertas(resultados, estado, 0.02) == []


def test_ignora_cotacao_atrasada_ou_sem_dados() -> None:
    estado = {"data": "2026-10-22", "enviados": {}}
    resultados = [
        _r("BOVA11", 0.03, cotacao={"confianca": "alta", "possivel_atraso": True}),
        _r("VALE3", -0.03, vies="PUT", cotacao={"confianca": "sem_dados", "possivel_atraso": False}),
    ]
    assert selecionar_alertas(resultados, estado, 0.02) == []


def test_estado_reseta_em_outro_dia() -> None:
    with tempfile.TemporaryDirectory() as d:
        caminho = Path(d) / "estado.json"
        caminho.write_text(
            json.dumps({"data": "2026-10-21", "enviados": {"BOVA11:ALTA": "x"}}),
            encoding="utf-8",
        )
        estado = carregar_estado(caminho, "2026-10-22")
        assert estado == {"data": "2026-10-22", "enviados": {}}


def test_salvar_e_carregar_estado() -> None:
    with tempfile.TemporaryDirectory() as d:
        caminho = Path(d) / "sub" / "estado.json"
        estado = {"data": "2026-10-22", "enviados": {"BOVA11:ALTA": "agora"}}
        salvar_estado(caminho, estado)
        assert carregar_estado(caminho, "2026-10-22") == estado


def test_assunto_um_ativo() -> None:
    item = {"ativo": "BOVA11", "variacao_pct": 0.0234, "acao": "VENDER CALL"}
    assert montar_assunto([item]) == "[Sinais] ⚡ BOVA11 +2,34 % — alta · VENDER CALL"


def test_assunto_varios_ativos() -> None:
    itens = [
        {"ativo": "BOVA11", "variacao_pct": 0.0234, "acao": "VENDER CALL"},
        {"ativo": "VALE3", "variacao_pct": -0.021, "acao": "VENDER PUT"},
    ]
    assunto = montar_assunto(itens)
    assert "2 movimentos fortes" in assunto
    assert "BOVA11" in assunto and "VALE3" in assunto


def test_enviar_email_monta_e_dispara_smtp() -> None:
    fake = MagicMock()
    fake.__enter__.return_value = fake
    config = {
        "EMAIL_REMETENTE": "remetente@exemplo.com",
        "EMAIL_SENHA": "abcd efgh ijkl mnop",
        "EMAIL_DESTINATARIO": "destino@exemplo.com",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "APP_URL": "",
    }
    with patch.dict(alertas._ENV, config), patch("smtplib.SMTP", return_value=fake):
        ok, erro = alertas.enviar_email("Assunto", "<b>oi</b>", "oi")

    assert ok is True and erro == ""
    fake.starttls.assert_called_once()
    fake.login.assert_called_once_with("remetente@exemplo.com", "abcdefghijklmnop")
    fake.sendmail.assert_called_once()


def test_email_html_tem_aviso_de_call_coberta() -> None:
    item = {
        "ativo": "BOVA11",
        "preco": 100.0,
        "variacao_pct": 0.021,
        "vies": "CALL",
        "modo": "RENDA",
        "acao": "VENDER CALL",
        "strike": 110.0,
        "premio_teorico": 1.0,
        "premio_real": 0.9,
        "premio_real_pct": 0.009,
        "strike_real": 110.0,
        "data_real": "21/10",
        "prob": 0.15,
        "motivo": "teste",
    }
    html_body, texto = alertas.montar_email_movimentos([item])
    assert "BOVA11" in html_body
    assert "coberta" in html_body.lower()
    assert "BOVA11" in texto
