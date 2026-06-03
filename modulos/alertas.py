"""E-mail alert module — sends opportunity notifications via SMTP.

Credentials are read from Streamlit secrets (cloud) or .env (local).
"""

from __future__ import annotations

import datetime
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


def _html_vencimentos(opcoes: list[dict]) -> str:
    """Build HTML email body for expiry summary."""
    hoje = datetime.date.today()
    exercidas = [o for o in opcoes if o["status"] == "EXERCIDA"]
    outras = [o for o in opcoes if o["status"] != "EXERCIDA"]
    total_deposito = sum(o["strike"] * o["quantidade"] for o in exercidas)

    linhas_exercidas = ""
    for o in exercidas:
        valor = o["strike"] * o["quantidade"]
        linhas_exercidas += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333">{(o['codigo_opcao'] or '—').upper()}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">R$ {o['strike']:.2f}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">{o['quantidade']}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right;color:#e74c3c"><strong>R$ {valor:,.2f}</strong></td>
        </tr>"""

    linhas_outras = ""
    for o in outras:
        status_cor = "#2ecc71" if o["status"] == "EXPIRADA" else "#f39c12"
        linhas_outras += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333">{(o['codigo_opcao'] or '—').upper()}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">R$ {o['strike']:.2f}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">{o['quantidade']}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right;color:{status_cor}">{o['status']}</td>
        </tr>"""

    deposito_bloco = ""
    if exercidas:
        deposito_bloco = f"""
        <div style="background:#e74c3c;color:#fff;padding:14px 20px;border-radius:6px;
                    margin:16px 0;font-size:1.1rem;font-weight:bold;text-align:center">
          🏦 Deposite R$ {total_deposito:,.2f} na corretora
        </div>
        <p style="color:#ccc;font-size:0.9rem">
          Esse valor é necessário para honrar o exercício das PUTs acima.
          Faça a transferência antes da abertura do mercado.
        </p>"""

    tabela_ex = f"""
        <h3 style="color:#e74c3c">⚠️ Exercidas ({len(exercidas)})</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
          <tr style="color:#888;font-size:0.85rem">
            <th style="text-align:left;padding:6px">Código</th>
            <th style="text-align:right;padding:6px">Strike</th>
            <th style="text-align:right;padding:6px">Qtd</th>
            <th style="text-align:right;padding:6px">Valor a depositar</th>
          </tr>
          {linhas_exercidas}
        </table>
        {deposito_bloco}
    """ if exercidas else ""

    tabela_outras = f"""
        <h3 style="color:#2ecc71">✅ Outras vencidas ({len(outras)})</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
          <tr style="color:#888;font-size:0.85rem">
            <th style="text-align:left;padding:6px">Código</th>
            <th style="text-align:right;padding:6px">Strike</th>
            <th style="text-align:right;padding:6px">Qtd</th>
            <th style="text-align:right;padding:6px">Status</th>
          </tr>
          {linhas_outras}
        </table>
    """ if outras else ""

    return f"""
    <html><body style="font-family:sans-serif;background:#0e1117;color:#fafafa;padding:24px">
      <div style="max-width:560px;margin:auto;background:#1a1d27;border-radius:8px;padding:24px">
        <h2 style="margin-top:0;color:#fafafa">📋 Resumo Semanal de Opções</h2>
        <p style="color:#aaa">{hoje.strftime('%d/%m/%Y')} — opções vencidas na semana passada:</p>
        {tabela_ex}
        {tabela_outras}
        <p style="color:#888;font-size:0.8rem;margin-top:20px">
          Atualize o status das posições no painel de Opções.
        </p>
      </div>
    </body></html>
    """


def alertar_vencimentos(opcoes_vencidas: list[dict]) -> bool:
    """Send Monday expiry summary e-mail.

    Parameters
    ----------
    opcoes_vencidas : list[dict]
        Options whose ``vencimento`` fell in the past 7 days.

    Returns
    -------
    bool
        True if sent successfully, False otherwise.
    """
    if not opcoes_vencidas:
        return False

    cfg = _get_cfg()
    if not cfg["remetente"] or not cfg["senha"]:
        return False

    exercidas = [o for o in opcoes_vencidas if o["status"] == "EXERCIDA"]
    assunto = (
        f"[ETF Estratégia] 🏦 AÇÃO NECESSÁRIA — {len(exercidas)} PUT(s) exercida(s)"
        if exercidas
        else f"[ETF Estratégia] 📋 Resumo — {len(opcoes_vencidas)} opção(ões) vencida(s)"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = cfg["remetente"]
    msg["To"] = cfg["destinatario"]
    msg.attach(MIMEText(_html_vencimentos(opcoes_vencidas), "html"))

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
    """Check market data and send alert using progressive daily thresholds.

    Each alert sent on the same day raises the threshold by 0.5 pp so that
    emails are only sent for increasingly significant moves (spam prevention).

    Thresholds reset automatically at midnight (keyed by today's date).

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

    _STEP = 0.005  # 0.5 pp increment per email

    hoje = datetime.date.today().isoformat()
    key_put  = f"alerta_put_limiar_{hoje}"
    key_call = f"alerta_call_limiar_{hoje}"

    # Initialise today's thresholds on first call of the day
    if key_put  not in st.session_state:
        st.session_state[key_put]  = LIMIAR_QUEDA_PUT   # e.g. -0.015
    if key_call not in st.session_state:
        st.session_state[key_call] = LIMIAR_ALTA_CALL   # e.g.  0.020

    limiar_put  = st.session_state[key_put]
    limiar_call = st.session_state[key_call]

    bova     = dados_mercado.get("BOVA11", {})
    variacao = bova.get("variacao_pct", 0.0)
    preco    = bova.get("preco", 0.0)
    ma200    = bova.get("ma_decisao")

    if variacao <= limiar_put:
        enviado = enviar_alerta("PUT", variacao, preco, ma200)
        if enviado:
            # Tighten: next PUT alert only on an additional -0.5% move
            st.session_state[key_put] = limiar_put - _STEP
        return "PUT"

    if variacao >= limiar_call:
        enviado = enviar_alerta("CALL", variacao, preco, ma200)
        if enviado:
            # Tighten: next CALL alert only on an additional +0.5% move
            st.session_state[key_call] = limiar_call + _STEP
        return "CALL"

    return None
