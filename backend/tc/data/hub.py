"""DataHub: bündelt alle Quellen, cached, protokolliert Lücken und liefert Quellen + Zeitstempel."""
from __future__ import annotations

import logging
import pickle
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..config import CACHE_DIR, JsonStore, Settings, iso, parse_iso, utcnow
from .base import GapLog, PriceSeries, Quote, classify_quality, suffix
from .rest import FMP, Ecb, Finnhub, Fred

log = logging.getLogger(__name__)


class DataHub:
    def __init__(self, settings: Settings, provider: Any, store: JsonStore, demo: bool = False,
                 use_rest: bool = True) -> None:
        self.s = settings
        self.p = provider
        self.store = store
        self.demo = demo
        self.gaps = GapLog()
        self.finnhub = Finnhub() if use_rest and not demo else None
        self.fmp = FMP() if use_rest and not demo else None
        self.fred = Fred() if use_rest and not demo else None
        self.ecb = Ecb() if use_rest and not demo else None
        self._daily: dict[str, PriceSeries] = {}
        self._intra: dict[str, PriceSeries] = {}
        self._fund = store.load("cache/fundamentals", {})
        self._events = store.load("cache/events", {})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ Kurse
    def load_daily(self, symbols: list[str]) -> dict[str, PriceSeries]:
        need = [s for s in dict.fromkeys(symbols) if s not in self._daily]
        if need:
            got = self.p.histories(need, period=self.s.get("data.history_period", "2y"), interval="1d")
            for s in need:
                ps = got.get(s)
                if ps is None or not ps.ok:
                    cached = self._cache_read(s, "1d")
                    if cached is not None:
                        self.gaps.add(s, "Tageskurse", "Abruf fehlgeschlagen – letzter gespeicherter Stand wird angezeigt")
                        ps = cached
                    else:
                        self.gaps.add(s, "Tageskurse", "keine Daten von der Quelle")
                        ps = PriceSeries(s, pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]),
                                         "", "nicht verfügbar", utcnow())
                else:
                    self._cache_write(ps, "1d")
                self._daily[s] = ps
        return {s: self._daily[s] for s in symbols if s in self._daily}

    def load_intraday(self, symbols: list[str]) -> dict[str, PriceSeries]:
        need = [s for s in dict.fromkeys(symbols) if s not in self._intra]
        if need:
            got = self.p.histories(need, period="5d", interval=self.s.get("data.intraday_interval", "15m"))
            for s in need:
                ps = got.get(s)
                if ps is None or not ps.ok:
                    self.gaps.add(s, "Intraday-Kurse", "nicht verfügbar – Tagesschlusskurs wird verwendet")
                    ps = PriceSeries(s, pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]),
                                     "", "nicht verfügbar", utcnow())
                self._intra[s] = ps
        return {s: self._intra[s] for s in symbols if s in self._intra}

    def daily(self, s: str) -> PriceSeries | None:
        return self._daily.get(s)

    def quote(self, s: str) -> Quote:
        """Letzter verfügbarer Kurs: Intraday bevorzugt, sonst Tagesschluss. Nie geschätzt."""
        now = utcnow()
        d = self._daily.get(s)
        i = self._intra.get(s)
        prev = None
        if d is not None and d.ok:
            closes = d.df["Close"].dropna()
            # Vortagesschluss = letzter Schluss vor dem heutigen (UTC-)Handelstag des Intraday-Kurses
            prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        crypto = suffix(s) == "crypto"
        if i is not None and i.ok and (d is None or not d.ok or i.last_time >= d.last_time):
            if d is not None and d.ok:
                closes = d.df["Close"].dropna()
                day_i = i.last_time.date()
                before = closes[closes.index.date < day_i]
                prev = float(before.iloc[-1]) if len(before) else prev
            q = classify_quality(i.last_time, now, True, i.demo, crypto)
            return Quote(s, i.last, d.currency if d and d.currency else i.currency, i.last_time, i.source, q, prev)
        if d is not None and d.ok:
            q = classify_quality(d.last_time, now, False, d.demo, crypto)
            return Quote(s, d.last, d.currency, d.last_time, d.source, q, prev)
        return Quote(s, None, "", None, "nicht verfügbar", "nicht verfügbar", None)

    # ------------------------------------------------------- Fundamentaldaten
    def fundamentals(self, s: str, refresh: bool = True) -> dict[str, Any]:
        cached = self._fund.get(s)
        max_age = timedelta(hours=float(self.s.get("data.fundamentals_refresh_hours", 20)))
        fresh = cached and parse_iso(cached.get("_fetched")) and utcnow() - parse_iso(cached["_fetched"]) < max_age
        if cached and (fresh or not refresh):
            return cached
        try:
            f = self.p.fundamentals(s)
            f["_source"] = getattr(self.p, "name", "?")
            if self.fmp and self.fmp.enabled and "." not in s:
                try:
                    extra = self.fmp.ratios_ttm(s)
                    for k, v in extra.items():
                        if f.get(k) is None and v is not None:
                            f[k] = v
                            f["_source"] += " + FMP"
                except Exception as e:  # noqa: BLE001
                    self.gaps.add(s, "FMP-Kennzahlen", e)
            f["_fetched"] = iso(utcnow())
            self._fund[s] = f
            return f
        except Exception as e:  # noqa: BLE001
            self.gaps.add(s, "Fundamentaldaten", e)
            if cached:
                cached["_stale"] = True
                return cached
            return {"_source": "nicht verfügbar", "_fetched": None}

    def events(self, s: str, max_age_hours: float = 3.0) -> dict[str, Any]:
        cached = self._events.get(s)
        if cached and parse_iso(cached.get("_fetched")) and utcnow() - parse_iso(cached["_fetched"]) < timedelta(hours=max_age_hours):
            return cached
        try:
            ev = self.p.events(s)
            if self.finnhub and self.finnhub.enabled:
                try:
                    fn = self.finnhub.company_news(s)
                    seen = {n["title"] for n in ev["news"]}
                    ev["news"] += [n for n in fn if n["title"] not in seen]
                except Exception as e:  # noqa: BLE001
                    self.gaps.add(s, "Finnhub-News", e)
            ev["_fetched"] = iso(utcnow())
            self._events[s] = ev
            return ev
        except Exception as e:  # noqa: BLE001
            self.gaps.add(s, "Nachrichten/Ereignisse", e)
            return cached or {"news": [], "upgrades": [], "earnings": [], "calendar": {}, "_fetched": None}

    def market_news(self) -> list[dict]:
        if self.finnhub and self.finnhub.enabled:
            try:
                return self.finnhub.market_news()
            except Exception as e:  # noqa: BLE001
                self.gaps.add("MARKT", "Marktnachrichten (Finnhub)", e)
        return []

    # ------------------------------------------------------------------ Makro
    def macro(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.ecb:
            for key, (_, label) in self.ecb.SERIES.items():
                try:
                    obs = self.ecb.latest(key)
                    if obs:
                        out[key] = {"label": label, "value": obs[0][1], "date": obs[0][0],
                                    "prev": obs[1][1] if len(obs) > 1 else None, "source": self.ecb.name,
                                    "url": "https://data.ecb.europa.eu/"}
                except Exception as e:  # noqa: BLE001
                    self.gaps.add("MAKRO", label, e)
        if self.fred and self.fred.enabled:
            series = {"us_fed_upper": ("DFEDTARU", "Fed-Leitzins (Obergrenze)", False),
                      "us_cpi": ("CPIAUCSL", "US-Inflation (CPI, J/J)", True),
                      "us_unemployment": ("UNRATE", "US-Arbeitslosenquote", False)}
            for key, (sid, label, yoy) in series.items():
                try:
                    obs = self.fred.observations(sid, limit=15)
                    if not obs:
                        continue
                    if yoy and len(obs) >= 13:
                        val = (obs[0][1] / obs[12][1] - 1) * 100
                        prev = (obs[1][1] / obs[13][1] - 1) * 100 if len(obs) >= 14 else None
                    else:
                        val, prev = obs[0][1], (obs[1][1] if len(obs) > 1 else None)
                    out[key] = {"label": label, "value": round(val, 2), "date": obs[0][0], "prev": prev,
                                "source": self.fred.name, "url": f"https://fred.stlouisfed.org/series/{sid}"}
                except Exception as e:  # noqa: BLE001
                    self.gaps.add("MAKRO", label, e)
        elif not self.demo:
            self.gaps.add("MAKRO", "US-Leitzins/CPI/Arbeitsmarkt", "FRED_API_KEY nicht gesetzt")
        return out

    def release_calendar(self) -> list[dict]:
        if self.fred and self.fred.enabled:
            try:
                return self.fred.release_dates()
            except Exception as e:  # noqa: BLE001
                self.gaps.add("KALENDER", "FRED-Veröffentlichungstermine", e)
        return []

    # ------------------------------------------------------------------ Cache
    def _cache_write(self, ps: PriceSeries, interval: str) -> None:
        if ps.demo:
            return
        try:
            with open(CACHE_DIR / f"{_safe(ps.symbol)}_{interval}.pkl", "wb") as f:
                pickle.dump({"df": ps.df, "currency": ps.currency, "source": ps.source, "fetched": ps.fetched_at}, f)
        except OSError as e:
            log.debug("cache write %s", e)

    def _cache_read(self, symbol: str, interval: str) -> PriceSeries | None:
        p = CACHE_DIR / f"{_safe(symbol)}_{interval}.pkl"
        if not p.exists():
            return None
        try:
            with open(p, "rb") as f:
                d = pickle.load(f)
            return PriceSeries(symbol, d["df"], d["currency"], d["source"] + " (Cache)", d["fetched"])
        except Exception:  # noqa: BLE001
            return None

    def persist(self) -> None:
        self.store.save("cache/fundamentals", self._fund)
        # Ereignis-Cache schlank halten
        self.store.save("cache/events", self._events)


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)
