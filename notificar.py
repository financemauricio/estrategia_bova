"""E-mail notifier for strong daily moves aligned with the MA50.

Run by ``.github/workflows/alertas.yml`` every 15 minutes during the B3
session. It evaluates the same rule as the Streamlit app: above the MA50 the
bias is CALL (wait for a rise), below it the bias is PUT (wait for a drop).
It sends one message per new move (at most once per
asset/direction/action/mode per day).

Examples
--------
    python notificar.py --dry-run --forcar
    python notificar.py --teste-email
    python notificar.py --state estado_alertas.json

No personal data is stored in the repository: the e-mail destination lives in
GitHub Secrets (or a local ``.env``). The state file contains only tickers,
dates and directions; it is ignored by git.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config import ALERTA_MOVIMENTO_PCT, DIAS_VENCIMENTO_PADRAO
from modulos import alertas, bs, cadeia, cotacoes, estrategia, mercado


def carregar_estado(caminho: str | Path, hoje: str) -> dict:
    """Load the day's sent alerts, resetting when the date changes."""
    caminho = Path(caminho)
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        bruto = {}

    if not isinstance(bruto, dict) or bruto.get("data") != hoje:
        return {"data": hoje, "enviados": {}}

    enviados = bruto.get("enviados")
    if not isinstance(enviados, dict):
        enviados = {}
    return {"data": hoje, "enviados": enviados}


def salvar_estado(caminho: str | Path, estado: dict) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _chave(
    ativo: str,
    variacao_pct: float,
    acao: str = "AGUARDAR",
    modo: str = "RENDA",
) -> str:
    """Daily dedup key: same asset/direction/action/mode alerts only once."""
    direcao = "ALTA" if variacao_pct >= 0 else "QUEDA"
    return f"{ativo}:{direcao}:{acao}:{modo}"


def selecionar_alertas(
    resultados: list[dict],
    estado: dict,
    limiar: float = ALERTA_MOVIMENTO_PCT,
) -> list[dict]:
    """Return new alerts aligned with the MA50 bias and not sent today.

    The move must confirm the bias: above MA50 (CALL) only a rise >= limiar
    alerts; below MA50 (PUT) only a drop >= limiar alerts. Stale/absent quotes
    are skipped. The rule's action (VENDER/AGUARDAR) is included, but a strong
    move is reported even when the premium is not enough — the user can see
    that the rule says "aguardar".
    """
    enviados = estado.get("enviados", {})
    novos: list[dict] = []

    for r in resultados:
        variacao = r.get("variacao_pct")
        if variacao is None:
            continue

        vies = r.get("vies")
        if vies == "CALL":
            # Acima da MA50: só faz sentido alertar alta forte (CALL coberta).
            if variacao < limiar:
                continue
        elif vies == "PUT":
            # Abaixo da MA50: só faz sentido alertar queda forte (PUT).
            if variacao > -limiar:
                continue
        else:
            continue

        cot = r.get("cotacao") or {}
        if cot.get("confianca") == "sem_dados":
            continue
        if cot.get("possivel_atraso"):
            continue

        ativo = str(r.get("ativo", "—"))
        direcao = "ALTA" if variacao >= 0 else "QUEDA"
        acao = str(r.get("acao", "AGUARDAR"))
        chave = _chave(ativo, float(variacao), acao, str(r.get("modo", "RENDA")))
        if chave in enviados:
            continue
        # Não repete "AGUARDAR" no mesmo dia/direção (evita downgrade/ruído).
        if acao == "AGUARDAR" and any(
            k.startswith(f"{ativo}:{direcao}:") for k in enviados
        ):
            continue

        novos.append(
            {
                "chave": chave,
                "direcao": "ALTA" if variacao >= 0 else "QUEDA",
                "resultado": r,
            }
        )

    return novos


def _motivo(r: dict) -> str:
    if r.get("modo") == "ESTICADO":
        gatilhos = r.get("gatilhos") or {}
        return (
            f"Modo esticado ({gatilhos.get('ativos', 0)}/3): "
            f"{estrategia.descrever_gatilhos(gatilhos)}."
        )
    if r.get("prioridade"):
        return "Movimento forte no dia, na direção do viés da MA50."
    return "Movimento do dia na direção do viés da MA50."


