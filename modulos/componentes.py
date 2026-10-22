"""Shared UI helpers — formatting only (no data access, no personal state)."""

from __future__ import annotations


def prob_badge(prob: float | None) -> str:
    """Format an exercise probability as a coloured emoji badge."""
    if prob is None:
        return "—"
    pct = prob * 100
    emoji = "🔴" if pct >= 50 else ("🟡" if pct >= 25 else "🟢")
    return f"{emoji} {pct:.1f}%"


def distancia_strike(tipo: str, preco_spot: float, strike: float) -> str:
    """Format the % distance from spot to strike with an OTM/ITM label."""
    pct = (preco_spot - strike) / strike * 100
    if tipo == "PUT":
        otm = pct >= 0
        sinal = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
    else:
        otm = pct <= 0
        sinal = f"+{abs(pct):.1f}%" if pct <= 0 else f"-{abs(pct):.1f}%"
    return f"{sinal} {'OTM' if otm else 'ITM'}"
