"""Offline-Tests (keine Netzwerkzugriffe). Start: cd backend && python -m pytest ../tests -q"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TC_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TC_SITE_DIR", str(tmp_path / "site"))
    for k in ("TELEGRAM_BOT_TOKEN", "NTFY_TOPIC", "SMTP_HOST", "ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    import importlib
    import tc.config
    importlib.reload(tc.config)
    for m in ["tc.data.hub", "tc.fx", "tc.depot", "tc.signals", "tc.alerts", "tc.pipeline", "tc.risk", "tc.econ_calendar"]:
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return tmp_path


# ------------------------------------------------------------- Indikatoren
def test_indicators_bounds_and_causality():
    from tc.data.synthetic import make_ohlcv
    from tc.indicators import compute_all, rsi
    df = make_ohlcv("TEST", 400)
    r = rsi(df["Close"]).dropna()
    assert r.between(0, 100).all()
    full = rsi(df["Close"])
    part = rsi(df["Close"].iloc[:300])
    assert np.allclose(full.iloc[:300].dropna(), part.dropna())  # keine Zukunftsdaten
    t = compute_all(df)
    for k in ("sma20", "sma50", "sma200", "rsi", "macd", "atr", "adx", "rvol", "trend"):
        assert k in t


def test_support_resistance_sides():
    from tc.data.synthetic import make_ohlcv
    from tc.indicators import support_resistance
    df = make_ohlcv("SR", 300)
    sr = support_resistance(df)
    last = df["Close"].iloc[-1]
    assert all(z["level"] < last for z in sr["supports"])
    assert all(z["level"] > last for z in sr["resistances"])


# ---------------------------------------------------------------- Signale
def _settings():
    from tc.config import Settings
    return Settings()


def test_no_signal_from_single_indicator():
    from tc import analyst as an
    s = _settings()
    t = {"bars": 300, "last": 100, "sma20": 99, "sma50": 98, "sma200": 90, "trend": "seitwärts", "rsi": 55,
         "macd_hist": 0.1, "perf_3m": 0.0, "atr": 2, "vol_60": 0.25, "sr": {"supports": [], "resistances": []}}
    te = {"score": 90, "dirs": {"momentum": 1}, "points": [], "coverage": 1.0}  # künstlich hoher Score, nur 1 Gruppe
    fe = {"score": 50, "dirs": {}, "points": [], "coverage": 0.0}
    ne = {"score": 50, "dirs": {"news": 0, "analysts": 0, "earnings": 0}, "points": [], "items": [], "calendar": {}}
    sig = an.build_signal("X", "X AG", {"price": 100, "quality": "verzögert"}, t, te, fe, ne, {"verdict": "positiv"}, s, "short")
    assert sig["raw_rating"] in ("BUY", "STRONG BUY")
    assert sig["rating"] == "HOLD"  # Bestätigung fehlt
    assert "Faktorgruppe" in sig["rating_note"]


def test_signal_contains_required_fields():
    from tc import analyst as an
    from tc.data.synthetic import make_ohlcv
    from tc.indicators import compute_all
    s = _settings()
    df = make_ohlcv("BULL", 400, scenario="bull")
    t = compute_all(df)
    t["last"] = float(df["Close"].iloc[-1])
    te = an.tech_eval(t)
    fe = an.fund_eval({"revenue_growth": 0.15, "earnings_growth": 0.2, "pe": 15, "operating_margin": 0.25, "roe": 0.2,
                       "equity_ratio": 0.5, "debt_to_equity": 0.3, "free_cashflow": 1e9, "market_cap": 2e10}, {})
    ne = an.news_eval({"news": [], "upgrades": [], "earnings": []}, datetime.now(timezone.utc))
    for h in ("short", "long"):
        sig = an.build_signal("B", "B AG", {"price": t["last"], "quality": "verzögert", "time": "x", "source": "y"}, t, te, fe, ne,
                              {"verdict": "neutral"}, s, h)
        for k in ("symbol", "quote", "time", "reason", "fundamental", "technical", "news", "levels", "uncertainty", "invalidation", "counterarguments"):
            assert k in sig, k
        assert sig["rating"] in an.RATINGS


def test_news_classification():
    from tc.analyst import classify_news
    n = classify_news({"title": "Company beats estimates, raises guidance after record quarter"})
    assert n["tone"] == "positiv" and "Quartalszahlen" in n["categories"]
    n = classify_news({"title": "Regulator opens antitrust probe; shares plunge"})
    assert n["tone"] == "negativ" and "Politik/Regulierung" in n["categories"]


# ------------------------------------------------------------------ Depot
class FixedProvider:
    """Liefert vorgegebene Tages- und 15-Minuten-Balken."""
    name = "TEST"

    def __init__(self, daily: dict, intra: dict):
        self.daily, self.intra = daily, intra

    def histories(self, symbols, period="2y", interval="1d"):
        from tc.data.base import PriceSeries, guess_currency
        src = self.daily if interval == "1d" else self.intra
        out = {}
        for s in symbols:
            df = src.get(s, pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]))
            out[s] = PriceSeries(s, df, guess_currency(s), "TEST", datetime.now(timezone.utc))
        return out

    def fundamentals(self, s):
        return {"name": s, "sector": "Technology"}

    def events(self, s):
        return {"news": [], "upgrades": [], "earnings": [], "calendar": {}}


def _bars(start: datetime, prices: list[tuple], freq="15min"):
    idx = pd.date_range(start, periods=len(prices), freq=freq, tz="UTC")
    return pd.DataFrame(prices, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def _hub_and_depot(daily, intra):
    from tc.config import JsonStore, Settings
    from tc.data.hub import DataHub
    from tc.depot import Depot
    from tc.fx import FX
    s = Settings()
    st = JsonStore()
    hub = DataHub(s, FixedProvider(daily, intra), st, demo=True, use_rest=False)
    hub.load_daily(list(daily))
    hub.load_intraday(list(intra))
    return s, hub, Depot(st, s), FX(hub, s)


def test_market_order_fills_next_bar_open_no_lookahead(tmp_env, monkeypatch):
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    daily = {"SAP.DE": _bars(t0 - timedelta(days=30), [(100, 101, 99, 100, 1e5)] * 30, "1D")}
    intra = {"SAP.DE": _bars(t0, [(100, 101, 99, 100.5, 1e3), (110, 111, 109, 110, 1e3), (120, 121, 119, 120, 1e3)])}
    s, hub, dep, fx = _hub_and_depot(daily, intra)
    monkeypatch.setenv("TC_NOW", (t0 + timedelta(minutes=50)).isoformat())
    order = dep.place({"type": "order", "side": "BUY", "symbol": "SAP.DE", "qty": 10, "order_type": "MARKET",
                       "created_at": (t0 + timedelta(minutes=5)).isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    assert order["status"] == "ausgeführt"
    # Erster Balken NACH 09:05 ist 09:15 mit Eröffnung 110 (nicht 100 von 09:00)
    assert order["fill"]["price"] == pytest.approx(110 * 1.0005)
    assert dep.d["positions"]["SAP.DE"]["qty"] == 10
    assert dep.d["cash"] == pytest.approx(10000 - 10 * 110 * 1.0005 - 1.0)


def test_limit_stop_bracket_oco_and_tax(tmp_env, monkeypatch):
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    daily = {"SAP.DE": _bars(t0 - timedelta(days=30), [(100, 101, 99, 100, 1e5)] * 30, "1D")}
    bars = [(100, 100, 100, 100, 1), (100, 100, 94, 95, 1),      # Limit 95 wird erreicht
            (96, 130, 96, 129, 1),                              # Take-Profit 120 erreicht → Stop storniert
            (129, 129, 80, 85, 1)]
    intra = {"SAP.DE": _bars(t0, bars)}
    s, hub, dep, fx = _hub_and_depot(daily, intra)
    monkeypatch.setenv("TC_NOW", (t0 + timedelta(hours=2)).isoformat())
    o = dep.place({"side": "BUY", "symbol": "SAP.DE", "qty": 50, "order_type": "LIMIT", "limit": 95, "sl": 90, "tp": 120,
                   "created_at": (t0 + timedelta(minutes=1)).isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    assert o["status"] == "ausgeführt" and o["fill"]["price"] == 95
    kids = [x for x in dep.d["orders"] if x.get("parent") == o["id"]]
    assert len(kids) == 2
    dep.process(hub, fx)
    tp = next(k for k in kids if k["type"] == "LIMIT")
    sl = next(k for k in kids if k["type"] == "STOP")
    assert tp["status"] == "ausgeführt" and tp["fill"]["price"] == 120
    assert sl["status"] == "storniert"
    assert "SAP.DE" not in dep.d["positions"]
    tx = dep.d["transactions"][-1]
    gain = 50 * 120 - 1 - (50 * 95 + 1)
    assert tx["realized_eur"] == pytest.approx(gain)
    # 1.000 € Freibetrag, Rest mit 26,375 %
    assert tx["tax_eur"] == pytest.approx((gain - 1000) * 0.25 * 1.055)


def test_stop_loss_gap_fills_at_open(tmp_env, monkeypatch):
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    daily = {"SAP.DE": _bars(t0 - timedelta(days=30), [(100, 101, 99, 100, 1e5)] * 30, "1D")}
    intra = {"SAP.DE": _bars(t0, [(100, 100, 100, 100, 1), (100, 100, 100, 100, 1), (80, 82, 78, 81, 1)])}
    s, hub, dep, fx = _hub_and_depot(daily, intra)
    monkeypatch.setenv("TC_NOW", (t0 + timedelta(hours=1)).isoformat())
    b = dep.place({"side": "BUY", "symbol": "SAP.DE", "qty": 10, "order_type": "MARKET", "created_at": t0.isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    st = dep.place({"side": "SELL", "symbol": "SAP.DE", "qty": 10, "order_type": "STOP", "stop": 90,
                    "created_at": (t0 + timedelta(minutes=16)).isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    assert st["status"] == "ausgeführt"
    assert st["fill"]["price"] == pytest.approx(80 * (1 - 0.0005))  # Kurslücke: schlechter als Stop
    assert dep.d["tax"]["loss_pot_stocks"] > 0


def test_rejections(tmp_env, monkeypatch):
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    daily = {"SAP.DE": _bars(t0 - timedelta(days=30), [(100, 101, 99, 100, 1e5)] * 30, "1D")}
    intra = {"SAP.DE": _bars(t0, [(100, 100, 100, 100, 1)] * 3)}
    s, hub, dep, fx = _hub_and_depot(daily, intra)
    monkeypatch.setenv("TC_NOW", (t0 + timedelta(hours=1)).isoformat())
    assert dep.place({"side": "SELL", "symbol": "SAP.DE", "qty": 1}, {"SAP.DE"})["status"] == "abgelehnt"  # kein Bestand
    assert dep.place({"side": "BUY", "symbol": "FOO", "qty": 1}, {"SAP.DE"})["status"] == "abgelehnt"     # kein Kurs
    big = dep.place({"side": "BUY", "symbol": "SAP.DE", "qty": 1000, "created_at": t0.isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    assert big["status"] == "abgelehnt" and "Cash" in big["reason"]
    amt = dep.place({"side": "BUY", "symbol": "SAP.DE", "amount_eur": 1001, "created_at": t0.isoformat()}, {"SAP.DE"})
    dep.process(hub, fx)
    assert amt["status"] == "ausgeführt" and dep.d["cash"] == pytest.approx(10000 - 1001, abs=0.05)


def test_fx_conversion_usd_and_pence(tmp_env):
    t0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    d = lambda p: _bars(t0 - timedelta(days=5), [(p, p, p, p, 1)] * 5, "1D")
    s, hub, dep, fx = _hub_and_depot({"EURUSD=X": d(1.25), "EURGBP=X": d(0.8)}, {})
    assert fx.to_eur(125, "USD") == pytest.approx(100)
    assert fx.to_eur(8000, "GBp") == pytest.approx(100)  # 8000 Pence = 80 GBP = 100 EUR


# ------------------------------------------------------- Signal-Statistik
def test_signal_evaluation_counts_failures(tmp_env):
    from tc.config import JsonStore, Settings
    from tc.data.hub import DataHub
    from tc.signals import SignalBook
    s = Settings()
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    prices = [100.0] + [100 - i for i in range(1, 30)]   # fällt nach dem Kaufsignal
    daily = {"X": _bars(t0, [(p, p, p, p, 1) for p in prices], "1D")}
    hub = DataHub(s, FixedProvider(daily, {}), JsonStore(), demo=True, use_rest=False)
    hub.load_daily(["X"])
    book = SignalBook(JsonStore(), s)
    sig = {"symbol": "X", "name": "X", "horizon": "short", "rating": "BUY", "score": 70, "time": "2026-09-01T12:00:00Z",
           "quote": {"price": 100.0, "currency": "EUR", "quality": "verzögert"}, "levels": {"risk_level": 95, "scenario_base": 110}}
    assert book.record(sig) is not None
    assert book.record(sig) is None  # gleiche Einstufung → kein Duplikat
    book.evaluate(hub, {})
    r = book.history[0]
    assert r["evaluations"]["5"]["hit"] is False and r["stop_hit"]
    st = book.stats()
    assert st["failures"] and st["rows"][0]["hit_rate"] == 0


def test_alert_dedupe(tmp_env):
    from tc import alerts as al
    from tc.config import JsonStore, Settings
    c = al.AlertCenter(JsonStore(), Settings())
    a = al.make_alert("x", "HIGH", "SAP.DE", "SAP", "h", "r", "risk", "todo", None, "src", None, "TAG", "key1")
    assert c.add(a) and not c.add(dict(a))
    c.dispatch(send=False)
    c.save()
    c2 = al.AlertCenter(JsonStore(), Settings())
    assert not c2.add(al.make_alert("x", "HIGH", "SAP.DE", "SAP", "h", "r", "risk", "todo", None, "src", None, "TAG", "key1"))
    txt = al.to_text(a)
    assert "BENACHRICHTIGUNG – keine Kaufempfehlung" in txt and "Was ist zu tun?" in txt


def test_quote_quality_labels():
    from tc.data.base import classify_quality
    now = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)
    assert classify_quality(now - timedelta(minutes=20), now, True, False) == "verzögert"
    assert classify_quality(now - timedelta(days=1), now, False, False) == "Schlusskurs"
    assert classify_quality(now - timedelta(days=10), now, False, False) == "veraltet"
    assert classify_quality(None, now, False, False) == "nicht verfügbar"


# ------------------------------------------------------- Gesamtlauf (Demo)
@pytest.mark.parametrize("report", ["morning", "intraday", "evening"])
def test_full_demo_run_with_commands(tmp_env, report):
    from tc.data.synthetic import SyntheticProvider
    from tc.pipeline import Run
    from tc.config import STATE_DIR
    (STATE_DIR / "inbox").mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "inbox" / "a.json").write_text(json.dumps({"type": "order", "side": "BUY", "symbol": "SAP.DE", "amount_eur": 2000,
                                                             "order_type": "MARKET", "created_at": "2026-01-01T00:00:00Z", "sl": 1, "strategy": "Test"}))
    (STATE_DIR / "inbox" / "b.json").write_text(json.dumps({"type": "price_alert_add", "symbol": "SAP.DE", "direction": "above", "level": 0.01}))
    prov = SyntheticProvider(scenarios={"NVDA": "breakout", "SAP.DE": "bull", "BAYN.DE": "crash"})
    res = Run(demo=True, provider=prov, report=report, send=False).execute()
    assert res["symbols"] > 50
    assert all(c["ok"] for c in res["commands"]), res["commands"]
    site = Path(os.environ["TC_SITE_DIR"]) / "data"
    for f in ("meta", "market", "signals", "screener", "depot", "risk", "alerts", "calendar", "track", "reports_index"):
        data = json.loads((site / f"{f}.json").read_text())
        assert data, f
    depot = json.loads((site / "depot.json").read_text())
    assert depot["valuation"]["positions"], "Kauf wurde nicht ausgeführt"
    assert any(o["note"] == "Stop-Loss" for o in depot["orders"])
    alerts = json.loads((site / "alerts.json").read_text())["alerts"]
    assert any(a["kind"] == "price_level" for a in alerts)
    assert any(a["kind"] == "order_filled" for a in alerts)
    rep = json.loads((site / "reports_index.json").read_text())["reports"]
    assert rep and rep[0]["kind"] == report
    # Nichts darf NaN enthalten (gültiges JSON fürs Frontend)
    for p in site.rglob("*.json"):
        assert "NaN" not in p.read_text()
    # Zweiter Lauf: Zustand bleibt erhalten, keine doppelten Alerts
    res2 = Run(demo=True, provider=prov, report="none", send=False).execute()
    alerts2 = json.loads((site / "alerts.json").read_text())["alerts"]
    assert sum(1 for a in alerts2 if a["kind"] == "price_level") == 1
    assert json.loads((site / "depot.json").read_text())["valuation"]["positions"]