def _item_email(r: dict, selic: float, usar_cadeia: bool = True) -> dict:
    """Enrich one rule result with the real closing premium, when possible."""
    real = None
    if usar_cadeia and r.get("vies") in ("CALL", "PUT") and r.get("strike_sugerido"):
        try:
            cad = cadeia.cadeia(r["ativo"])
            real = cadeia.resumo_premio(
                cad,
                r["vies"],
                r.get("preco"),
                r.get("dias", DIAS_VENCIMENTO_PADRAO),
                selic,
                strike_ref=r.get("strike_sugerido"),
            )
        except Exception:
            real = None

    preco = r.get("preco")
    ma = r.get("ma_decisao")
    distancia_ma = (preco - ma) / ma if preco and ma else None
    premio_real = real["preco"] if real else None
    premio_real_pct = (
        premio_real / preco if premio_real is not None and preco else None
    )

    return {
        "ativo": r.get("ativo", "—"),
        "preco": preco,
        "ma": ma,
        "distancia_ma": distancia_ma,
        "variacao_pct": r.get("variacao_pct"),
        "vies": r.get("vies", "—"),
        "modo": r.get("modo", "—"),
        "acao": r.get("acao", "AGUARDAR"),
        "strike": r.get("strike_sugerido"),
        "premio_teorico": r.get("premio_teorico"),
        "premio_real": premio_real,
        "premio_real_pct": premio_real_pct,
        "strike_real": real.get("strike") if real else None,
        "data_real": real.get("data") if real else None,
        "prob": r.get("prob_exercicio"),
        "motivo": _motivo(r),
        "confianca": (r.get("cotacao") or {}).get("confianca"),
    }


def montar_assunto(itens: list[dict]) -> str:
    if not itens:
        return "[Sinais] Sem alertas"
    if len(itens) == 1:
        item = itens[0]
        var = item.get("variacao_pct") or 0.0
        sinal = "alta" if var >= 0 else "queda"
        variacao = f"{var * 100:+.2f} %".replace(".", ",")
        return (
            f"[Sinais] ⚡ {item.get('ativo')} {variacao} — {sinal} · "
            f"{item.get('acao')}"
        )

    nomes = ", ".join(str(i.get("ativo")) for i in itens)
    return f"[Sinais] ⚡ {len(itens)} movimentos fortes — {nomes}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alertas por e-mail dos sinais de opções.")
    parser.add_argument(
        "--state",
        default="estado_alertas.json",
        help="arquivo de estado local (ignorado pelo git)",
    )
    parser.add_argument(
        "--limiar",
        type=float,
        default=ALERTA_MOVIMENTO_PCT,
        help="variação absoluta mínima, ex.: 0.02 = 2 %%",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra o e-mail no terminal, sem enviar nem atualizar o estado",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="roda mesmo com o mercado fechado (útil para teste)",
    )
    parser.add_argument(
        "--sem-cadeia",
        action="store_true",
        help="não busca o prêmio real de fechamento (mais rápido)",
    )
    parser.add_argument(
        "--teste-email",
        action="store_true",
        help="envia uma mensagem de teste e sai",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.teste_email:
        ok, erro = alertas.email_teste(alertas.configuracao().get("app_url", ""))
        print("Teste enviado." if ok else f"Falha no teste: {erro}")
        return 0 if ok else 1

    agora = cotacoes.agora_brt()
    if not args.forcar and not cotacoes.mercado_aberto(agora):
        print("Mercado fechado — sem alerta.")
        return 0

    dados = mercado.buscar_dados_mercado()
    if not dados:
        print("Sem cotações agora — nada a fazer.")
        return 1

    selic = bs.buscar_selic()
    resultados = estrategia.avaliar_carteira(dados, selic, DIAS_VENCIMENTO_PADRAO)

    hoje = agora.date().isoformat()
    caminho_estado = Path(args.state)
    estado = carregar_estado(caminho_estado, hoje)
    selecionados = selecionar_alertas(resultados, estado, args.limiar)

    if not selecionados:
        print("Nenhum movimento novo acima do limite.")
        return 0

    itens = [
        _item_email(s["resultado"], selic, usar_cadeia=not args.sem_cadeia)
        for s in selecionados
    ]
    assunto = montar_assunto(itens)
    html_body, texto_body = alertas.montar_email_movimentos(
        itens,
        app_url=alertas.configuracao().get("app_url", ""),
        agora=agora,
    )

    if args.dry_run:
        print("DRY-RUN — nada foi enviado.")
        print(f"Assunto: {assunto}\n")
        print(texto_body)
        return 0

    ok, erro = alertas.enviar_email(assunto, html_body, texto_body)
    if not ok:
        print(f"Falha ao enviar: {erro}")
        return 1

    for s in selecionados:
        estado["enviados"][s["chave"]] = agora.isoformat()
    salvar_estado(caminho_estado, estado)
    print(f"Alerta enviado: {assunto}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
