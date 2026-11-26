"""Marktübersicht, Marktstimmung (eigener Angst-/Gier-Indikator) und Makro-Umfeld."""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

from typing import Any

import numpy as np
import pandas as pd

from .config import Settings, iso, utcnow
from .data.hub import DataHub
from .indicators import classify_trend, perf, sma

INTERP = "EIGENE MODELLINTERPRETATION"
FACT = "BESTÄTIGTE DATEN"


def overview_item(hub: DataHub, sym: str, name: str, note: str | None = None, kind: str = "") -> dict:
    d = hub.daily(sym)
    q = hub.quote(sym)
    item: dict[str, Any] = {"symbol": sym, "name": name, "kind": kind, "note": note, "quote": q.as_dict()}
    if d is None or not d.ok or q.price is None:
        item.update({"available": False})
        return item
    c = d.df["Close"].dropna()
    # Live-Kurs an die Tagesreihe anhängen, damit Woche/Monat konsistent zum angezeigten Kurs sind
    last = q.price
    item["available"] = True
    item["day_pct"] = (last / q.prev_close - 1) if q.prev_close else None
    base_w = c.iloc[-6] if len(c) > 6 else None
    base_m = c.iloc[-22] if len(c) > 22 else None
    item["week_pct"] = (last / base_w - 1) if base_w else None
    item["month_pct"] = (last / base_m - 1) if base_m else None
    item["ytd_pct"] = _ytd(c, last)
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    sl = float(s50.iloc[-1] / s50.iloc[-11] - 1) if len(s50.dropna()) > 11 else None
    item["trend"] = classify_trend(last, _last(s50), _last(s200), sl)
    item["spark"] = [round(float(x), 4) for x in c.tail(60).values]
    return item


def _ytd(c: pd.Series, last: float) -> float | None:
    yr = utcnow().year
    prev = c[c.index.year < yr]
    return (last / float(prev.iloc[-1]) - 1) if len(prev) else None


def _last(s: pd.Series) -> float | None:
    v = s.iloc[-1] if len(s) else np.nan
    return None if pd.isna(v) else float(v)


def build_overview(hub: DataHub, s: Settings) -> list[dict]:
    items = s.universe.get("market_overview", [])
    syms = [i["symbol"] for i in items]
    hub.load_daily(syms)
    hub.load_intraday(syms)
    return [overview_item(hub, i["symbol"], i["name"], i.get("note"), i.get("kind", "")) for i in items]


def build_overnight(hub: DataHub, s: Settings) -> list[dict]:
    items = s.universe.get("overnight", [])
    syms = [i["symbol"] for i in items]
    hub.load_daily(syms)
    hub.load_intraday(syms)
    return [overview_item(hub, i["symbol"], i["name"]) for i in items]


def sentiment(hub: DataHub, s: Settings, tech: dict[str, dict]) -> dict:
    """Angst-/Gier-Indikator aus nachvollziehbaren Komponenten. Kein CNN-Index (inoffiziell, Lizenz unklar)."""
    si = s.universe.get("sentiment_instruments", {})
    syms = [si.get("vix", "^VIX"), "^GSPC", "GC=F", si.get("us10y", "^TNX"), si.get("us3m", "^IRX")]
    hub.load_daily(syms)
    hub.load_intraday(syms)
    comps: list[dict] = []

    vix = hub.daily(si.get("vix", "^VIX"))
    vq = hub.quote(si.get("vix", "^VIX"))
    vix_info = None
    if vix is not None and vix.ok and vq.price:
        hist = vix.df["Close"].dropna().tail(252)
        pct = float((hist < vq.price).mean())
        comps.append({"key": "vix", "label": "Volatilität (VIX) im 1-Jahres-Vergleich", "score": round(100 * (1 - pct)),
                      "detail": f"VIX {_n(vq.price, 1)}, höher als an {_pc(pct, 0)} der Tage im letzten Jahr"})
        vix_info = {"value": vq.price, "percentile_1y": pct, "quote": vq.as_dict(),
                    "level": "niedrig" if vq.price < 15 else "normal" if vq.price < 20 else "erhöht" if vq.price < 30 else "hoch"}

    valid = [t for t in tech.values() if t.get("sma200")]
    if len(valid) >= 10:
        above200 = np.mean([t["last"] > t["sma200"] for t in valid])
        above50 = np.mean([t["last"] > t["sma50"] for t in valid if t.get("sma50")])
        comps.append({"key": "breadth", "label": "Marktbreite (Anteil Werte über SMA 200 / SMA 50)",
                      "score": round(100 * (0.6 * above200 + 0.4 * above50)),
                      "detail": f"{_pc(above200, 0)} über SMA 200, {_pc(above50, 0)} über SMA 50 ({len(valid)} Werte)"})
        near_hi = np.mean([t.get("dist_52w_high", -1) > -0.05 for t in valid])
        near_lo = np.mean([(t["last"] / t["low_52w"] - 1) < 0.05 for t in valid if t.get("low_52w")])
        comps.append({"key": "highs_lows", "label": "Kursstärke (nahe 52-W-Hoch vs. -Tief)",
                      "score": int(np.clip(50 + (near_hi - near_lo) * 150, 0, 100)),
                      "detail": f"{_pc(near_hi, 0)} nahe Jahreshoch, {_pc(near_lo, 0)} nahe Jahrestief"})

    spx = hub.daily("^GSPC")
    if spx is not None and spx.ok and len(spx.df) > 130:
        c = spx.df["Close"].dropna()
        dist = float(c.iloc[-1] / c.rolling(125).mean().iloc[-1] - 1)
        comps.append({"key": "momentum", "label": "Momentum S&P 500 (Abstand zum 125-Tage-Schnitt)",
                      "score": int(np.clip(50 + dist * 600, 0, 100)), "detail": f"{_pc(dist, 1, True)} zum 125-Tage-Schnitt"})
        gold = hub.daily("GC=F")
        if gold is not None and gold.ok:
            ps, pg = perf(c, 20), perf(gold.df["Close"], 20)
            if ps is not None and pg is not None:
                comps.append({"key": "safe_haven", "label": "Sichere Häfen (Aktien vs. Gold, 20 Tage)",
                              "score": int(np.clip(50 + (ps - pg) * 500, 0, 100)),
                              "detail": f"S&P 500 {_pc(ps, 1, True)} vs. Gold {_pc(pg, 1, True)}"})

    score = round(float(np.mean([c["score"] for c in comps]))) if comps else None
    label = None
    if score is not None:
        label = ("extreme Angst" if score < 25 else "Angst" if score < 45 else "neutral" if score <= 55
                 else "Gier" if score <= 75 else "extreme Gier")

    rates = {}
    for key, sym, lab in (("us10y", si.get("us10y", "^TNX"), "Rendite 10-jährige US-Staatsanleihe"),
                          ("us3m", si.get("us3m", "^IRX"), "Rendite 3-monatige US-T-Bills")):
        q = hub.quote(sym)
        if q.price is not None:
            d = hub.daily(sym)
            val = q.price / 10 if sym == "^TNX" and q.price > 20 else q.price
            m_ago = None
            if d is not None and d.ok and len(d.df) > 22:
                m_ago = float(d.df["Close"].iloc[-22])
                m_ago = m_ago / 10 if sym == "^TNX" and m_ago > 20 else m_ago
            rates[key] = {"label": lab, "value": val, "month_ago": m_ago, "quote": q.as_dict()}

    return {"score": score, "label": label, "components": comps, "vix": vix_info, "rates": rates,
            "method": "Mittelwert der Komponenten (je 0–100, höher = risikofreudiger). Eigene Berechnung, kein CNN-Fear-&-Greed-Index.",
            "tag": INTERP, "time": iso(utcnow())}


