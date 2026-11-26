"""REST-Quellen mit offiziellen APIs: Finnhub, Financial Modeling Prep, FRED (US-Notenbank St. Louis), EZB.

Alle Schlüssel kommen ausschließlich aus Umgebungsvariablen (GitHub Secrets) und landen nie im Frontend.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from ..config import env

log = logging.getLogger(__name__)
TIMEOUT = 20
UA = {"User-Agent": "trading-center/1.0 (private Planspiel)"}


def _get(url: str, params: dict | None = None, retries: int = 2) -> requests.Response:
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT, headers=UA)
            if r.status_code == 429:
                time.sleep(2 + 3 * i)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1 + i)
    raise RuntimeError(f"{url}: {last}")


class Finnhub:
    """News, Earnings-Kalender, Analystenkonsens. Free: 60 Calls/Min (Anbieterangabe)."""
    name = "Finnhub"
    base = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        self.key = env("FINNHUB_API_KEY")

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def _q(self, path: str, **params: Any) -> Any:
        params["token"] = self.key
        r = _get(f"{self.base}{path}", params)
        time.sleep(1.05)  # Limit respektieren
        return r.json()

    def company_news(self, symbol: str, days: int = 7) -> list[dict]:
        if "." in symbol:  # Free-Plan deckt im Wesentlichen US-Werte ab
            return []
        to = date.today()
        frm = to - timedelta(days=days)
        data = self._q("/company-news", symbol=symbol, **{"from": frm.isoformat(), "to": to.isoformat()})
        out = []
        for n in (data or [])[:15]:
            out.append({"title": n.get("headline"), "url": n.get("url"),
                        "published": datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc).isoformat(),
                        "publisher": n.get("source"), "summary": (n.get("summary") or "")[:300] or None,
                        "via": self.name})
        return out

    def market_news(self) -> list[dict]:
        data = self._q("/news", category="general")
        out = []
        for n in (data or [])[:25]:
            out.append({"title": n.get("headline"), "url": n.get("url"),
                        "published": datetime.fromtimestamp(n.get("datetime", 0), tz=timezone.utc).isoformat(),
                        "publisher": n.get("source"), "summary": (n.get("summary") or "")[:300] or None,
                        "via": self.name})
        return out

    def earnings_calendar(self, days: int = 21) -> list[dict]:
        frm = date.today()
        to = frm + timedelta(days=days)
        data = self._q("/calendar/earnings", **{"from": frm.isoformat(), "to": to.isoformat()})
        return (data or {}).get("earningsCalendar", []) or []


class FMP:
    """Financial Modeling Prep – Fundamentaldaten als Ergänzung. Free: 250 Calls/Tag (Anbieterangabe)."""
    name = "Financial Modeling Prep"
    base = "https://financialmodelingprep.com/stable"

    def __init__(self) -> None:
        self.key = env("FMP_API_KEY")

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def ratios_ttm(self, symbol: str) -> dict[str, Any]:
        r = _get(f"{self.base}/ratios-ttm", {"symbol": symbol, "apikey": self.key}).json()
        row = r[0] if isinstance(r, list) and r else {}
        return {
            "pe": row.get("priceToEarningsRatioTTM"),
            "pb": row.get("priceToBookRatioTTM"),
            "peg": row.get("priceToEarningsGrowthRatioTTM"),
            "profit_margin": row.get("netProfitMarginTTM"),
            "operating_margin": row.get("operatingProfitMarginTTM"),
            "debt_to_equity": row.get("debtToEquityRatioTTM"),
            "dividend_yield": row.get("dividendYieldTTM"),
        }


class Fred:
    """FRED-API der Federal Reserve Bank of St. Louis (kostenloser Schlüssel)."""
    name = "FRED (St. Louis Fed)"
    base = "https://api.stlouisfed.org/fred"
    RELEASES = {10: ("US-Verbraucherpreise (CPI)", "inflation"),
                50: ("US-Arbeitsmarktbericht (Employment Situation)", "labor"),
                53: ("US-BIP (GDP)", "gdp"),
                54: ("US-Konsumausgaben & PCE-Preisindex", "inflation")}

    def __init__(self) -> None:
        self.key = env("FRED_API_KEY")

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def observations(self, series: str, limit: int = 15) -> list[tuple[str, float]]:
        r = _get(f"{self.base}/series/observations", {"series_id": series, "api_key": self.key,
                                                      "file_type": "json", "sort_order": "desc", "limit": limit}).json()
        out = []
        for o in r.get("observations", []):
            try:
                out.append((o["date"], float(o["value"])))
            except (ValueError, KeyError):
                continue
        return out

    def release_dates(self, days: int = 60) -> list[dict]:
        out = []
        start = date.today()
        end = start + timedelta(days=days)
        for rid, (title, cat) in self.RELEASES.items():
            try:
                r = _get(f"{self.base}/release/dates", {"release_id": rid, "api_key": self.key, "file_type": "json",
                                                        "realtime_start": start.isoformat(), "realtime_end": end.isoformat(),
                                                        "include_release_dates_with_no_data": "true",
                                                        "sort_order": "asc", "limit": 10}).json()
                for d in r.get("release_dates", []):
                    if start.isoformat() <= d["date"] <= end.isoformat():
                        out.append({"date": d["date"], "title": title, "category": cat,
                                    "source": f"https://fred.stlouisfed.org/releases/calendar?rid={rid}"})
            except Exception as e:  # noqa: BLE001
                log.info("FRED release %s: %s", rid, e)
        return out


class Ecb:
    """Statistik-API der EZB (ohne Schlüssel)."""
    name = "EZB Data Portal"
    base = "https://data-api.ecb.europa.eu/service/data"
    SERIES = {
        "deposit_rate": ("FM/B.U2.EUR.4F.KR.DFR.LEV", "EZB-Einlagesatz"),
        "hicp": ("ICP/M.U2.N.000000.4.ANR", "Inflation Euroraum (HVPI, J/J)"),
    }

    def latest(self, key: str, n: int = 13) -> list[tuple[str, float]]:
        path, _ = self.SERIES[key]
        r = _get(f"{self.base}/{path}", {"lastNObservations": n, "format": "csvdata"})
        rows = list(csv.DictReader(io.StringIO(r.text)))
        out = []
        for row in rows:
            try:
                out.append((row["TIME_PERIOD"], float(row["OBS_VALUE"])))
            except (KeyError, ValueError):
                continue
        out.sort(key=lambda x: x[0], reverse=True)
        return out
