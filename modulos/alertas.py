"""E-mail alert module — sends opportunity notifications via SMTP.

Credentials are read from Streamlit secrets (cloud) or .env (local).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st


def _get_cfg() -> dict[str, str]:
    """Return e-mail config from secrets or environment variables."""
    try:
        return {
            "remetente": st.secrets["EMAIL_REMETENTE"],
            "senha": st.secrets["EMAIL_SENHA"],
            "destinatario": st.secrets["EMAIL_DESTINATARIO"],
            "host": st.secrets["SMTP_HOST"],
            "port": st.secrets["SMTP_PORT"],
        }
    except Exception:
        from dotenv import load_dotenv
        load_dotenv()
        return {
            "remetente": os.getenv("EMAIL_REMETENTE", ""),
            "senha": os.getenv("EMAIL_SENHA", ""),
            "destinatario": os.getenv("EMAIL_DESTINATARIO", ""),
            "host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
            "port": os.getenv("SMTP_PORT", "587"),
        }


def _html_template(tipo: str, variacao_pct: float, preco: float, ma200: float | None) -> str:
    cor = "#e74c3c" if tipo == "PUT" else "#2ecc71"
    acao = "VENDER PUT ATM" if tipo == "PUT" else "VENDER CALL 3% OTM"
    motivo = (
        f"queda de {abs(variacao_pct)*100:.2f} % no dia"
        if tipo == "PUT"
        else f"alta de {variacao_pct*100:.2f} % no dia"
    )
    ma200_str = f"R$ {ma200:.2f}" if ma200 else "N/D"

    return f"""
    <html><body style="font-family:sans-serif;background:#0e1117;color:#fafafa;padding:24px">
      <div style="max-width:520px;margin:auto;background:#1a1d27;border-radius:8px;padding:24px">
        <h2 style="color:{cor};margin-top:0">⚡ Oportunidade de {tipo} — Prioridade Máxima</h2>
        <p>BOVA11 registrou <strong>{motivo}</strong>.</p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
          <tr><td style="padding:8px;border-bottom:1px solid #333">Preço atual</td>
              <td style="padding:8px;border-bottom:1px solid #333;text-align:right"><strong>R$ {preco:.2f}</strong></td></tr>
          <tr><td style="padding:8px;border-bottom:1px solid #333">Variação</td>
              <td style="padding:8px;border-bottom:1px solid #333;text-align:right;color:{cor}"><strong>{variacao_pct*100:+.2f} %</strong></td></tr>
          <tr><td style="padding:8px">MA 200</td>
              <td style="padding:8px;text-align:right">{ma200_str}</td></tr>
        </table>
        <div style="background:{cor};color:#000;padding:12px 20px;border-radius:6px;
                    text-align:center;font-weight:bold;font-size:1.1rem">
          {acao}
        </div>
        <p style="color:#888;font-size:0.85rem;margin-top:16px">
          Verifique liquidez e prêmio no Home Broker antes de operar.
        </p>
      </div>
    </body></html>
    """


def enviar_alerta(tipo: str, variacao_pct: float, preco: float, ma200: float | None) -> bool:
    """Send an opportunity alert e-mail.

    Parameters
    ----------
    tipo : str
        'PUT' or 'CALL'.
    variacao_pct : float
        Daily return fraction (e.g. -0.018).
    preco : float
        Current BOVA11 price.
    ma200 : float or None
        Current MA200 value.

    Returns
    -------
    bool
        True if sent successfully, False otherwise.
    """
    cfg = _get_cfg()
    if not cfg["remetente"] or not cfg["senha"]:
        return False

    sinal = "queda" if tipo == "PUT" else "alta"
    assunto = f"[ETF Estratégia] ⚡ Oportunidade de {tipo} — {sinal} de {abs(variacao_pct)*100:.1f}%"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = cfg["remetente"]
    msg["To"] = cfg["destinatario"]
    msg.attach(MIMEText(_html_template(tipo, variacao_pct, preco, ma200), "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls(context=context)
            server.login(cfg["remetente"], cfg["senha"])
            server.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        return True
    except Exception:
        return False


def verificar_e_alertar(dados_mercado: dict) -> str | None:
    """Check market data and send alert if thresholds are breached.

    Parameters
    ----------
    dados_mercado : dict
        Output from ``mercado.buscar_dados_mercado()``.

    Returns
    -------
    str or None
        'PUT', 'CALL', or None if no alert was sent.
    """
    from config import LIMIAR_QUEDA_PUT, LIMIAR_ALTA_CALL

    bova = dados_mercado.get("BOVA11", {})
    variacao = bova.get("variacao_pct", 0.0)
    preco = bova.get("preco", 0.0)
    ma200 = bova.get("ma200")

    if variacao <= LIMIAR_QUEDA_PUT:
        enviar_alerta("PUT", variacao, preco, ma200)
        return "PUT"
    if variacao >= LIMIAR_ALTA_CALL:
        enviar_alerta("CALL", variacao, preco, ma200)
        return "CALL"
    return None
