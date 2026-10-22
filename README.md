# Sinais de Opções — BOVA11, VALE3, ITSA4, PRIO3

Painel **somente leitura de mercado** para a estratégia de venda de opções (wheel).
Não guarda posições, valores, aportes nem qualquer dado pessoal: não há banco de
dados, login ou cadastro. Abre, mostra o sinal do dia e pronto.

O alerta por e-mail é opcional. Com o painel aberto, ele usa os secrets do
**Streamlit Cloud**; com o painel fechado, o **GitHub Actions** usa os secrets do
GitHub. O endereço de destino não fica no código.

---

## O que ele responde

Para cada ativo monitorado, **uma** pergunta:

> "Hoje eu venderia PUT ou CALL? Em que strike? O prêmio paga o risco?"

| Viés | Condição | Modo renda (padrão) | Modo esticado (exceção) |
|---|---|---|---|
| **PUT** | preço abaixo da MA50 | delta ≈ -0,15 | — |
| **CALL** | preço acima da MA50 | delta ≈ +0,15 (coberta) | CALL +3 % OTM |
| **AGUARDAR** | prêmio abaixo do piso | 0,4 % do preço | 1,0 % do preço |

O **modo esticado** liga quando o ativo sobe muito: 2 de 3 critérios entre
distância ≥ 8 % acima da MA50, RSI(14) ≥ 70 e ganho de 5 dias ≥ 5 %. A ideia é
colher prêmio maior e, se exercido, vender num preço esticado. A CALL é sempre
**coberta** — o app não rastreia posição.

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
faça **Reboot app**. Sem token, o app segue com Yahoo + Status Invest.

### Cotação em três fontes

O preço do ativo é o input da regra, então ele não vem de uma fonte só:

| Fonte | O que traz | Horário |
|---|---|---|
| Yahoo Finance | preço e horário do último negócio | sim |
| brapi | preço e fechamento anterior | não (o horário é do feed, não do negócio) |
| Status Invest | preço de conferência | não |

- As fontes são comparadas a cada 2 min. Se concordam (até 0,8 %), o app mostra
  `consenso`; se divergem, avisa e manda confirmar no Home Broker.
- Fora do pregão o cabeçalho mostra **"fechamento de dd/mm"** em vez de um
  horário que poderia parecer tempo real.
- A cotação fica visível na tabela de sinais (coluna `Cotação`) e no detalhe de
  cada ativo, com o preço de cada fonte em **🔎 De onde vem cada preço**.
- Fontes gratuitas têm **atraso de até 15 min**. Nos primeiros minutos do pregão
  elas ainda devolvem o fechamento anterior; nesse caso o app mostra
  **"fechamento de dd/mm"** e avisa, em vez de fingir que o preço é de agora.
- Atualização automática a cada 2 min; o botão **🔄 Forçar atualização agora**
  limpa o cache e busca de novo.

### Prêmio real — a cadeia de opções

