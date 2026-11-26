"""Synthetische Daten – NUR für Tests und den Demo-Modus. Überall als DEMO gekennzeichnet."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from .base import PriceSeries, guess_currency

SOURCE = "DEMO (synthetisch)"


def _seed(symbol: str) -> int:
    return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)


def make_ohlcv(symbol: str, days: int = 520, end: datetime | None = None, scenario: str | None = None,
               start_price: float | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(_seed(symbol))
    end = (end or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    idx = pd.bdate_range(end=end, periods=days, tz="UTC")
    drift = {"bull": 0.0009, "bear": -0.0009, "flat": 0.0, "crash": 0.0003}.get(scenario or "", rng.normal(0.0003, 0.0006))
    vol = 0.004 if (start_price and start_price < 10) else rng.uniform(0.012, 0.028)
    rets = rng.normal(drift, vol, days)
    if scenario == "crash":
        rets[-15:] = rng.normal(-0.03, 0.02, 15)
    if scenario == "breakout":
        rets[:-10] = rng.normal(0, vol * 0.5, days - 10)
        rets[-10:] = rng.normal(0.012, vol * 0.5, 10)
    p0 = start_price or float(rng.uniform(20, 400))
    close = p0 * np.exp(np.cumsum(rets))
    opn = close * np.exp(rng.normal(0, vol / 3, days))
    high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, vol / 2, days)))
    low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, vol / 2, days)))
    volume = rng.lognormal(13, 0.4, days)
    if scenario == "breakout":
        volume[-3:] *= 3.5
    return pd.DataFrame({"Open": opn, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


class SyntheticProvider:
    name = SOURCE

    def __init__(self, scenarios: dict[str, str] | None = None, now: datetime | None = None) -> None:
        self.scenarios = scenarios or {}
        self.now = now

    # Wechselkurse brauchen plausible Größenordnungen, sonst wird die EUR-Umrechnung im Demo unbrauchbar
    FX_START = {"EURUSD=X": 1.10, "EURGBP=X": 0.85, "EURCHF=X": 0.94, "EURDKK=X": 7.46}

    def histories(self, symbols: list[str], period: str = "2y", interval: str = "1d") -> dict[str, PriceSeries]:
        now = self.now or datetime.now(timezone.utc)
        out = {}
        for s in symbols:
            sp = self.FX_START.get(s)
            sc = "flat" if sp else self.scenarios.get(s)
            if interval == "1d":
                df = make_ohlcv(s, end=now, scenario=sc, start_price=sp)
            else:
                daily = make_ohlcv(s, end=now, scenario=sc, start_price=sp)
                df = _intraday_from(daily, now, s)
            out[s] = PriceSeries(s, df, guess_currency(s), SOURCE, now, demo=True)
        return out

    def fundamentals(self, symbol: str) -> dict[str, Any]:
        rng = np.random.default_rng(_seed(symbol) + 7)
        sectors = ["Technology", "Industrials", "Financial Services", "Healthcare", "Consumer Cyclical",
                   "Consumer Defensive", "Energy", "Utilities", "Basic Materials", "Communication Services"]
        return {
            "name": f"{symbol} (Demo AG)", "currency": guess_currency(symbol), "sector": sectors[_seed(symbol) % len(sectors)],
            "industry": "Demo-Industrie", "country": "Germany" if symbol.endswith(".DE") else "United States",
            "market_cap": float(rng.uniform(5e9, 3e11)), "pe": float(rng.uniform(8, 45)), "forward_pe": float(rng.uniform(8, 35)),
            "pb": float(rng.uniform(0.8, 9)), "peg": float(rng.uniform(0.6, 3)), "eps": float(rng.uniform(1, 12)),
            "revenue_growth": float(rng.normal(0.07, 0.1)), "earnings_growth": float(rng.normal(0.08, 0.2)),
            "profit_margin": float(rng.uniform(-0.05, 0.3)), "operating_margin": float(rng.uniform(0, 0.35)),
            "roe": float(rng.uniform(-0.05, 0.35)), "debt_to_equity": float(rng.uniform(0.1, 2.0)),
            "free_cashflow": float(rng.uniform(-1e9, 2e10)), "operating_cashflow": float(rng.uniform(1e8, 3e10)),
            "dividend_yield": float(rng.uniform(0, 0.05)), "equity_ratio": float(rng.uniform(0.15, 0.6)),
            "beta": float(rng.uniform(0.6, 1.6)), "analyst_count": int(rng.integers(0, 30)),
            "recommendation_mean": float(rng.uniform(1.5, 3.5)),
            "revenue_history": [{"date": f"{2025 - i}-12-31", "value": float(1e10 * (1.06 ** (-i)))} for i in range(4)],
            "net_income_history": [{"date": f"{2025 - i}-12-31", "value": float(1e9 * (1.05 ** (-i)))} for i in range(4)],
        }

    def events(self, symbol: str) -> dict[str, Any]:
        now = self.now or datetime.now(timezone.utc)
        return {"news": [{"title": f"DEMO-Meldung: {symbol} meldet Quartalszahlen über Erwartungen",
                          "url": None, "published": (now - timedelta(hours=5)).isoformat(),
                          "publisher": "DEMO", "summary": None, "via": SOURCE}],
                "upgrades": [], "earnings": [], "calendar": {}}


def _intraday_from(daily: pd.DataFrame, now: datetime, symbol: str) -> pd.DataFrame:
    rng = np.random.default_rng(_seed(symbol) + 99)
    last_close = float(daily["Close"].iloc[-1])
    idx = pd.date_range(end=now.replace(second=0, microsecond=0), periods=40, freq="15min", tz="UTC")
    rets = rng.normal(0, 0.002, len(idx))
    close = last_close * np.exp(np.cumsum(rets))
    opn = np.r_[last_close, close[:-1]]
    high = np.maximum(opn, close) * 1.001
    low = np.minimum(opn, close) * 0.999
    return pd.DataFrame({"Open": opn, "High": high, "Low": low, "Close": close,
                         "Volume": rng.lognormal(10, 0.3, len(idx))}, index=idx)
