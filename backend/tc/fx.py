"""Währungsumrechnung in EUR auf Basis abgerufener Wechselkurse (nie geschätzt)."""
from __future__ import annotations

from .config import Settings
from .data.hub import DataHub


class FX:
    def __init__(self, hub: DataHub, settings: Settings) -> None:
        self.hub = hub
        self.map: dict[str, str] = settings.universe.get("fx", {}) or {}
        hub.load_daily(list(self.map.values()))
        hub.load_intraday(list(self.map.values()))

    def per_eur(self, ccy: str) -> float | None:
        """Einheiten der Fremdwährung je 1 EUR."""
        if ccy in ("EUR", "", None):
            return 1.0
        base = "GBP" if ccy == "GBp" else ccy
        sym = self.map.get(base)
        if not sym:
            return None
        q = self.hub.quote(sym)
        return q.price

    def to_eur(self, amount: float | None, ccy: str) -> float | None:
        if amount is None:
            return None
        if ccy == "GBp":
            amount = amount / 100.0
        rate = self.per_eur(ccy)
        if not rate:
            return None
        return amount / rate

    def from_eur(self, amount_eur: float, ccy: str) -> float | None:
        rate = self.per_eur(ccy)
        if not rate:
            return None
        v = amount_eur * rate
        return v * 100.0 if ccy == "GBp" else v
