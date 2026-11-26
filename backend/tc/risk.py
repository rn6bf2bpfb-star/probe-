"""Risikomanagement: Kennzahlen des Depots, Drawdown, Diversifikation und Warnungen."""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

import math
from collections import Counter
from datetime import timedelta
from statistics import mean
from typing import Any

import numpy as np
import pandas as pd

from .config import Settings, parse_iso, utcnow
from .data.hub import DataHub


def equity_metrics(equity: list[dict], rf_annual: float = 0.0) -> dict[str, Any]:
    if len(equity) < 2:
        return {"note": "Noch zu wenig Verlauf für Kennzahlen."}
    s = pd.Series([p["value"] for p in equity], index=pd.to_datetime([p["time"] for p in equity])).sort_index()
    daily = s.groupby(s.index.date).last()
    peak = daily.cummax()
    dd = daily / peak - 1
    max_dd = float(dd.min())
    # längste Verlustphase (Tage unter altem Hoch)
    longest = cur = 0
    for v in dd.values:
        cur = cur + 1 if v < 0 else 0
        longest = max(longest, cur)
    rets = daily.pct_change().dropna()
    out = {"max_drawdown": max_dd, "current_drawdown": float(dd.iloc[-1]), "longest_underwater_days": longest,
           "days": int(len(daily)),
           "drawdown_series": [{"date": str(k), "dd": float(v)} for k, v in dd.tail(365).items()]}
    if len(rets) >= 10:
        vol = float(rets.std() * math.sqrt(252))
        ann = float((1 + rets.mean()) ** 252 - 1)
        out["volatility"] = vol
        out["sharpe"] = (ann - rf_annual) / vol if vol > 0 else None
        out["sharpe_note"] = "Annualisiert aus Tagesrenditen; bei weniger als 60 Tagen wenig aussagekräftig."
    return out


def trade_stats(transactions: list[dict]) -> dict[str, Any]:
    sells = [t for t in transactions if t["side"] == "SELL"]
    out: dict[str, Any] = {"trades_closed": len(sells), "orders_total": len(transactions)}
    if sells:
        wins = [t["realized_eur"] for t in sells if t["realized_eur"] > 0]
        losses = [t["realized_eur"] for t in sells if t["realized_eur"] <= 0]
        out.update({"win_rate": len(wins) / len(sells), "avg_win": mean(wins) if wins else None,
                    "avg_loss": mean(losses) if losses else None,
                    "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
                    "best": max(t["realized_eur"] for t in sells), "worst": min(t["realized_eur"] for t in sells)})
        streak = maxstreak = 0
        for t in sells:
            streak = streak + 1 if t["realized_eur"] <= 0 else 0
            maxstreak = max(maxstreak, streak)
        cur = 0
        for t in reversed(sells):
            if t["realized_eur"] <= 0:
                cur += 1
            else:
                break
        out["max_losing_streak"] = maxstreak
        out["current_losing_streak"] = cur
    # Strategien
    by: dict[str, dict] = {}
    for t in sells:
        k = t.get("strategy") or "manuell"
        b = by.setdefault(k, {"strategy": k, "n": 0, "wins": 0, "realized_eur": 0.0, "fees_eur": 0.0})
        b["n"] += 1
        b["wins"] += 1 if t["realized_eur"] > 0 else 0
        b["realized_eur"] += t["realized_eur"]
    for t in transactions:
        k = t.get("strategy") or "manuell"
        if k in by:
            by[k]["fees_eur"] += t.get("fees_eur", 0)
    for b in by.values():
        b["win_rate"] = b["wins"] / b["n"] if b["n"] else None
    out["by_strategy"] = sorted(by.values(), key=lambda x: -x["realized_eur"])
    week_ago = utcnow() - timedelta(days=7)
    out["trades_last_7d"] = sum(1 for t in transactions if parse_iso(t["time"]) and parse_iso(t["time"]) >= week_ago)
    return out


def diversification(val: dict) -> dict[str, Any]:
    pos = val["positions"]
    total = val["total_eur"] or 1
    weights = [p["value_eur"] / total for p in pos]
    hhi = sum(w * w for w in weights)
    sectors = Counter()
    countries = Counter()
    for p in pos:
        sectors[p["sector"]] += p["value_eur"] / total
        countries[p["country"]] += p["value_eur"] / total
    eff = 1 / hhi if hhi > 0 else 0
    return {"hhi": hhi, "effective_positions": eff, "n_positions": len(pos),
            "cash_weight": val["cash_eur"] / total,
            "sectors": [{"name": k, "weight": v} for k, v in sectors.most_common()],
            "countries": [{"name": k, "weight": v} for k, v in countries.most_common()]}


def correlations(hub: DataHub, symbols: list[str]) -> dict[str, Any]:
    cols = {}
    for s in symbols:
        d = hub.daily(s)
        if d is not None and d.ok:
            cols[s] = d.df["Close"].dropna()
    if len(cols) < 2:
        return {"pairs": []}
    df = pd.DataFrame(cols)
    df.index = df.index.normalize()
    df = df.groupby(level=0).last().ffill(limit=3).pct_change(fill_method=None).tail(120)
    c = df.corr(min_periods=40)
    pairs = []
    for i, a in enumerate(c.columns):
        for b in c.columns[i + 1:]:
            v = c.loc[a, b]
            if not pd.isna(v):
                pairs.append({"a": a, "b": b, "corr": float(v)})
    pairs.sort(key=lambda x: -x["corr"])
    return {"pairs": pairs[:15], "window": "120 Handelstage"}


