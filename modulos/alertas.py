"""E-mail alerts — SMTP only, no database and no positions.

The Streamlit app checks alerts while the page is open, using the settings in
Streamlit secrets. ``notificar.py`` (run by GitHub Actions) uses this module to
send alerts even when nobody has the app open.

Credentials are read from environment variables (GitHub Actions), a local
``.env``, or Streamlit secrets (app). They are never written to the repository.
The env snapshot happens at import time, before Streamlit can load its own
secrets and overwrite the process environment.
"""

from __future__ import annotations

import html as html_lib
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

_CAMPOS_ENV = (
    "EMAIL_REMETENTE",
    "EMAIL_SENHA",
    "EMAIL_DESTINATARIO",
    "SMTP_HOST",
    "SMTP_PORT",
    "APP_URL",
)
_ENV = {nome: os.getenv(nome, "") for nome in _CAMPOS_ENV}


def _get(nome: str, padrao: str = "") -> str:
    """Read a setting from env/.env first, then Streamlit secrets.

    The env snapshot matters for GitHub Actions; the Streamlit fallback lets
    the app use the e-mail settings already configured in Streamlit Cloud.
    """
    valor = _ENV.get(nome) or os.getenv(nome, "")
    if valor:
        return valor
    try:
        import streamlit as st

        if nome in st.secrets:
            segredo = st.secrets[nome]
            if segredo:
                return str(segredo)
    except Exception:
        pass
    return padrao


def configuracao() -> dict[str, str]:
    """Return SMTP settings without ever exposing them in logs."""
    return {
        "remetente": _get("EMAIL_REMETENTE").strip(),
        # Gmail shows app passwords as "abcd efgh ijkl mnop"; spaces are visual.
        "senha": _get("EMAIL_SENHA").replace(" ", "").strip(),
        "destinatario": _get("EMAIL_DESTINATARIO").strip(),
        "host": _get("SMTP_HOST", "smtp.gmail.com"),
        "port": _get("SMTP_PORT", "587"),
        "app_url": _get("APP_URL"),
    }


def configurado() -> bool:
    cfg = configuracao()
    return bool(cfg["remetente"] and cfg["senha"] and cfg["destinatario"])


def _fmt_reais(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor * 100:+.2f} %".replace(".", ",")


def _fmt_prob(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor * 100:.0f} %".replace(".", ",")


def _botao(url: str, texto: str = "Abrir o painel") -> str:
    if not url:
        return ""
    return (
        '<div style="text-align:center;margin:22px 0">'
        f'<a href="{html_lib.escape(url)}" style="background:#2563eb;color:#fff;'
        "padding:12px 26px;border-radius:8px;text-decoration:none;"
        'font-weight:700;display:inline-block">'
        f"{html_lib.escape(texto)}</a></div>"
    )


