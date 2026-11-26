"""KI-Aktienanalyst: kombiniert Technik, Fundamentaldaten und Nachrichten zu begründeten Signalen.

Grundsätze
* Regeln sind transparent und deterministisch; jede Punktvergabe wird begründet.
* Kein Signal aus einem einzelnen Indikator: BUY/SELL braucht mehrere bestätigende Faktorgruppen.
* Fehlende Daten zählen neutral und erhöhen die Unsicherheit – sie werden nie geschätzt.
* Kurzfristiges Trading (Tage bis Wochen) und langfristiges Investment (Monate bis Jahre) getrennt.
"""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

import math
import re
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from .config import Settings, iso, parse_iso, utcnow

FACT, THIRD, INTERP = "BESTÄTIGTE DATEN", "ANALYSTENEINSCHÄTZUNG (Dritte)", "EIGENE MODELLINTERPRETATION"
RATINGS = ["STRONG SELL", "SELL", "HOLD", "BUY", "STRONG BUY"]
RATING_DE = {"STRONG BUY": "besonders interessantes Kaufszenario", "BUY": "positives Szenario",
             "HOLD": "beobachten bzw. halten", "SELL": "negatives Szenario", "STRONG SELL": "deutlich erhöhtes Abwärtsrisiko"}

# ---------------------------------------------------------------- Nachrichten
NEWS_CATEGORIES = {
    "Quartalszahlen": r"\b(earnings|quarter|quartal|results|ergebnis|umsatz|revenue|guidance|prognose|ausblick|eps)\b",
    "Übernahme/Fusion": r"\b(acquir|acquisition|merger|takeover|übernahme|fusion|buyout|bid for|deal to buy)\w*",
    "Management": r"\b(ceo|cfo|chief executive|vorstand|resign|rücktritt|appoint|ernenn|steps down|chairman)\w*",
    "Analysten": r"\b(upgrade|downgrade|price target|kursziel|rating|analyst|overweight|underweight|outperform)\w*",
    "Politik/Regulierung": r"\b(tariff|zoll|sanction|sanktion|regulat|antitrust|kartell|government|regierung|election|wahl|subsid)\w*",
    "Branche": r"\b(industry|branche|sector|sektor|demand|nachfrage|supply|competition|wettbewerb)\b",
    "International": r"\b(china|europe|eu|ukraine|russia|middle east|nahost|war|krieg|opec|fed|ecb|ezb)\b",
}
POS = r"\b(beat|beats|surge|soar|jump|record|raise[sd]?|upgrade|strong|growth|wins?|contract|auftrag|rekord|übertr|steigt|anhebung|hebt|buyback|rückkauf|outperform|approval|zulassung)\w*"
NEG = r"\b(miss|misses|plunge|fall|falls|drop|cut[s]?|downgrade|weak|loss|lawsuit|klage|probe|investigation|ermittlung|recall|rückruf|warn|senkt|bricht|verlust|fraud|betrug|layoff|stellenabbau|delay|verzögerung|underperform|halt)\w*"


def classify_news(item: dict) -> dict:
    text = f"{item.get('title') or ''} {item.get('summary') or ''}".lower()
    cats = [c for c, rx in NEWS_CATEGORIES.items() if re.search(rx, text)]
    p, n = len(re.findall(POS, text)), len(re.findall(NEG, text))
    tone = "positiv" if p > n else "negativ" if n > p else "neutral"
    return {**item, "categories": cats or ["Unternehmen"], "tone": tone,
            "tone_method": "Stichwortanalyse (kein Textverständnis) – Originalquelle lesen"}


