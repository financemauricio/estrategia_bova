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

from modulos import mercado as _mercado_mod  # noqa: E402 — same package, no circular dep


def _get_cfg() -> dict[str, str]:
    """Return e-mail config from secrets or environment variables."""
    try:
        return {
            "remetente":    st.secrets["EMAIL_REMETENTE"],
            "senha":        st.secrets["EMAIL_SENHA"],
            "destinatario": st.secrets["EMAIL_DESTINATARIO"],
            "host":         st.secrets["SMTP_HOST"],
            "port":         st.secrets["SMTP_PORT"],
            "app_url":      st.secrets.get("APP_URL", ""),
        }
    except Exception:
        from dotenv import load_dotenv
        load_dotenv()
        return {
            "remetente":    os.getenv("EMAIL_REMETENTE", ""),
            "senha":        os.getenv("EMAIL_SENHA", ""),
            "destinatario": os.getenv("EMAIL_DESTINATARIO", ""),
            "host":         os.getenv("SMTP_HOST", "smtp.gmail.com"),
            "port":         os.getenv("SMTP_PORT", "587"),
            "app_url":      os.getenv("APP_URL", ""),
        }


def _botao_link(url: str, texto: str = "🚀 Acessar o painel agora") -> str:
    """Return an HTML button linking to the app, or empty string if no URL."""
    if not url:
        return ""
    return f"""
    <div style="text-align:center;margin:20px 0">
      <a href="{url}" style="background:#3498db;color:#fff;padding:12px 28px;
         border-radius:6px;text-decoration:none;font-weight:bold;font-size:1rem;
         display:inline-block">{texto}</a>
    </div>"""


