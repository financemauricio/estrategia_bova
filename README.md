# Sinais de Opções — BOVA11, VALE3, ITUB4, PRIO3

Painel **somente leitura de mercado** para a estratégia de venda de opções (wheel).
Não guarda posições, valores, aportes nem qualquer dado pessoal: não há banco de
dados, login ou cadastro. Abre, mostra o sinal do dia e pronto.

---

## O que ele responde

Para cada ativo monitorado, **uma** pergunta:

> "Hoje eu venderia PUT ou CALL? Em que strike? O prêmio paga o risco?"

| Viés | Condição | Ação sugerida |
|---|---|---|
| **PUT** | preço abaixo da MA50 | vender PUT com delta ≈ -0,25 |
| **CALL** | preço acima da MA50 | vender CALL 3 % OTM |
| **AGUARDAR** | prêmio teórico < 0,6 % do preço | ficar de fora |

Prioridade máxima quando o dia tem queda ≥ 1,5 % (PUT) ou alta ≥ 2 % (CALL),
na direção do viés.

---

## Rodar localmente

```bash
cd /home/geoia/Documentos/codigos/acao/Validacao_planilha/estrategia_acumulacao
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Abre em `http://localhost:8501`. Não precisa de banco nem de configuração prévia.

### Token da brapi (opcional)

O Yahoo às vezes devolve a sessão atual com Open/High/Low zerados. Com um token
gratuito da [brapi.dev](https://brapi.dev) o app corrige essa barra com o spot real.

```bash
# .streamlit/secrets.toml  (local, ignorado pelo git)
BRAPI_TOKEN = "seu_token"
```

No Streamlit Cloud: **Manage app → Settings → Secrets**, cole a mesma linha e
faça **Reboot app**. Sem token, o app descarta a barra corrompida e avisa na tela.

---

## Deploy

```bash
git add .
git commit -m "ajuste: ..."
git push
```

O Streamlit Cloud republica sozinho em ~1 minuto.

---

## Estrutura

```
estrategia_acumulacao/
├── app.py                     # navegação (Sinais, Análise, A Regra)
├── config.py                  # ativos, limiares, delta, prêmio mínimo
├── requirements.txt
├── modulos/
│   ├── mercado.py             # yfinance + correção de barra via brapi
│   ├── estrategia.py          # regra por ativo (viés, strike, prêmio)
│   ├── bs.py                  # Black-Scholes, vol histórica, Selic (BCB)
│   ├── opcoes_b3.py           # brapi, strike por delta, delta/BS
│   └── componentes.py         # formatação de UI
├── pages/
│   ├── 1_Sinais.py            # tabela de sinais dos 4 ativos
│   ├── 2_Analise_Ativo.py     # gráfico + detalhe do ativo escolhido
│   └── 3_Regra.py             # a regra e a expectativa realista
└── tests/                     # testes puros (sem rede)
```

---

## Ajustar a regra

Tudo em `config.py`:

| Constante | Padrão | Significado |
|---|---|---|
| `TICKERS` | BOVA11, VALE3, ITUB4, PRIO3 | ativos monitorados |
| `MA_PERIODO` | 50 | média que define o viés |
| `DELTA_PUT_ALVO` | -0,25 | risco alvo da PUT (~25 % de exercício) |
| `CALL_STRIKE_OTM_PCT` | 3 % | distância da CALL |
| `PREMIO_MIN_PCT` | 0,6 % | prêmio mínimo por ciclo, em % do preço |
| `LIMIAR_QUEDA_PUT` | -1,5 % | queda que aciona prioridade |
| `LIMIAR_ALTA_CALL` | +2,0 % | alta que aciona prioridade |
| `DIAS_VENCIMENTO_PADRAO` | 30 | prazo usado no cálculo |

---

## Testes

```bash
pip install pytest
pytest tests/ -q
```

Cobrem: viés PUT/CALL, bloqueio por prêmio baixo, strike por delta e correção
da barra corrompida.

---

## Aviso

Ferramenta de leitura de mercado, **não** é recomendação de investimento.
Prêmios são teóricos (Black-Scholes com volatilidade histórica); o que vale é o
**bid real** no Home Broker. Opções têm risco de perda relevante.