def news_eval(ev: dict, now: datetime, max_age_days: int = 7) -> dict:
    items = []
    for n in ev.get("news", []) or []:
        pub = _parse_dt(n.get("published"))
        if pub and now - pub > timedelta(days=max_age_days):
            continue
        items.append(classify_news(n))
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    pos = sum(1 for i in items if i["tone"] == "positiv")
    neg = sum(1 for i in items if i["tone"] == "negativ")
    points = []
    news_dir = 0
    if items:
        if pos - neg >= 2:
            news_dir = 1
        elif neg - pos >= 2:
            news_dir = -1
        points.append({"text": f"{len(items)} Meldungen der letzten {max_age_days} Tage: {pos} positiv, {neg} negativ, Rest neutral (Stichwortanalyse).",
                       "tag": INTERP, "dir": news_dir})
    # Analysten-Änderungen der letzten 30 Tage
    ups = downs = 0
    for u in ev.get("upgrades", []) or []:
        d = _parse_dt(u.get("date"))
        if d and now - d <= timedelta(days=30):
            a = (u.get("action") or "").lower()
            if a in ("up", "upgrade"):
                ups += 1
            elif a in ("down", "downgrade"):
                downs += 1
    analyst_dir = 1 if ups > downs else -1 if downs > ups else 0
    if ups or downs:
        points.append({"text": f"Analysten in 30 Tagen: {ups} Hochstufung(en), {downs} Abstufung(en).", "tag": THIRD, "dir": analyst_dir})
    # Gewinnüberraschung
    earn_dir = 0
    surprise = None
    for e in ev.get("earnings", []) or []:
        if e.get("eps_reported") is not None and e.get("surprise_pct") is not None:
            d = _parse_dt(e.get("date"))
            if d and now - d <= timedelta(days=100):
                surprise = e
                sp = e["surprise_pct"]
                earn_dir = 1 if sp > 3 else -1 if sp < -3 else 0
                points.append({"text": f"Letzte Quartalszahlen ({d.date().isoformat()}): EPS {e['eps_reported']} vs. Erwartung {e.get('eps_estimate')} ({_n(sp, 1, True)} % Überraschung).",
                               "tag": FACT, "dir": earn_dir})
            break
    score = 50 + 12 * news_dir + 10 * analyst_dir + 12 * earn_dir
    return {"score": score, "items": items[:8], "dirs": {"news": news_dir, "analysts": analyst_dir, "earnings": earn_dir},
            "points": points, "surprise": surprise, "calendar": ev.get("calendar", {}), "fetched": ev.get("_fetched")}