def montar_email_movimentos(
    itens: list[dict],
    app_url: str = "",
    agora: datetime | None = None,
) -> tuple[str, str]:
    """Build the HTML and plain-text bodies for a movement alert.

    ``itens`` is a list of dicts with: ativo, preco, variacao_pct, vies,
    modo, acao, strike, premio_teorico, premio_real, premio_real_pct,
    strike_real, data_real, prob, motivo, confianca.
    """
    quando = (agora or datetime.now()).strftime("%d/%m/%Y %H:%M")

    cards = []
    linhas_texto = []
    for item in itens:
        var = item.get("variacao_pct") or 0.0
        cor = "#16a34a" if var >= 0 else "#dc2626"
        modo = item.get("modo") or "—"
        modo_txt = "🔥 ESTICADO" if modo == "ESTICADO" else "RENDA"
        acao = item.get("acao") or "AGUARDAR"
        acao_cor = "#16a34a" if acao.startswith("VENDER") else "#6b7280"

        real = item.get("premio_real")
        real_txt = "—"
        if real is not None:
            real_txt = _fmt_reais(real)
            if item.get("premio_real_pct") is not None:
                real_txt += f" ({item['premio_real_pct'] * 100:.2f} %)".replace(".", ",")
            if item.get("strike_real") is not None:
                real_txt += f" · K{int(round(item['strike_real']))}"
            if item.get("data_real"):
                real_txt += f" · fech. {item['data_real']}"

        ma = item.get("ma")
        dist_ma = item.get("distancia_ma")
        ma_txt = "MA50 indisponível"
        if ma:
            ma_txt = f"MA50 {_fmt_reais(ma)}"
            if dist_ma is not None:
                lado = "acima" if dist_ma >= 0 else "abaixo"
                ma_txt += f" · preço {_fmt_pct(dist_ma)} {lado}"

        cards.append(
            f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:16px;
                    margin:0 0 14px 0;background:#fff">
          <div style="display:flex;justify-content:space-between;gap:12px;
                      align-items:baseline;flex-wrap:wrap">
            <div style="font-size:1.15rem;font-weight:700;color:#111827">
              {html_lib.escape(str(item.get('ativo', '—')))}
              <span style="color:{cor};font-size:1rem">{_fmt_pct(var)}</span>
            </div>
            <div style="color:#374151;font-size:0.9rem">
              {modo_txt} · viés {html_lib.escape(str(item.get('vies', '—')))}
            </div>
          </div>
          <div style="margin-top:10px;color:#111827">
            <strong style="color:{acao_cor}">{html_lib.escape(str(acao))}</strong>
            &nbsp;·&nbsp; preço {_fmt_reais(item.get('preco'))}
            &nbsp;·&nbsp; strike {_fmt_reais(item.get('strike'))}
          </div>
          <div style="margin-top:4px;color:#374151;font-size:0.9rem">
            {ma_txt}
          </div>
          <div style="margin-top:4px;color:#4b5563;font-size:0.92rem">
            Prêmio real (fech.): {real_txt}<br>
            Prêmio teórico: {_fmt_reais(item.get('premio_teorico'))}
            &nbsp;·&nbsp; prob. exercício: {_fmt_prob(item.get('prob'))}
          </div>
          <div style="margin-top:8px;color:#6b7280;font-size:0.85rem">
            {html_lib.escape(str(item.get('motivo', '')))}
          </div>
        </div>"""
        )
        linhas_texto.append(
            f"{item.get('ativo')} {_fmt_pct(var)} | {acao} | strike {_fmt_reais(item.get('strike'))}\n"
            f"  preço {_fmt_reais(item.get('preco'))} · modo {modo} · viés {item.get('vies')}\n"
            f"  {ma_txt}\n"
            f"  prêmio real (fech.) {real_txt}\n"
            f"  prêmio teórico {_fmt_reais(item.get('premio_teorico'))} · prob. {_fmt_prob(item.get('prob'))}\n"
            f"  motivo: {item.get('motivo', '')}"
        )

    html_body = f"""
    <html><body style="margin:0;padding:0;background:#f3f4f6;
                       font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif">
      <div style="max-width:620px;margin:0 auto;padding:24px 16px">
        <div style="background:#111827;color:#fff;border-radius:12px 12px 0 0;padding:22px 24px">
          <div style="font-size:1.45rem;font-weight:800;margin:0">⚡ Movimento forte</div>
          <div style="color:#d1d5db;font-size:0.9rem;margin-top:4px">
            {quando} · alerta automático dos ativos monitorados
          </div>
        </div>
        <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:0;
                    border-radius:0 0 12px 12px;padding:18px">
          {''.join(cards)}
          {_botao(app_url)}
          <div style="color:#6b7280;font-size:0.8rem;line-height:1.5;margin-top:10px">
            CALL é sempre <strong>coberta</strong>: o app não rastreia posição.
            Prêmio real é o último negócio de fechamento da opcoes.net.br, não o bid de agora.
            Confirme o bid no Home Broker antes de operar. Isto não é recomendação de investimento.
          </div>
        </div>
      </div>
    </body></html>
    """

    texto = (
        f"Movimento forte — {quando}\n\n"
        + "\n\n".join(linhas_texto)
        + "\n\nCALL só se coberta. Confirme o bid no Home Broker. Não é recomendação.\n"
    )
    return html_body, texto


def enviar_email(assunto: str, html_body: str, texto_body: str = "") -> tuple[bool, str]:
    """Send one HTML e-mail. Returns ``(ok, error_message)``."""
    cfg = configuracao()
    if not (cfg["remetente"] and cfg["senha"] and cfg["destinatario"]):
        return False, (
            "E-mail não configurado. Defina EMAIL_REMETENTE, EMAIL_SENHA e "
            "EMAIL_DESTINATARIO nos Secrets do GitHub (ou no .env local)."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = cfg["remetente"]
    msg["To"] = cfg["destinatario"]
    if texto_body:
        msg.attach(MIMEText(texto_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30) as servidor:
            servidor.ehlo()
            servidor.starttls(context=contexto)
            servidor.ehlo()
            servidor.login(cfg["remetente"], cfg["senha"])
            servidor.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        return True, ""
    except Exception as exc:  # noqa: BLE001 — report to the workflow log
        return False, f"{type(exc).__name__}: {exc}"


def email_teste(app_url: str = "") -> tuple[bool, str]:
    """Send a small test message to validate SMTP settings."""
    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f3f4f6;padding:24px">
      <div style="max-width:520px;margin:auto;background:#fff;border:1px solid #e5e7eb;
                  border-radius:10px;padding:24px">
        <h2 style="margin-top:0;color:#111827">✅ Alerta de e-mail funcionando</h2>
        <p style="color:#374151">Se você recebeu esta mensagem, o notificador dos sinais
        de opções está configurado corretamente.</p>
        {_botao(app_url)}
        <p style="color:#6b7280;font-size:0.85rem">Mensagem automática de teste.</p>
      </div>
    </body></html>
    """
    return enviar_email(
        "[Sinais] ✅ Teste de alerta por e-mail",
        html_body,
        "Alerta de e-mail funcionando. Mensagem automática de teste.",
    )
