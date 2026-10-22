"""Strategy constants — pure market-signal app (no personal data stored).

The app never records positions, cash or contributions. It only reads market
data and answers: "which option would I sell on this asset today, and at what
strike?".
"""

# Shown in the sidebar so it is obvious which version is deployed
APP_VERSION: str = "2026-10-22 · modo renda + esticado"

# Assets monitored (name → yfinance ticker)
TICKERS: dict[str, str] = {
    "BOVA11": "BOVA11.SA",
    "VALE3":  "VALE3.SA",
    "ITSA4":  "ITSA4.SA",
    "PRIO3":  "PRIO3.SA",
}

# Moving averages
MA_PERIODO: int = 50            # decision MA (bias)
MA_VISUALIZACAO: list[int] = [50, 100, 200]
HISTORICO_PERIODO: str = "400d"

# Daily moves that flag maximum priority (in the direction of the bias)
LIMIAR_QUEDA_PUT: float = -0.015   # drop >= 1.5 % → PUT priority
LIMIAR_ALTA_CALL: float = 0.020    # rise >= 2.0 % → CALL priority

# ---------------------------------------------------------------------------
# Modo renda (padrão): longe do dinheiro, prêmio menor, pouca chance de exercício
# ---------------------------------------------------------------------------
# PUT: delta alvo. -0.15 ≈ 15 % de chance de exercício por ciclo.
DELTA_PUT_RENDA: float = -0.15
# CALL coberta: delta alvo. +0.15 ≈ 15 % de chance de exercício por ciclo.
DELTA_CALL_RENDA: float = 0.15
# Prêmio mínimo no modo renda, como fração do spot (0.4 % por ciclo).
PREMIO_MIN_RENDA_PCT: float = 0.004

# ---------------------------------------------------------------------------
# Modo esticado (exceção): o ativo subiu muito; vender CALL mais perto
# ---------------------------------------------------------------------------
# Strike da CALL no modo esticado: 3 % acima do preço (regra antiga).
CALL_STRIKE_OTM_ESTICADO_PCT: float = 0.03
# Prêmio mínimo no modo esticado: 1.0 % do spot por ciclo.
PREMIO_MIN_ESTICADO_PCT: float = 0.010

# Gatilhos do modo esticado. Precisa de ESTICADO_MIN_CRITERIOS entre 3.
# Distância acima da MA50 (8 %) OU RSI >= 70 OU ganho de 5 dias >= 5 %.
DIST_MA_ESTICADO_PCT: float = 0.08
RSI_ESTICADO: float = 70.0
GANHO_5D_ESTICADO_PCT: float = 0.05
ESTICADO_MIN_CRITERIOS: int = 2

# Default days to expiry used for the premium/strike math
DIAS_VENCIMENTO_PADRAO: int = 30

# Dashboard auto-refresh interval (seconds)
REFRESH_INTERVAL_SECONDS: int = 120