def _html_template(tipo: str, variacao_pct: float, preco: float, ma200: float | None, app_url: str = "") -> str:
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
        {_botao_link(app_url)}
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
    msg.attach(MIMEText(_html_template(tipo, variacao_pct, preco, ma200, cfg["app_url"]), "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls(context=context)
            server.login(cfg["remetente"], cfg["senha"])
            server.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        return True
    except Exception:
        return False


def _html_vencimentos(opcoes: list[dict], app_url: str = "") -> str:
    """Build HTML email body for expiry summary."""
    _app_url_venc = app_url
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
        {_botao_link(_app_url_venc, "📋 Acessar Carteira")}
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
    msg.attach(MIMEText(_html_vencimentos(opcoes_vencidas, cfg["app_url"]), "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls(context=context)
            server.login(cfg["remetente"], cfg["senha"])
            server.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        return True
    except Exception:
        return False


def alertar_lembrete_sexta(opcoes_abertas: list[dict]) -> bool:
    """Send a Friday reminder e-mail to prompt the user to visit the dashboard.

    Parameters
    ----------
    opcoes_abertas : list[dict]
        Open option positions — used to highlight any expiring within 7 days.

    Returns
    -------
    bool
        True if sent successfully, False otherwise.
    """
    cfg = _get_cfg()
    if not cfg["remetente"] or not cfg["senha"]:
        return False

    hoje = datetime.date.today()
    proximas = []
    for op in opcoes_abertas:
        venc = op.get("vencimento")
        if isinstance(venc, str):
            venc = datetime.date.fromisoformat(venc)
        dias = (venc - hoje).days if venc else 999
        if 0 <= dias <= 7:
            proximas.append((op.get("codigo_opcao") or "—", dias, op.get("strike", 0)))

    alerta_opcoes = ""
    if proximas:
        linhas = "".join(
            f"<tr><td style='padding:6px;border-bottom:1px solid #333'>"
            f"{cod.upper()}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #333;text-align:right'>"
            f"R$ {strike:.2f}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #333;text-align:right;color:#e74c3c'>"
            f"{dias}d ⚠️</td></tr>"
            for cod, dias, strike in proximas
        )
        alerta_opcoes = f"""
        <div style="background:#1e2a1e;border:1px solid #e74c3c;border-radius:6px;padding:16px;margin:16px 0">
          <h3 style="color:#e74c3c;margin-top:0">⚠️ {len(proximas)} opção(ões) vencendo esta semana</h3>
          <table style="width:100%;border-collapse:collapse">
            <tr style="color:#888;font-size:0.85rem">
              <th style="text-align:left;padding:6px">Código</th>
              <th style="text-align:right;padding:6px">Strike</th>
              <th style="text-align:right;padding:6px">Dias</th>
            </tr>
            {linhas}
          </table>
        </div>"""

    html = f"""
    <html><body style="font-family:sans-serif;background:#0e1117;color:#fafafa;padding:24px">
      <div style="max-width:520px;margin:auto;background:#1a1d27;border-radius:8px;padding:24px">
        <h2 style="margin-top:0;color:#fafafa">📅 Lembrete Semanal — {hoje.strftime('%d/%m/%Y')}</h2>
        <p>É sexta-feira! Hora de revisar a estratégia e verificar oportunidades.</p>
        {alerta_opcoes}
        <div style="background:#2c3e50;padding:14px 20px;border-radius:6px;margin:16px 0">
          <p style="margin:0;font-size:0.95rem">
            📊 Acesse o <strong>Dashboard</strong> para ver o viés de mercado (MA50)<br>
            📋 Revise a <strong>Carteira</strong> para gerir posições em opções
          </p>
        </div>
        {_botao_link(cfg["app_url"])}
        <p style="color:#888;font-size:0.8rem;margin-top:16px">
          Este lembrete é enviado toda sexta ao acessar o painel.
        </p>
      </div>
    </body></html>
    """

    assunto = (
        f"[ETF Estratégia] ⚠️ Lembrete — {len(proximas)} opção(ões) vencendo esta semana"
        if proximas
        else f"[ETF Estratégia] 📅 Lembrete semanal — {hoje.strftime('%d/%m')}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = cfg["remetente"]
    msg["To"] = cfg["destinatario"]
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls(context=context)
            server.login(cfg["remetente"], cfg["senha"])
            server.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        return True
    except Exception:
        return False


def alertar_oportunidade_recompra(
    opcoes_abertas: list[dict],
    dados_mkt: dict,
) -> bool:
    """Send a buyback-opportunity alert when the underlying moves favorably.

    For a sold PUT: underlying rises >= LIMIAR_RECOMPRA_PCT → PUT lost value,
    good moment to close the position with profit.
    For a sold CALL: underlying falls >= LIMIAR_RECOMPRA_PCT → CALL lost value,
    same logic.

    A session_state guard (keyed by option id + date) prevents repeat emails
    for the same position on the same day.

    Parameters
    ----------
    opcoes_abertas : list[dict]
        Open option records from ``banco.listar_opcoes('ABERTA')``.
    dados_mkt : dict
        Output from ``mercado.buscar_dados_mercado()`` — covers the main ETFs.

    Returns
    -------
    bool
        True if at least one alert email was sent.
    """
    from config import LIMIAR_RECOMPRA_PCT

    cfg = _get_cfg()
    if not cfg["remetente"] or not cfg["senha"]:
        return False

    hoje = datetime.date.today()
    disparadas: list[dict] = []

    for op in opcoes_abertas:
        op_id   = op["id"]
        ativo   = op["ativo"]
        tipo    = op["tipo"]
        guard   = f"recompra_{op_id}_{hoje.isoformat()}"

        if st.session_state.get(guard):
            continue  # already alerted for this position today

        # Get daily variation for the underlying
        variacao: float | None = None
        d = dados_mkt.get(ativo)
        if d and "variacao_pct" in d:
            variacao = d["variacao_pct"]
            spot     = d.get("preco", 0.0)
        else:
            # Arbitrary underlying — compute from history
            d_op = _mercado_mod.buscar_dados_ativo_opcao(ativo)
            hist = d_op.get("hist")
            spot = d_op.get("preco") or 0.0
            if hist is not None and len(hist) >= 2:
                try:
                    variacao = float(hist["Close"].iloc[-1] / hist["Close"].iloc[-2]) - 1
                except Exception:
                    pass

        if variacao is None:
            continue

        # Check trigger condition
        triggered = (
            (tipo == "PUT"  and variacao >=  LIMIAR_RECOMPRA_PCT) or
            (tipo == "CALL" and variacao <= -LIMIAR_RECOMPRA_PCT)
        )
        if not triggered:
            continue

        venc = op.get("vencimento")
        if isinstance(venc, str):
            venc = datetime.date.fromisoformat(venc)
        dias = (venc - hoje).days if venc else "—"

        disparadas.append({
            "id":        op_id,
            "guard":     guard,
            "codigo":    (op.get("codigo_opcao") or "—").upper(),
            "tipo":      tipo,
            "ativo":     ativo,
            "strike":    op["strike"],
            "spot":      spot,
            "variacao":  variacao,
            "dias":      dias,
            "premio":    op.get("premio_total", 0.0),
        })

    if not disparadas:
        return False

    # Build email
    linhas = ""
    for r in disparadas:
        sinal   = f"+{r['variacao']*100:.1f}%" if r["variacao"] >= 0 else f"{r['variacao']*100:.1f}%"
        cor_var = "#2ecc71" if r["variacao"] >= 0 else "#e74c3c"
        acao    = "recomprar PUT" if r["tipo"] == "PUT" else "recomprar CALL"
        linhas += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333">{r['codigo']}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:center">{r['tipo']}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">R$ {r['strike']:.2f}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right">R$ {r['spot']:.2f}</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:right;color:{cor_var}"><strong>{sinal}</strong></td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:center">{r['dias']}d</td>
          <td style="padding:8px;border-bottom:1px solid #333;text-align:center">{acao}</td>
        </tr>"""

    n = len(disparadas)
    html = f"""
    <html><body style="font-family:sans-serif;background:#0e1117;color:#fafafa;padding:24px">
      <div style="max-width:620px;margin:auto;background:#1a1d27;border-radius:8px;padding:24px">
        <h2 style="color:#2ecc71;margin-top:0">💰 Oportunidade de Recompra — {n} posição(ões)</h2>
        <p>O ativo subjacente se moveu na direção favorável ao fechamento das posições abaixo.
           Considere recomprar para realizar o lucro.</p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px;font-size:0.9rem">
          <tr style="color:#888;font-size:0.8rem">
            <th style="text-align:left;padding:6px">Código</th>
            <th style="padding:6px">Tipo</th>
            <th style="text-align:right;padding:6px">Strike</th>
            <th style="text-align:right;padding:6px">Spot</th>
            <th style="text-align:right;padding:6px">Variação</th>
            <th style="padding:6px">Dias</th>
            <th style="padding:6px">Ação sugerida</th>
          </tr>
          {linhas}
        </table>
        {_botao_link(cfg['app_url'], '📋 Abrir Carteira para encerrar posição')}
        <p style="color:#888;font-size:0.8rem;margin-top:16px">
          Avalie o prêmio de recompra no Home Broker. Esta oportunidade não implica obrigação de fechar.
        </p>
      </div>
    </body></html>
    """

    assunto = f"[ETF Estratégia] 💰 Recompra de opção — {n} posição(ões) favorável(is)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"]    = cfg["remetente"]
    msg["To"]      = cfg["destinatario"]
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], int(cfg["port"])) as server:
            server.starttls(context=context)
            server.login(cfg["remetente"], cfg["senha"])
            server.sendmail(cfg["remetente"], cfg["destinatario"], msg.as_string())
        # Mark all triggered positions as alerted for today
        for r in disparadas:
            st.session_state[r["guard"]] = True
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