# ------------------------------------------------------------------ Technik
def tech_eval(t: dict) -> dict:
    pts: list[dict] = []
    if t.get("bars", 0) < 60 or t.get("sma50") is None:
        return {"score": 50, "dirs": {}, "points": [{"text": "Zu kurze Kurshistorie für eine technische Bewertung.", "tag": INTERP, "dir": 0}], "coverage": 0.0}
    last = t["last"]
    dirs: dict[str, int] = {}
    # Trend
    tr = t.get("trend")
    dirs["trend"] = 1 if tr == "aufwärts" else -1 if tr == "abwärts" else 0
    s200 = t.get("sma200")
    pts.append({"text": f"Trend {tr}: Kurs {_rel(last, t['sma50'])} SMA 50" + (f", {_rel(last, s200)} SMA 200" if s200 else "") + f", SMA 20 bei {_n(t['sma20'], 2)}.",
                "tag": FACT, "dir": dirs["trend"]})
    if t.get("cross_20d"):
        pts.append({"text": "Golden Cross (SMA 50 über SMA 200) in den letzten 20 Tagen." if t["cross_20d"] == "golden_cross" else "Death Cross (SMA 50 unter SMA 200) in den letzten 20 Tagen.",
                    "tag": FACT, "dir": 1 if t["cross_20d"] == "golden_cross" else -1})
    # Momentum: RSI + MACD + 3M-Performance
    m = 0
    rsi = t.get("rsi")
    if rsi is not None:
        if rsi > 75:
            m -= 1
            pts.append({"text": f"RSI {_n(rsi, 0)}: überkauft – Rücksetzergefahr.", "tag": FACT, "dir": -1})
        elif rsi < 25:
            pts.append({"text": f"RSI {_n(rsi, 0)}: stark überverkauft – Gegenbewegung möglich, aber Abwärtsdruck.", "tag": FACT, "dir": 0})
        elif 50 <= rsi <= 70:
            m += 1
            pts.append({"text": f"RSI {_n(rsi, 0)}: positives Momentum ohne Überhitzung.", "tag": FACT, "dir": 1})
        elif rsi < 40:
            m -= 1
            pts.append({"text": f"RSI {_n(rsi, 0)}: schwaches Momentum.", "tag": FACT, "dir": -1})
    if t.get("macd_hist") is not None:
        if t.get("macd_cross") == "bullish":
            m += 1
            pts.append({"text": "MACD hat die Signallinie frisch nach oben gekreuzt.", "tag": FACT, "dir": 1})
        elif t.get("macd_cross") == "bearish":
            m -= 1
            pts.append({"text": "MACD hat die Signallinie frisch nach unten gekreuzt.", "tag": FACT, "dir": -1})
        else:
            m += 1 if t["macd_hist"] > 0 else -1
    p3 = t.get("perf_3m")
    if p3 is not None:
        m += 1 if p3 > 0.05 else -1 if p3 < -0.05 else 0
    dirs["momentum"] = 1 if m >= 2 else -1 if m <= -2 else 0
    # Volumen
    rv = t.get("rvol")
    p1 = t.get("perf_1d") or 0
    if rv is not None:
        if rv >= 1.8:
            dirs["volume"] = 1 if p1 > 0 else -1
            pts.append({"text": f"Handelsvolumen {_n(rv, 1)}× über dem 20-Tage-Schnitt bei {_pc(p1, 1, True)} – {'Kaufdruck' if p1 > 0 else 'Verkaufsdruck'}.",
                        "tag": FACT, "dir": dirs["volume"]})
        else:
            dirs["volume"] = 0
    # Relative Stärke
    rs = t.get("rel_strength_6m")
    if rs is not None:
        dirs["rel_strength"] = 1 if rs > 0.05 else -1 if rs < -0.05 else 0
        pts.append({"text": f"Relative Stärke 6 Monate: {_pc(rs, 1, True)} gegenüber dem Vergleichsindex.", "tag": FACT, "dir": dirs["rel_strength"]})
    # Unterstützung / Widerstand
    sr = t.get("sr") or {}
    atr = t.get("atr") or 0
    if sr.get("supports") and atr:
        dist = (last - sr["supports"][0]["level"]) / atr
        if dist < 1.0 and dirs["trend"] >= 0:
            dirs["sr"] = 1
            pts.append({"text": f"Kurs nahe Unterstützung {_n(sr['supports'][0]['level'], 2)} ({_n(dist, 1)} ATR entfernt) – günstiges Chance-Risiko möglich.", "tag": INTERP, "dir": 1})
    if sr.get("resistances") and atr:
        dist = (sr["resistances"][0]["level"] - last) / atr
        if dist < 0.7:
            dirs["sr"] = dirs.get("sr", 0) - 1
            pts.append({"text": f"Kurs direkt unter Widerstand {_n(sr['resistances'][0]['level'], 2)} – Ausbruch noch nicht bestätigt.", "tag": INTERP, "dir": -1})
    if t.get("dist_52w_high") is not None and t["dist_52w_high"] > -0.02 and (rv or 0) > 1.3:
        dirs["sr"] = 1
        pts.append({"text": "Ausbruch auf neues 52-Wochen-Hoch mit erhöhtem Volumen.", "tag": FACT, "dir": 1})
    # Trendstärke
    if t.get("adx") is not None:
        pts.append({"text": f"ADX {_n(t['adx'], 0)}: {'ausgeprägter' if t['adx'] > 25 else 'schwacher'} Trend.", "tag": FACT, "dir": 0})
    ch = t.get("channel")
    if ch and ch["r2"] > 0.6:
        pts.append({"text": f"Trendkanal (60 Tage, R² {_n(ch['r2'], 2)}): {_n(ch['slope_pct_per_day'] * 21, 1, True)} % pro Monat, Kanal {_n(ch['lower'], 2)}–{_n(ch['upper'], 2)}.", "tag": INTERP, "dir": 0})
    vol = t.get("vol_60")
    if vol is not None and vol > 0.6:
        pts.append({"text": f"Hohe Volatilität ({_pc(vol, 0)} annualisiert) – größere Schwankungen einplanen.", "tag": FACT, "dir": 0})
    raw = 50 + 14 * dirs.get("trend", 0) + 10 * dirs.get("momentum", 0) + 7 * dirs.get("volume", 0) + 8 * dirs.get("rel_strength", 0) + 6 * max(-1, min(1, dirs.get("sr", 0)))
    if rsi is not None and rsi > 80:
        raw -= 6
    return {"score": int(max(0, min(100, raw))), "dirs": {k: max(-1, min(1, v)) for k, v in dirs.items()}, "points": pts, "coverage": 1.0}


# ----------------------------------------------------------- Fundamentaldaten
FUND_KEYS = ["revenue_growth", "earnings_growth", "pe", "pb", "equity_ratio", "debt_to_equity", "free_cashflow",
             "operating_margin", "roe", "dividend_yield"]


def sector_medians(funds: dict[str, dict]) -> dict[str, dict]:
    by: dict[str, dict[str, list[float]]] = {}
    for f in funds.values():
        sec = f.get("sector")
        if not sec:
            continue
        for k in ("pe", "pb", "operating_margin", "revenue_growth"):
            v = f.get(k)
            if isinstance(v, (int, float)) and math.isfinite(v) and (k not in ("pe", "pb") or v > 0):
                by.setdefault(sec, {}).setdefault(k, []).append(float(v))
    return {s: {k: median(v) for k, v in d.items() if len(v) >= 3} for s, d in by.items()}


