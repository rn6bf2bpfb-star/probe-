"""Yahoo Finance über yfinance (inoffizielle Schnittstelle, Börsenkurse i. d. R. 15–20 Min. verzögert)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .base import PriceSeries, guess_currency

log = logging.getLogger(__name__)
SOURCE = "Yahoo Finance"
FIELDS = ["Open", "High", "Low", "Close", "Volume"]


def _yf():
    import yfinance as yf  # erst bei Bedarf importieren (Tests laufen ohne)
    return yf


def _normalize(df: pd.DataFrame, daily: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=FIELDS)
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(-1)
    keep = [c for c in FIELDS if c in df.columns]
    df = df[keep]
    for c in FIELDS:
        if c not in df.columns:
            df[c] = np.nan
    idx = pd.to_datetime(df.index)
    if daily:
        # Tagesbalken auf das Handelsdatum (Börsenzeitzone) normieren: 00:00 UTC dieses Datums
        idx = pd.DatetimeIndex(pd.to_datetime([d.date() for d in idx])).tz_localize("UTC")
    else:
        idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=["Close"])


class YahooProvider:
    name = SOURCE

    def __init__(self, pause: float = 0.35) -> None:
        self.pause = pause

    # ---------- Kurse ----------
    def histories(self, symbols: list[str], period: str = "2y", interval: str = "1d") -> dict[str, PriceSeries]:
        yf = _yf()
        out: dict[str, PriceSeries] = {}
        now = datetime.now(timezone.utc)
        for chunk in [symbols[i:i + 40] for i in range(0, len(symbols), 40)]:
            try:
                raw = yf.download(chunk, period=period, interval=interval, group_by="ticker",
                                  auto_adjust=False, threads=True, progress=False)
            except Exception as e:  # noqa: BLE001
                log.warning("yf.download fehlgeschlagen: %s", e)
                raw = None
            for s in chunk:
                df = pd.DataFrame()
                if raw is not None and not raw.empty:
                    try:
                        if isinstance(raw.columns, pd.MultiIndex):
                            lv0 = raw.columns.get_level_values(0)
                            df = raw[s] if s in lv0 else pd.DataFrame()
                        else:
                            df = raw
                    except KeyError:
                        df = pd.DataFrame()
                df = _normalize(df, daily=interval == "1d")
                out[s] = PriceSeries(s, df, guess_currency(s), SOURCE, now)
            time.sleep(self.pause)
        return out

    # ---------- Fundamentaldaten ----------
    def fundamentals(self, symbol: str) -> dict[str, Any]:
        yf = _yf()
        t = yf.Ticker(symbol)
        info: dict[str, Any] = {}
        try:
            info = t.info or {}
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"info: {e}") from e
        f: dict[str, Any] = {
            "name": info.get("longName") or info.get("shortName"),
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "peg": info.get("trailingPegRatio") or info.get("pegRatio"),
            "eps": info.get("trailingEps"),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "debt_to_equity": (info.get("debtToEquity") / 100.0) if info.get("debtToEquity") is not None else None,
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "dividend_yield": _div_yield(info),
            "payout_ratio": info.get("payoutRatio"),
            "beta": info.get("beta"),
            "analyst_target_mean": info.get("targetMeanPrice"),
            "analyst_target_low": info.get("targetLowPrice"),
            "analyst_target_high": info.get("targetHighPrice"),
            "analyst_count": info.get("numberOfAnalystOpinions"),
            "recommendation_mean": info.get("recommendationMean"),
            "recommendation_key": info.get("recommendationKey"),
            "website": info.get("website"),
            "summary": (info.get("longBusinessSummary") or "")[:600] or None,
        }
        # Mehrjahreszahlen
        try:
            inc = t.income_stmt
            if inc is not None and not inc.empty:
                f["revenue_history"] = _row(inc, ["Total Revenue", "Operating Revenue"])
                f["net_income_history"] = _row(inc, ["Net Income", "Net Income Common Stockholders"])
        except Exception as e:  # noqa: BLE001
            log.debug("income_stmt %s: %s", symbol, e)
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                eq = _row(bs, ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"])
                ta = _row(bs, ["Total Assets"])
                if eq and ta and ta[0]["value"]:
                    f["equity_ratio"] = eq[0]["value"] / ta[0]["value"]
        except Exception as e:  # noqa: BLE001
            log.debug("balance_sheet %s: %s", symbol, e)
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                f["fcf_history"] = _row(cf, ["Free Cash Flow"])
        except Exception as e:  # noqa: BLE001
            log.debug("cashflow %s: %s", symbol, e)
        time.sleep(self.pause)
        return {k: _py(v) for k, v in f.items()}

    # ---------- Ereignisse ----------
    def events(self, symbol: str) -> dict[str, Any]:
        yf = _yf()
        t = yf.Ticker(symbol)
        out: dict[str, Any] = {"news": [], "upgrades": [], "earnings": [], "calendar": {}}
        try:
            for n in (t.news or [])[:15]:
                item = _news_item(n)
                if item:
                    out["news"].append(item)
        except Exception as e:  # noqa: BLE001
            log.debug("news %s: %s", symbol, e)
        try:
            ud = t.upgrades_downgrades
            if ud is not None and not ud.empty:
                ud = ud.sort_index(ascending=False).head(10)
                for idx, r in ud.iterrows():
                    out["upgrades"].append({
                        "date": pd.Timestamp(idx).tz_localize(None).date().isoformat() if pd.Timestamp(idx).tzinfo else pd.Timestamp(idx).date().isoformat(),
                        "firm": r.get("Firm"), "to": r.get("ToGrade"), "from": r.get("FromGrade"),
                        "action": r.get("Action")})
        except Exception as e:  # noqa: BLE001
            log.debug("upgrades %s: %s", symbol, e)
        try:
            ed = t.get_earnings_dates(limit=8)
            if ed is not None and not ed.empty:
                for idx, r in ed.iterrows():
                    out["earnings"].append({
                        "date": pd.Timestamp(idx).tz_convert("UTC").isoformat() if pd.Timestamp(idx).tzinfo else pd.Timestamp(idx).isoformat(),
                        "eps_estimate": _py(r.get("EPS Estimate")),
                        "eps_reported": _py(r.get("Reported EPS")),
                        "surprise_pct": _py(r.get("Surprise(%)"))})
        except Exception as e:  # noqa: BLE001
            log.debug("earnings %s: %s", symbol, e)
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, (list, tuple)) and ed:
                    out["calendar"]["earnings_date"] = str(ed[0])
                for k_src, k_dst in (("Ex-Dividend Date", "ex_dividend_date"), ("Dividend Date", "dividend_date")):
                    if cal.get(k_src):
                        out["calendar"][k_dst] = str(cal[k_src])
        except Exception as e:  # noqa: BLE001
            log.debug("calendar %s: %s", symbol, e)
        time.sleep(self.pause)
        return out


def _div_yield(info: dict) -> float | None:
    dy = info.get("dividendYield")
    if dy is None:
        return info.get("trailingAnnualDividendYield")
    # yfinance liefert seit 2025 teils Prozentwerte (z. B. 1.2 statt 0.012)
    return dy / 100.0 if dy > 0.5 else dy


def _row(df: pd.DataFrame, names: list[str]) -> list[dict] | None:
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            vals = []
            for col, v in s.items():
                vals.append({"date": pd.Timestamp(col).date().isoformat(), "value": float(v)})
            vals.sort(key=lambda x: x["date"], reverse=True)
            return vals[:5] or None
    return None


def _news_item(n: dict) -> dict | None:
    c = n.get("content") if isinstance(n.get("content"), dict) else n
    title = c.get("title")
    if not title:
        return None
    url = None
    for key in ("canonicalUrl", "clickThroughUrl"):
        if not url and isinstance(c.get(key), dict):
            url = c[key].get("url")
    url = url or c.get("link")
    pub = c.get("pubDate") or c.get("displayTime")
    if not pub and c.get("providerPublishTime"):
        pub = datetime.fromtimestamp(c["providerPublishTime"], tz=timezone.utc).isoformat()
    prov = c.get("provider", {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
    return {"title": title, "url": url, "published": pub, "publisher": prov,
            "summary": (c.get("summary") or "")[:300] or None, "via": SOURCE}


def _py(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (f != f or f in (float("inf"), float("-inf"))) else f
    if isinstance(v, np.integer):
        return int(v)
    return v