def environment(sent: dict, overview: list[dict], macro: dict) -> dict:
    """Gesamteinschätzung positiv/neutral/negativ mit Begründung."""
    pts = 0.0
    reasons: list[dict] = []
    if sent.get("score") is not None:
        sc = sent["score"]
        pts += (sc - 50) / 25
        reasons.append({"text": f"Eigener Stimmungsindikator bei {sc}/100 ({sent['label']}).", "tag": INTERP,
                        "dir": "+" if sc > 55 else "-" if sc < 45 else "="})
    for it in overview:
        if it.get("kind") == "index" and it.get("available") and it["symbol"] in ("^GSPC", "^GDAXI"):
            t = it["trend"]
            pts += 0.6 if t == "aufwärts" else -0.6 if t == "abwärts" else 0
            reasons.append({"text": f"{it['name']}: Trend {t}, Monat {_pct(it.get('month_pct'))}.", "tag": FACT,
                            "dir": "+" if t == "aufwärts" else "-" if t == "abwärts" else "="})
    v = sent.get("vix")
    if v:
        if v["value"] >= 25:
            pts -= 1
        elif v["value"] < 16:
            pts += 0.3
        reasons.append({"text": f"VIX {_n(v['value'], 1)} – Volatilität {v['level']}.", "tag": FACT,
                        "dir": "-" if v["value"] >= 25 else "+" if v["value"] < 16 else "="})
    dr = macro.get("deposit_rate")
    if dr and dr.get("prev") is not None:
        ch = dr["value"] - dr["prev"]
        if abs(ch) > 1e-9:
            pts += 0.3 if ch < 0 else -0.3
        reasons.append({"text": f"EZB-Einlagesatz {_n(dr['value'], 2)} % (Stand {dr['date']}{', zuletzt gesenkt' if ch < 0 else ', zuletzt erhöht' if ch > 0 else ', unverändert'}).",
                        "tag": FACT, "dir": "+" if ch < 0 else "-" if ch > 0 else "="})
    h = macro.get("hicp")
    if h:
        reasons.append({"text": f"Inflation Euroraum {_n(h['value'], 1)} % (Ziel der EZB: 2 %, Stand {h['date']}).", "tag": FACT,
                        "dir": "-" if h["value"] > 3 else "+" if h["value"] <= 2.5 else "="})
        if h["value"] > 3:
            pts -= 0.3
    cpi = macro.get("us_cpi")
    if cpi:
        reasons.append({"text": f"US-Inflation (CPI) {_n(cpi['value'], 1)} % J/J (Stand {cpi['date']}).", "tag": FACT,
                        "dir": "-" if cpi["value"] > 3.5 else "="})
    verdict = "positiv" if pts >= 1.0 else "negativ" if pts <= -1.0 else "neutral"
    expl = {"positiv": "Das Umfeld spricht eher für Aktien: Trends und Stimmung sind überwiegend freundlich. Das schützt nicht vor Rücksetzern.",
            "neutral": "Gemischtes Bild: Es gibt Argumente in beide Richtungen. Selektiv vorgehen und Positionsgrößen vorsichtig wählen.",
            "negativ": "Das Umfeld ist angespannt: schwache Trends oder hohe Unsicherheit. Risiko reduzieren und Signale strenger prüfen."}[verdict]
    return {"verdict": verdict, "points": round(pts, 2), "explanation": expl, "reasons": reasons, "tag": INTERP}


def _pct(v: float | None) -> str:
    return _pc(v, 1, True)