def fund_eval(f: dict, medians: dict[str, dict], is_etf: bool = False) -> dict:
    if is_etf:
        return {"score": 50, "dirs": {}, "coverage": 0.0, "points": [{"text": "ETF: keine Unternehmenskennzahlen, Bewertung über Trend und Kosten/Diversifikation.", "tag": INTERP, "dir": 0}]}
    pts: list[dict] = []
    dirs: dict[str, int] = {}
    present = sum(1 for k in FUND_KEYS if f.get(k) is not None)
    coverage = present / len(FUND_KEYS)
    med = medians.get(f.get("sector") or "", {})
    # Wachstum
    g = []
    rg, eg = f.get("revenue_growth"), f.get("earnings_growth")
    if rg is not None:
        g.append(1 if rg > 0.08 else -1 if rg < 0 else 0)
        pts.append({"text": f"Umsatzwachstum (J/J, letztes Quartal): {_pc(rg, 1, True)}.", "tag": FACT, "dir": g[-1]})
    if eg is not None:
        g.append(1 if eg > 0.10 else -1 if eg < -0.05 else 0)
        pts.append({"text": f"Gewinnwachstum (J/J): {_pc(eg, 1, True)}.", "tag": FACT, "dir": g[-1]})
    rh = f.get("revenue_history") or []
    if len(rh) >= 3 and rh[-1]["value"]:
        cagr = (rh[0]["value"] / rh[-1]["value"]) ** (1 / (len(rh) - 1)) - 1 if rh[0]["value"] > 0 and rh[-1]["value"] > 0 else None
        if cagr is not None:
            pts.append({"text": f"Umsatz-CAGR über {len(rh) - 1} Geschäftsjahre: {_pc(cagr, 1, True)}.", "tag": FACT, "dir": 1 if cagr > 0.07 else -1 if cagr < 0 else 0})
            g.append(1 if cagr > 0.07 else -1 if cagr < 0 else 0)
    if g:
        dirs["growth"] = 1 if sum(g) >= 2 else -1 if sum(g) <= -1 else 0
    # Profitabilität
    pr = []
    om, roe = f.get("operating_margin"), f.get("roe")
    if om is not None:
        ref = med.get("operating_margin")
        pr.append(1 if (om > (ref or 0.15)) else -1 if om < 0.03 else 0)
        pts.append({"text": f"Operative Marge {_pc(om, 1)}" + (f" (Branchenmedian im Universum {_pc(ref, 1)})" if ref else "") + ".", "tag": FACT, "dir": pr[-1]})
    if roe is not None:
        pr.append(1 if roe > 0.15 else -1 if roe < 0.05 else 0)
        pts.append({"text": f"Eigenkapitalrendite {_pc(roe, 1)}.", "tag": FACT, "dir": pr[-1]})
    if pr:
        dirs["profitability"] = 1 if sum(pr) >= 1 else -1 if sum(pr) <= -1 else 0
    # Bewertung
    va = []
    pe, ref_pe = f.get("pe"), med.get("pe")
    if pe is not None and pe > 0:
        if ref_pe:
            rel = pe / ref_pe
            va.append(1 if rel < 0.8 else -1 if rel > 1.4 else 0)
            pts.append({"text": f"KGV {_n(pe, 1)} vs. Branchenmedian {_n(ref_pe, 1)} im Universum ({'günstiger' if rel < 1 else 'teurer'}).", "tag": FACT, "dir": va[-1]})
        else:
            va.append(1 if pe < 14 else -1 if pe > 35 else 0)
            pts.append({"text": f"KGV {_n(pe, 1)}.", "tag": FACT, "dir": va[-1]})
    elif pe is not None:
        va.append(-1)
        pts.append({"text": "Negatives KGV (Verlust) – keine KGV-Bewertung möglich.", "tag": FACT, "dir": -1})
    fpe = f.get("forward_pe")
    if fpe and pe and pe > 0 and fpe > 0:
        pts.append({"text": f"Erwartetes KGV {_n(fpe, 1)} ({'Gewinnanstieg erwartet' if fpe < pe else 'Gewinnrückgang erwartet'}, Konsens Dritter).", "tag": THIRD, "dir": 1 if fpe < pe * 0.9 else -1 if fpe > pe * 1.1 else 0})
    pb = f.get("pb")
    if pb is not None and pb > 0:
        pts.append({"text": f"KBV {_n(pb, 1)}.", "tag": FACT, "dir": 0})
    peg = f.get("peg")
    if peg is not None and peg > 0:
        va.append(1 if peg < 1.2 else -1 if peg > 2.5 else 0)
        pts.append({"text": f"PEG {_n(peg, 2)}.", "tag": FACT, "dir": va[-1]})
    if va:
        dirs["valuation"] = 1 if sum(va) >= 1 else -1 if sum(va) <= -1 else 0
    # Bilanz & Cashflow
    ba = []
    eqr, de = f.get("equity_ratio"), f.get("debt_to_equity")
    if eqr is not None:
        ba.append(1 if eqr > 0.4 else -1 if eqr < 0.2 else 0)
        pts.append({"text": f"Eigenkapitalquote {_pc(eqr, 0)}.", "tag": FACT, "dir": ba[-1]})
    if de is not None:
        ba.append(1 if de < 0.5 else -1 if de > 2.0 else 0)
        pts.append({"text": f"Verschuldungsgrad (Fremd-/Eigenkapital) {_n(de, 2)}.", "tag": FACT, "dir": ba[-1]})
    fcf = f.get("free_cashflow")
    if fcf is not None:
        ba.append(1 if fcf > 0 else -1)
        mc = f.get("market_cap")
        y = f" (FCF-Rendite {_pc(fcf / mc, 1)})" if mc and fcf > 0 else ""
        pts.append({"text": f"Free Cashflow {'positiv' if fcf > 0 else 'negativ'}: {_big(fcf)}{y}.", "tag": FACT, "dir": ba[-1]})
    if ba:
        dirs["balance"] = 1 if sum(ba) >= 2 else -1 if sum(ba) <= -1 else 0
    dy = f.get("dividend_yield")
    if dy:
        pts.append({"text": f"Dividendenrendite {_pc(dy, 1)}" + (f", Ausschüttungsquote {_pc(f['payout_ratio'], 0)}" if f.get("payout_ratio") else "") + ".", "tag": FACT,
                    "dir": -1 if (f.get("payout_ratio") or 0) > 1.0 else 0})
    # Wettbewerbsposition (Proxy)
    if om is not None and med.get("operating_margin"):
        better = om > med["operating_margin"] * 1.2
        pts.append({"text": f"[PROXY] Wettbewerbsposition: Marge {'deutlich über' if better else 'nicht über'} Branchenmedian – Burggraben nur über den Geschäftsbericht wirklich beurteilbar.",
                    "tag": INTERP, "dir": 0})
    raw = 50 + 9 * dirs.get("growth", 0) + 8 * dirs.get("profitability", 0) + 9 * dirs.get("valuation", 0) + 8 * dirs.get("balance", 0)
    # Fehlende Daten ziehen Richtung 50
    raw = 50 + (raw - 50) * (0.4 + 0.6 * coverage)
    if f.get("_stale"):
        pts.append({"text": "Fundamentaldaten aus älterem Cache (aktueller Abruf fehlgeschlagen).", "tag": FACT, "dir": 0})
    return {"score": int(round(raw)), "dirs": dirs, "coverage": round(coverage, 2), "points": pts}


