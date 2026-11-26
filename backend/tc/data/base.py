"""Gemeinsame Datenstrukturen der Datenschicht."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

SUFFIX_CCY = {
    ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR",
    ".BR": "EUR", ".VI": "EUR", ".HE": "EUR", ".L": "GBp", ".SW": "CHF", ".CO": "DKK",
    ".ST": "SEK", ".OL": "NOK",
}


def suffix(symbol: str) -> str:
    if "=" in symbol or symbol.startswith("^"):
        return "^"
    if "-" in symbol and symbol.split("-")[-1] in ("EUR", "USD"):
        return "crypto"
    if "." in symbol:
        return "." + symbol.rsplit(".", 1)[1]
    return ""


def guess_currency(symbol: str) -> str:
    s = suffix(symbol)
    if s == "crypto":
        return symbol.split("-")[-1]
    if s == "^":
        if symbol in ("^GDAXI", "^MDAXI", "^STOXX50E", "^FCHI", "^AEX"):
            return "EUR"
        return "USD"
    return SUFFIX_CCY.get(s, "USD")


@dataclass
class PriceSeries:
    symbol: str
    df: pd.DataFrame                 # Open, High, Low, Close, Volume – Index UTC
    currency: str
    source: str
    fetched_at: datetime
    demo: bool = False

    @property
    def ok(self) -> bool:
        return self.df is not None and not self.df.empty and self.df["Close"].notna().sum() > 0

    @property
    def last_time(self) -> datetime | None:
        if not self.ok:
            return None
        ts = self.df["Close"].dropna().index[-1]
        return ts.to_pydatetime()

    @property
    def last(self) -> float | None:
        if not self.ok:
            return None
        return float(self.df["Close"].dropna().iloc[-1])


@dataclass
class Quote:
    """Letzter verfügbarer Kurs inkl. Herkunft und Aktualität."""
    symbol: str
    price: float | None
    currency: str
    time: datetime | None
    source: str
    quality: str                     # "verzögert", "Schlusskurs", "veraltet", "nicht verfügbar", "DEMO"
    prev_close: float | None = None

    def as_dict(self) -> dict[str, Any]:
        from ..config import iso
        return {"symbol": self.symbol, "price": self.price, "currency": self.currency,
                "time": iso(self.time), "source": self.source, "quality": self.quality,
                "prev_close": self.prev_close}


def classify_quality(last_time: datetime | None, now: datetime, intraday: bool, demo: bool,
                     crypto: bool = False) -> str:
    if demo:
        return "DEMO"
    if last_time is None:
        return "nicht verfügbar"
    age = now - last_time
    if intraday and age <= timedelta(minutes=45):
        return "nahezu Echtzeit" if crypto else "verzögert"
    if age <= timedelta(days=4):
        return "Schlusskurs" if not intraday or age > timedelta(hours=3) else "verzögert"
    return "veraltet"


@dataclass
class GapLog:
    items: list[dict] = field(default_factory=list)

    def add(self, symbol: str, what: str, reason: str) -> None:
        self.items.append({"symbol": symbol, "what": what, "reason": str(reason)[:200],
                           "time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
