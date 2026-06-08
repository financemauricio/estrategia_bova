# Monitor Estratégia ETF + Opções

Painel de controle para a estratégia de acumulação com BOVA11, IVV (NYSE) e HASH11 via venda sistemática de opções.

---

## Funcionalidades

- Preço em tempo real de BOVA11, IVV e HASH11 (atualiza a cada 5 minutos)
- MA50 do BOVA11 para decisão (MA100/MA200 como referência visual)
- Motor de regras com os 5 passos da estratégia e recomendação automática (PUT ATM ou CALL 3% OTM)
- Alerta por e-mail quando queda > 1,5 % ou alta > 2 %
- Registro de posições em ETFs, aportes mensais e operações com opções
- Calculadora de aporte para rebalancear a carteira (alvo 70/20/10)
- Gráfico de candlestick do BOVA11 com médias móveis
- Controle de caixa integrado: prêmios, recompras, exercícios e aportes
- Funciona em qualquer dispositivo (celular, tablet, PC)

---

## Pré-requisitos

- Python 3.11+
- Conta gratuita no [Supabase](https://supabase.com) (banco de dados)
- Conta gratuita no [Streamlit Community Cloud](https://share.streamlit.io) (hospedagem)
- Repositório no [GitHub](https://github.com) (privado recomendado)
- Conta de e-mail Gmail com [App Password](https://myaccount.google.com/apppasswords) habilitado

---

## Setup Local (teste antes do deploy)

### 1. Clonar / copiar o projeto

```bash
# A pasta já está em:
cd /home/geoia/Documentos/codigos/acao/Validacao_planilha/estrategia_acumulacao
```

### 2. Criar ambiente virtual isolado

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configurar o Supabase

1. Acesse [supabase.com](https://supabase.com) → **New project**
2. Anote o nome do projeto e a senha do banco
3. Vá em **Project Settings → Database → Connection string → URI**
4. Copie a string no formato: `postgresql://postgres:[senha]@[host]:5432/postgres`

### 4. Configurar credenciais locais

```bash
# Criar arquivo de secrets para Streamlit
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edite `.streamlit/secrets.toml` com seus dados:

```toml
DATABASE_URL = "postgresql://postgres:SUA_SENHA@SEU_HOST:5432/postgres"

EMAIL_REMETENTE = "seu@gmail.com"
EMAIL_SENHA = "xxxx xxxx xxxx xxxx"   # App Password do Gmail
EMAIL_DESTINATARIO = "seu@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
```

### 5. Rodar localmente

```bash
source .venv/bin/activate
streamlit run app.py
```

O app abrirá em `http://localhost:8501`.  
As tabelas do banco são criadas automaticamente na primeira execução.

---

## Deploy no Streamlit Cloud (acesso pelo celular)

### 1. Criar repositório no GitHub

```bash
cd estrategia_acumulacao   # ou a pasta raiz
git init
git add .
git commit -m "feat: monitor estrategia ETF opcoes"
gh repo create estrategia-acumulacao --private --source=. --push
```

> O arquivo `.gitignore` já exclui `.env`, `secrets.toml` e dados locais.

### 2. Conectar ao Streamlit Cloud

1. Acesse [share.streamlit.io](https://share.streamlit.io)
2. Clique em **New app**
3. Selecione o repositório e o arquivo `app.py`
4. Em **Advanced settings → Secrets**, cole o conteúdo do seu `secrets.toml`:

```toml
DATABASE_URL = "postgresql://postgres:SUA_SENHA@SEU_HOST:5432/postgres"
EMAIL_REMETENTE = "seu@gmail.com"
EMAIL_SENHA = "xxxx xxxx xxxx xxxx"
EMAIL_DESTINATARIO = "seu@gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = "587"
```

5. Clique em **Deploy**

### 3. Restringir acesso (somente você)

1. No painel do Streamlit Cloud → **Settings → Sharing**
2. Selecione **Only specific people can view this app**
3. Adicione seu e-mail

---

## Estrutura do Projeto

```
estrategia_acumulacao/
├── app.py                     # Entry point — navegação entre páginas
├── config.py                  # Constantes da estratégia (edite aqui para ajustar regras)
├── requirements.txt
├── .gitignore
├── .env.example
├── .streamlit/
│   ├── config.toml            # Tema escuro
│   └── secrets.toml.example   # Template de credenciais
├── modulos/
│   ├── banco.py               # Banco de dados (Supabase PostgreSQL)
│   ├── mercado.py             # Dados de mercado (yfinance)
│   ├── estrategia.py          # Motor de regras (5 passos)
│   ├── alertas.py             # Alertas por e-mail
│   ├── bs.py                  # Black-Scholes e Selic
│   └── componentes.py         # Helpers de UI compartilhados
└── pages/
    ├── 1_Dashboard.py         # Painel principal (atualização automática)
    ├── 2_Carteira.py          # Opções, ETFs, caixa e aportes (página central)
    └── 3_Analise_Semanal.py   # Checklist semanal e gráfico com MAs
```

---

## Ajustar Parâmetros da Estratégia

Edite apenas `config.py`:

| Constante | Valor padrão | Significado |
|---|---|---|
| `ALOCACAO_ALVO` | 70/20/10 | Alvo por ticker |
| `CAIXA_MIN_PCT` | 5 % | Caixa mínimo do patrimônio |
| `CALL_STRIKE_OTM_PCT` | 3 % | Strike da CALL acima do preço |
| `LIMIAR_QUEDA_PUT` | -1,5 % | Queda que aciona prioridade PUT |
| `LIMIAR_ALTA_CALL` | +2,0 % | Alta que aciona prioridade CALL |
| `MA_PERIODO` | 50 dias | Média móvel usada na decisão |
| `MA_VISUALIZACAO` | 50/100/200 | MAs exibidas nos gráficos |
| `LIMIAR_RECOMPRA_PCT` | 2 % | Movimento favorável para alerta de recompra |
| `APORTE_MENSAL` | R$ 5.000 | Sugestão padrão de aporte |
| `REFRESH_INTERVAL_SECONDS` | 300 s | Frequência de atualização do dashboard |

---

## Fluxo de Caixa

O saldo em **Caixa e Movimentações** (página Carteira) reflete o dinheiro líquido na corretora:

| Evento | Movimento |
|---|---|
| Venda de opção (prêmio) | ENTRADA automática |
| Recompra de opção | SAÍDA automática (bloqueada se saldo insuficiente) |
| PUT exercida | SAÍDA = strike × quantidade (compra das ações) |
| CALL exercida | ENTRADA = strike × quantidade (venda das ações) |
| Aporte registrado | ENTRADA do valor total + SAÍDA do valor investido em ETFs |
| Depósito/saque manual | ENTRADA ou SAÍDA via formulário de caixa |

PUTs abertas reservam `strike × quantidade` do caixa (exibido como **Comprometido**).
Se o caixa for insuficiente para exercício ou recompra, registre um aporte ou depósito antes de encerrar a posição.

---

## Atualizar o App Após Mudanças

```bash
git add .
git commit -m "ajuste: ..."
git push
```

O Streamlit Cloud detecta o push e atualiza automaticamente em ~1 minuto.