# ---------------------------------------------------------------- Signale
def _rating_from(score: float, s: Settings) -> str:
    if score >= s.get("signals.strong_buy", 75):
        return "STRONG BUY"
    if score >= s.get("signals.buy", 62):
        return "BUY"
    if score <= s.get("signals.strong_sell", 25):
        return "STRONG SELL"
    if score <= s.get("signals.sell", 38):
        return "SELL"
    return "HOLD"


def _confirm(rating: str, dirs: dict[str, int], min_groups: int, coverage: float) -> tuple[str, str | None]:
    # Das Marktumfeld zählt nicht als aktienspezifische Bestätigung
    own = {k: v for k, v in dirs.items() if k != "market"}
    pos = sum(1 for v in own.values() if v > 0)
    neg = sum(1 for v in own.values() if v < 0)
    note = None
    if rating in ("BUY", "STRONG BUY"):
        if pos < min_groups or pos <= neg:
            return "HOLD", f"Score positiv, aber nur {pos} bestätigende Faktorgruppe(n) bei {neg} gegenläufigen – kein Einzelindikator-Signal."
        if rating == "STRONG BUY" and (pos < min_groups + 1 or neg > 1 or coverage < 0.6):
            return "BUY", "Für STRONG BUY fehlen Bestätigung oder Datenabdeckung – auf BUY begrenzt."
    if rating in ("SELL", "STRONG SELL"):
        if neg < min_groups or neg <= pos:
            return "HOLD", f"Score negativ, aber nur {neg} bestätigende Faktorgruppe(n) bei {pos} gegenläufigen."
        if rating == "STRONG SELL" and (neg < min_groups + 1 or pos > 1 or coverage < 0.6):
            return "SELL", "Für STRONG SELL fehlen Bestätigung oder Datenabdeckung – auf SELL begrenzt."
    return rating, note


