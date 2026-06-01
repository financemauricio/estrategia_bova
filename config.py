"""Strategy constants — edit here to adjust rules without touching business logic."""

# Target portfolio allocation (must sum to 1.0)
ALOCACAO_ALVO: dict[str, float] = {
    "BOVA11": 0.70,
    "IVVB11": 0.20,
    "HASH11": 0.10,
}

# yfinance tickers (Brazilian exchange suffix .SA)
TICKERS: dict[str, str] = {
    "BOVA11": "BOVA11.SA",
    "IVVB11": "IVVB11.SA",
    "HASH11": "HASH11.SA",
}

# Minimum cash as fraction of total portfolio
CAIXA_MIN_PCT: float = 0.05

# CALL strike distance above current price (3 %)
CALL_STRIKE_OTM_PCT: float = 0.03

# Thresholds that trigger maximum-priority alerts
LIMIAR_QUEDA_PUT: float = -0.015   # daily drop >= 1.5 % → PUT priority
LIMIAR_ALTA_CALL: float = 0.020    # daily rise >= 2.0 % → CALL priority

# Moving-average window used for strategy decisions (days)
MA_PERIODO: int = 25

# Additional MAs shown on charts for visual reference only
MA_VISUALIZACAO: list[int] = [25, 50, 200]

# Fixed monthly contribution amount (BRL)
APORTE_MENSAL: float = 5_000.0

# Dashboard auto-refresh interval (seconds)
REFRESH_INTERVAL_SECONDS: int = 300

# History window for fetching prices (must be > largest MA in MA_VISUALIZACAO)
HISTORICO_PERIODO: str = "300d"