O prêmio teórico (Black-Scholes com volatilidade histórica) é a régua da regra.
Para ver o que o mercado **realmente pagou**, o app lê a cadeia pública da
[opcoes.net.br](https://opcoes.net.br) — último negócio de cada série, sem login:

| Campo | Uso no app |
|---|---|
| último preço | prêmio real do vencimento mais próximo de 30 dias |
| delta | conferência do strike sugerido (renda ≈ ±0,15) |
| nº de negócios | liquidez da série |
| vencimento / dias | comparação semanal × mensal |

- É **fechamento** (D-1): o app mostra a data e o vencimento, e não confunde com
  o bid de agora. Cache de 15 min, uma requisição por ativo.
- **Por que o mesmo strike vale tão diferente?** Em 21/10/2026, BOVA11 K210
  valia **R$ 0,21** no semanal de 23/10 (1 dia) e **R$ 7,19** no mensal de 19/11
  (28 dias). O teórico de ~R$ 7,00 é do mensal — não do semanal.
- A página **Análise do Ativo** mostra a cadeia completa do vencimento escolhido
  (CALL e PUT por strike, com delta e liquidez) e um comparativo do mesmo strike
  em todos os vencimentos.


---

## Deploy

```bash
git add .
git commit -m "ajuste: ..."
git push
```

O Streamlit Cloud republica sozinho em ~1 minuto.

---

## Alertas por e-mail

Há dois caminhos, e os dois usam a mesma regra:

- **Painel aberto:** a página **Sinais** verifica a cada atualização e envia
  usando os secrets **já configurados no Streamlit Cloud**. Não precisa mexer no
  GitHub. Funciona enquanto a aba estiver aberta; se o Streamlit hibernar, para.
- **Painel fechado (24 h):** o **GitHub Actions** roda de graça a cada 15 min
  durante o pregão (10:00–17:59 BRT, seg–sex) e usa os **GitHub Secrets**.

Se os dois caminhos estiverem ativos ao mesmo tempo, pode chegar um e-mail
duplicado; use um por vez.

- Primeiro olha a **MA50**: preço acima → viés **CALL**; abaixo → viés **PUT**.
- Só dispara se o movimento do dia **confirmar o viés**: alta ≥ **2 %** com viés
  CALL, ou queda ≥ **2 %** com viés PUT (`ALERTA_MOVIMENTO_PCT`).
- Se está acima da MA50 e cai 2 %, **não** manda (o viés continua CALL); se está
  abaixo e sobe 2 %, **não** manda (o viés continua PUT). Se o movimento fizer o
  preço cruzar a MA50, o viés muda e o alerta pode disparar.
- Manda no máximo **um e-mail por ativo, direção, ação e modo por dia**, para não
  spammar. Se a condição mudar (ex.: AGUARDAR → VENDER, ou RENDA → ESTICADO),
  chega um novo aviso.
- Ignora cotação atrasada ou sem fonte.
- Inclui preço, variação, **MA50 e distância até ela**, viés, modo
  (renda/esticado), ação, strike, prêmio teórico, prêmio real de fechamento e
  probabilidade de exercício.

### Já configurou o e-mail no Streamlit Cloud?

Se você já usava o e-mail na versão antiga, os três valores provavelmente estão
em **Streamlit Cloud → Manage app → Settings → Secrets** (os mesmos
`EMAIL_REMETENTE`, `EMAIL_SENHA` e `EMAIL_DESTINATARIO`). O painel novo lê esses
secrets automaticamente.

1. Abra **Sinais → 📧 Alertas por e-mail**.
2. Clique em **Enviar e-mail de teste**.
3. Se chegar, o caminho do painel está pronto; não precisa criar GitHub Secrets.
4. Deixe a aba aberta durante o pregão para ele verificar a cada atualização.

### Para rodar com o painel fechado (GitHub Actions)

Os valores são os mesmos que estão no Streamlit Cloud; só precisam ser copiados
para o GitHub.

1. Se ainda não tem, crie uma **Senha de app** no Gmail (é diferente da senha
   normal; exige verificação em duas etapas): Conta Google → Segurança → Senhas
   de app.
2. No GitHub, abra **Settings → Secrets and variables → Actions** e cadastre:
   - `EMAIL_REMETENTE` — sua conta Gmail que envia.
   - `EMAIL_SENHA` — a senha de app de 16 caracteres.
   - `EMAIL_DESTINATARIO` — para onde o alerta vai.
   - Opcional: `SMTP_HOST` (padrão `smtp.gmail.com`), `SMTP_PORT` (padrão `587`),
     `APP_URL` (link do painel no rodapé do e-mail) e `BRAPI_TOKEN` (mesmo token
     opcional do app, para corrigir a barra do Yahoo).
3. Abra a aba **Actions → Alertas de movimento → Run workflow** e marque
   **“Enviar apenas um e-mail de teste”**. Se chegar, o agendamento já está ativo.

### Testar localmente

```bash
cp .env.example .env
# preencha EMAIL_REMETENTE, EMAIL_SENHA e EMAIL_DESTINATARIO
python notificar.py --teste-email --forcar
python notificar.py --dry-run --forcar   # mostra o e-mail sem enviar
```

Observações:

- O GitHub pode atrasar alguns minutos o horário agendado; para um alerta de
  swing trade isso não muda a decisão.
- Em repositório público, o GitHub desativa agendamentos após 60 dias sem
  atividade. Se isso acontecer, rode o workflow manualmente ou faça um commit.
- Quer alertar também quando o **modo esticado** ligar sem movimento de 2 %?
  Basta acrescentar essa condição em `notificar.py`; hoje o gatilho é só ±2 %.

---

## Estrutura

```
estrategia_acumulacao/
├── app.py                     # navegação (Sinais, Análise, A Regra)
├── config.py                  # ativos, limiares, delta, prêmio mínimo
├── notificar.py               # alerta por e-mail (painel e GitHub Actions)
├── requirements.txt
├── .github/workflows/
│   └── alertas.yml            # agenda de 15 min durante o pregão
├── modulos/
│   ├── mercado.py             # histórico yfinance + consenso de preço
│   ├── cotacoes.py            # Yahoo + brapi + Status Invest, com horário
│   ├── estrategia.py          # regra por ativo (viés, strike, prêmio)
│   ├── alertas.py             # SMTP + template do e-mail
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
| `TICKERS` | BOVA11, VALE3, ITSA4, PRIO3 | ativos monitorados |
| `MA_PERIODO` | 50 | média que define o viés |
| `DELTA_PUT_RENDA` | -0,15 | risco alvo da PUT no modo renda (~15 % de exercício) |
| `DELTA_CALL_RENDA` | +0,15 | risco alvo da CALL coberta no modo renda |
| `PREMIO_MIN_RENDA_PCT` | 0,4 % | prêmio mínimo por ciclo no modo renda |
| `CALL_STRIKE_OTM_ESTICADO_PCT` | 3 % | distância da CALL no modo esticado |
| `PREMIO_MIN_ESTICADO_PCT` | 1,0 % | prêmio mínimo por ciclo no modo esticado |
| `DIST_MA_ESTICADO_PCT` | 8 % | distância acima da MA50 que conta como “esticado” |
| `RSI_ESTICADO` | 70 | RSI que conta como “esticado” |
| `GANHO_5D_ESTICADO_PCT` | 5 % | ganho de 5 dias que conta como “esticado” |
| `ESTICADO_MIN_CRITERIOS` | 2 | critérios necessários para ligar o modo esticado |
| `LIMIAR_QUEDA_PUT` | -1,5 % | queda que aciona prioridade |
| `LIMIAR_ALTA_CALL` | +2,0 % | alta que aciona prioridade |
| `ALERTA_MOVIMENTO_PCT` | ±2,0 % | variação que dispara e-mail, na direção da MA50 |
| `DIAS_VENCIMENTO_PADRAO` | 30 | prazo usado no cálculo |

---

## Testes

```bash
pip install pytest
pytest tests/ -q
```

Cobrem: viés PUT/CALL, modo renda × esticado, bloqueio por prêmio baixo,
strike por delta de PUT e CALL, escolha da série real, seleção/estado dos
alertas por e-mail e correção da barra corrompida.

---

## Aviso

Ferramenta de leitura de mercado, **não** é recomendação de investimento.
Prêmios são teóricos (Black-Scholes com volatilidade histórica); o que vale é o
**bid real** no Home Broker. Opções têm risco de perda relevante.