def build_signal(sym: str, name: str, quote: dict, t: dict, te: dict, fe: dict, ne: dict, env: dict,
                 s: Settings, horizon: str, is_etf: bool = False) -> dict:
    now = utcnow()
    market_dir = {"positiv": 1, "neutral": 0, "negativ": -1}.get(env.get("verdict"), 0)
    if horizon == "short":
        dirs = {**{f"tech_{k}": v for k, v in te["dirs"].items()}, "news": ne["dirs"]["news"], "earnings": ne["dirs"]["earnings"], "market": market_dir}
        score = 0.70 * te["score"] + 0.15 * ne["score"] + 0.15 * (50 + 20 * market_dir)
        coverage = te.get("coverage", 1.0)
        label = "Kurzfristiges Trading (Tage bis wenige Wochen)"
    else:
        long_tech = 50 + 20 * te["dirs"].get("trend", 0) + 10 * te["dirs"].get("rel_strength", 0)
        dirs = {**{f"fund_{k}": v for k, v in fe["dirs"].items()}, "tech_trend": te["dirs"].get("trend", 0),
                "analysts": ne["dirs"]["analysts"], "earnings": ne["dirs"]["earnings"]}
        if is_etf:
            score = 0.7 * long_tech + 0.3 * (50 + 20 * market_dir)
            dirs = {"tech_trend": te["dirs"].get("trend", 0), "tech_rel_strength": te["dirs"].get("rel_strength", 0),
                    "tech_momentum": te["dirs"].get("momentum", 0), "market": market_dir}
            coverage = 0.7
        else:
            score = 0.60 * fe["score"] + 0.25 * long_tech + 0.15 * (50 + 10 * ne["dirs"]["analysts"] + 12 * ne["dirs"]["earnings"])
            coverage = fe.get("coverage", 0.0)
        label = "Langfristiges Investment (Monate bis Jahre)"
    raw_rating = _rating_from(score, s)
    rating, note = _confirm(raw_rating, dirs, int(s.get("signals.min_confirming_groups", 3)), coverage)
    if horizon == "short" and rating == "STRONG BUY" and market_dir < 0:
        rating, note = "BUY", "Negatives Marktumfeld – STRONG BUY auf BUY begrenzt."
    price = quote.get("price")
    levels = _levels(price, t, rating, horizon) if price else {}
    unc = _uncertainty(t, coverage, dirs, quote, ne, env)
    if horizon == "short":
        pool = te["points"] + ne["points"]
    else:
        pool = fe["points"] + [p for p in te["points"] if p["text"].startswith(("Trend", "Relative", "Golden", "Death"))] + ne["points"]
    pros = [p for p in pool if p["dir"] > 0]
    cons = [p for p in pool if p["dir"] < 0]
    relevant = te["points"] if horizon == "short" else fe["points"] + [p for p in te["points"] if "Trend" in p["text"]]
    bullish = rating in ("BUY", "STRONG BUY")
    bearish = rating in ("SELL", "STRONG SELL")
    counter = cons if bullish else pros if bearish else []
    counter = [c["text"] for c in counter][:5]
    if ne.get("calendar", {}).get("earnings_date"):
        counter.append(f"Nächster Zahlentermin laut Yahoo: {ne['calendar']['earnings_date'][:10]} – Gap-Risiko.")
    if bullish and market_dir < 0:
        counter.append("Marktumfeld insgesamt negativ – Einzelwerte werden oft mitgerissen.")
    crv = levels.get("crv")
    if (bullish or bearish) and crv is not None and crv < 1.5:
        counter.append(f"Chance-Risiko-Verhältnis nur {_n(crv, 2)} bis zum Basisszenario – wenig Puffer.")
    if unc["level"] == "hoch":
        counter.append("Hohe Unsicherheit der Datenlage bzw. Volatilität – Signal nur eingeschränkt belastbar.")
    reason = _reason(rating, horizon, pros, cons, note)
    return {
        "id": f"{sym}|{horizon}|{now.date().isoformat()}",
        "symbol": sym, "name": name, "horizon": horizon, "horizon_label": label,
        "rating": rating, "rating_text": RATING_DE[rating], "raw_rating": raw_rating, "rating_note": note,
        "score": int(round(score)), "score_band": int(5 + 10 * (1 - min(1.0, coverage))),
        "quote": quote, "time": iso(now),
        "reason": reason, "factor_dirs": dirs,
        "technical": {"score": te["score"], "points": te["points"]},
        "fundamental": {"score": fe["score"], "coverage": fe.get("coverage"), "points": fe["points"]},
        "news": {"score": ne["score"], "items": ne["items"][:5], "points": ne["points"]},
        "levels": levels, "uncertainty": unc,
        "invalidation": _invalidation(rating, horizon, levels, t),
        "counterarguments": counter or ["Keine wesentlichen Gegenargumente in den verfügbaren Daten – das heißt nicht, dass es keine gibt."],
        "pros": [p["text"] for p in pros][:6],
        "relevant_points": [p["text"] for p in relevant][:6],
        "tag": INTERP,
        "disclaimer": "Analytische Orientierung für das Planspiel, keine Anlageberatung und keine Garantie.",
    }


