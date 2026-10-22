"""Strategy constants — pure market-signal app (no personal data stored).

The app never records positions, cash or contributions. It only reads market
data and answers: "which option would I sell on this asset today, and at what
strike?".
"""

# Shown in the sidebar so it is obvious which version is deployed
APP_VERSION: str = "2026-10-21 · cotação 3 fontes"

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

# Strike selection
# PUT: strike whose delta is closest to this (≈ 25 % exercise chance)
DELTA_PUT_ALVO: float = -0.25
# CALL: fixed 3 % OTM above spot
CALL_STRIKE_OTM_PCT: float = 0.03

# Minimum theoretical premium per share, as a fraction of spot price
# (0.6 % per 30-day cycle). Percentual so low-priced stocks are not penalised.
PREMIO_MIN_PCT: float = 0.006

# Default days to expiry used for the premium/strike math
DIAS_VENCIMENTO_PADRAO: int = 30

# Dashboard auto-refresh interval (seconds)
REFRESH_INTERVAL_SECONDS: int = 120