def warnings(val: dict, div: dict, ts: dict, em: dict, tech: dict[str, dict], depot: dict, s: Settings) -> list[dict]:
    w: list[dict] = []
    total = val["total_eur"] or 1
    mw = float(s.get("risk.max_position_weight", 0.2))
    for p in val["positions"]:
        if p["weight"] > mw:
            w.append({"level": "HIGH" if p["weight"] > mw * 1.5 else "MEDIUM", "kind": "concentration", "symbol": p["symbol"],
                      "text": f"{p['name']} macht {_pc(p['weight'], 0)} des Depots aus (Grenze {_pc(mw, 0)}) – Klumpenrisiko."})
        vol = (tech.get(p["symbol"]) or {}).get("vol_60")
        if vol and vol > float(s.get("risk.high_volatility", 0.6)):
            w.append({"level": "MEDIUM", "kind": "volatility", "symbol": p["symbol"],
                      "text": f"{p['name']}: ungewöhnlich hohe Volatilität ({_pc(vol, 0)} annualisiert)."})
    ms = float(s.get("risk.max_sector_weight", 0.4))
    for sec in div["sectors"]:
        if sec["weight"] > ms and sec["name"] not in ("ETF",):
            w.append({"level": "MEDIUM", "kind": "sector", "text": f"Sektor {sec['name']} mit {_pc(sec['weight'], 0)} übergewichtet (Grenze {_pc(ms, 0)})."})
    # Risiko je offener Position anhand Stop-Orders
    mr = float(s.get("risk.max_risk_per_trade", 0.02))
    stops = {o["symbol"]: o["stop"] for o in depot["orders"] if o["status"] == "offen" and o["side"] == "SELL" and o["type"] == "STOP"}
    for p in val["positions"]:
        price = p["quote"].get("price")
        if price is None:
            continue
        stop = stops.get(p["symbol"])
        if stop is None:
            w.append({"level": "LOW", "kind": "no_stop", "symbol": p["symbol"],
                      "text": f"{p['name']}: kein Stop-Loss gesetzt – Verlust nicht begrenzt."})
            continue
        risk_eur = max(0.0, (price - stop) / price) * p["value_eur"]
        if risk_eur / total > mr:
            w.append({"level": "MEDIUM", "kind": "risk_per_trade", "symbol": p["symbol"],
                      "text": f"{p['name']}: Abstand zum Stop entspricht {_pc(risk_eur / total, 1)} des Depots (Grenze {_pc(mr, 0)})."})
    if ts.get("current_losing_streak", 0) >= int(s.get("risk.losing_streak", 3)):
        w.append({"level": "MEDIUM", "kind": "losing_streak", "text": f"{ts['current_losing_streak']} Verlusttrades in Folge – Strategie und Positionsgröße überprüfen, Pause erwägen."})
    if ts.get("trades_last_7d", 0) > int(s.get("risk.max_trades_per_week", 10)):
        w.append({"level": "MEDIUM", "kind": "overtrading", "text": f"{ts['trades_last_7d']} Ausführungen in 7 Tagen – erhöhtes Risiko durch zu häufiges Trading (Kosten!)."})
    cdd = em.get("current_drawdown")
    if cdd is not None:
        if cdd <= -float(s.get("risk.drawdown_alarm", 0.2)):
            w.append({"level": "HIGH", "kind": "drawdown", "text": f"Depot {_pc(cdd, 1)} unter dem Höchststand."})
        elif cdd <= -float(s.get("risk.drawdown_warn", 0.1)):
            w.append({"level": "MEDIUM", "kind": "drawdown", "text": f"Depot {_pc(cdd, 1)} unter dem Höchststand."})
    if div["n_positions"] and div["effective_positions"] < 4 and div["cash_weight"] < 0.5:
        w.append({"level": "LOW", "kind": "diversification", "text": f"Effektiv nur {_n(div['effective_positions'], 1)} Positionen – geringe Streuung."})
    return w


def risk_score(val: dict, div: dict, em: dict, tech: dict[str, dict]) -> dict:
    """Eingegangenes Risiko: gewichtete Volatilität und Konzentration."""
    total = val["total_eur"] or 1
    wv = 0.0
    for p in val["positions"]:
        v = (tech.get(p["symbol"]) or {}).get("vol_60") or 0.3
        wv += p["value_eur"] / total * v
    score = min(100, wv * 120 + div["hhi"] * 40)
    return {"weighted_volatility": wv, "score": round(score),
            "level": "niedrig" if score < 25 else "mittel" if score < 50 else "hoch",
            "return_per_risk": (val["pnl_pct"] / wv) if wv > 0 else None,
            "note": "Gewichtete Volatilität der Positionen (Cash = 0). Rendite pro Risiko = Gesamtrendite / gewichtete Volatilität."}