def _levels(price: float, t: dict, rating: str, horizon: str) -> dict:
    atr = t.get("atr") or price * 0.02
    sr = t.get("sr") or {}
    sup = [x["level"] for x in sr.get("supports", [])]
    res = [x["level"] for x in sr.get("resistances", [])]
    if horizon == "short":
        if rating in ("SELL", "STRONG SELL"):
            base = sup[0] if sup and 1 <= (price - sup[0]) / atr <= 4 else price - 2 * atr
            bull_case = price + 1.5 * atr
            bear_case = sup[1] if len(sup) > 1 else price - 3.5 * atr
            stop = min(res[0] + 0.5 * atr, price + 3 * atr) if res else price + 2 * atr
            stop = max(stop, price + atr)
            return {"type": "short", "entry_ref": price, "scenario_base": base, "scenario_bull": bull_case,
                    "scenario_bear": bear_case, "risk_level": stop,
                    "risk_text": f"Signal ungültig über {_n(stop, 2)} (Widerstand + Puffer)",
                    "crv": round((price - base) / (stop - price), 2) if stop > price else None,
                    "method": "Szenarien aus Unterstützungen/Widerständen und ATR (14). Keine Kursprognose."}
        base = res[0] if res and 1 <= (res[0] - price) / atr <= 4 else price + 2 * atr
        bull = res[1] if len(res) > 1 and res[1] > base else price + 3.5 * atr
        stop = max(sup[0] - 0.5 * atr, price - 3 * atr) if sup else price - 2 * atr
        stop = min(stop, price - atr)
        bear = price - 1.5 * atr
        return {"type": "long", "entry_ref": price, "scenario_base": base, "scenario_bull": bull,
                "scenario_bear": bear, "risk_level": stop,
                "risk_text": f"Verlustbereich unter {_n(stop, 2)} (Unterstützung − 0,5 ATR)",
                "crv": round((base - price) / (price - stop), 2) if price > stop else None,
                "method": "Szenarien aus Unterstützungen/Widerständen und ATR (14). Keine Kursprognose."}
    vol = t.get("vol_60") or 0.3
    s200 = t.get("sma200")
    loss = min(price * math.exp(-vol / 2), (s200 * 0.95) if s200 else price * 0.85)
    return {"type": "long_term", "entry_ref": price,
            "scenario_bear": price * math.exp(-vol), "scenario_base": None, "scenario_bull": price * math.exp(vol),
            "risk_level": loss, "risk_text": f"These überprüfen unter {_n(loss, 2)} (SMA 200 − 5 % bzw. halbe Jahresschwankung)",
            "method": f"12-Monats-Bandbreite = ±1 Standardabweichung der realisierten Volatilität ({_pc(vol, 0)}). Statistische Spanne, keine Prognose; kein Base-Case ohne Bewertungsmodell.",
            "crv": None}


def _uncertainty(t: dict, coverage: float, dirs: dict, quote: dict, ne: dict, env: dict) -> dict:
    u = 0.0
    reasons = []
    vol = t.get("vol_60")
    if vol is not None:
        u += min(1.0, vol / 0.8) * 35
        if vol > 0.45:
            reasons.append(f"hohe Volatilität ({_pc(vol, 0)})")
    u += (1 - coverage) * 30
    if coverage < 0.6:
        reasons.append(f"Datenabdeckung {_pc(coverage, 0)}")
    vals = [v for v in dirs.values() if v != 0]
    if vals:
        disagree = min(sum(1 for v in vals if v > 0), sum(1 for v in vals if v < 0)) / len(vals)
        u += disagree * 40
        if disagree > 0.3:
            reasons.append("Faktoren widersprechen sich")
    if quote.get("quality") in ("veraltet", "nicht verfügbar"):
        u += 20
        reasons.append(f"Kurs {quote.get('quality')}")
    if env.get("verdict") == "negativ":
        u += 10
        reasons.append("angespanntes Marktumfeld")
    ed = (ne.get("calendar") or {}).get("earnings_date")
    if ed:
        d = _parse_dt(ed)
        if d and timedelta(0) <= d - utcnow() <= timedelta(days=10):
            u += 10
            reasons.append("Quartalszahlen in Kürze")
    u = min(100.0, u)
    return {"score": int(round(u)), "level": "niedrig" if u < 30 else "mittel" if u < 55 else "hoch", "reasons": reasons}


def _invalidation(rating: str, horizon: str, lv: dict, t: dict) -> list[str]:
    out = []
    if horizon == "short":
        if rating in ("BUY", "STRONG BUY"):
            if lv.get("risk_level"):
                out.append(f"Schlusskurs unter {_n(lv['risk_level'], 2)}.")
            if t.get("sma50"):
                out.append(f"Schlusskurs unter SMA 50 ({_n(t['sma50'], 2)}).")
            out.append("MACD kreuzt die Signallinie nach unten.")
            out.append("Kein Fortschritt Richtung Basisszenario innerhalb von 20 Handelstagen (Zeitstopp).")
        elif rating in ("SELL", "STRONG SELL"):
            if lv.get("risk_level"):
                out.append(f"Schlusskurs über {_n(lv['risk_level'], 2)}.")
            if t.get("sma50"):
                out.append(f"Rückeroberung des SMA 50 ({_n(t['sma50'], 2)}) mit Volumen.")
        else:
            out.append("HOLD: neu bewerten bei Ausbruch über den nächsten Widerstand oder Bruch der nächsten Unterstützung.")
    else:
        if rating in ("BUY", "STRONG BUY", "HOLD"):
            if lv.get("risk_level"):
                out.append(f"Nachhaltig unter {_n(lv['risk_level'], 2)}.")
            out.append("Umsatzwachstum dreht ins Negative oder Free Cashflow wird negativ.")
            out.append("Deutliche Prognosesenkung oder Abstufungswelle der Analysten.")
        else:
            out.append("Rückkehr über den SMA 200 und Stabilisierung der Gewinnentwicklung.")
    return out


def _reason(rating: str, horizon: str, pros: list[dict], cons: list[dict], note: str | None) -> str:
    h = "kurzfristig" if horizon == "short" else "langfristig"
    pro = "; ".join(p["text"].rstrip(".") for p in pros[:3]) or "keine klaren positiven Faktoren"
    con = "; ".join(p["text"].rstrip(".") for p in cons[:3]) or "keine klaren negativen Faktoren"
    base = {"STRONG BUY": f"Mehrere unabhängige Faktoren sprechen {h} klar für die Aktie: {pro}.",
            "BUY": f"{h.capitalize()} überwiegen die positiven Faktoren: {pro}. Dagegen: {con}.",
            "HOLD": f"{h.capitalize()} kein eindeutiges Bild. Dafür: {pro}. Dagegen: {con}.",
            "SELL": f"{h.capitalize()} überwiegen die negativen Faktoren: {con}. Dafür spricht: {pro}.",
            "STRONG SELL": f"Mehrere unabhängige Faktoren zeigen {h} ein deutlich erhöhtes Abwärtsrisiko: {con}."}[rating]
    return base + (f" Hinweis: {note}" if note else "")


def _rel(a: float, b: float | None) -> str:
    if b is None:
        return "?"
    return f"{_pc(abs(a / b - 1), 1)} {'über' if a >= b else 'unter'}"


def _big(v: float) -> str:
    a = abs(v)
    s = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{s}{_n(a / 1e9, 1)} Mrd."
    if a >= 1e6:
        return f"{s}{_n(a / 1e6, 0)} Mio."
    return f"{_n(v, 0)}"


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        d = parse_iso(str(s).replace(" ", "T")) if "T" in str(s) or " " in str(s) else datetime.fromisoformat(str(s)[:10])
    except ValueError:
        try:
            d = datetime.fromisoformat(str(s)[:10])
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d
