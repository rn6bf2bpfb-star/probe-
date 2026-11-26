"""Tägliche Börsenberichte (morgens, untertags, abends) – regelbasiert, optional mit KI-Kommentar."""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

from typing import Any

from . import llm
from .config import Settings, iso, utcnow


def _p(v: float | None) -> str:
    return _pc(v, 2, True)


def _movers(stocks: list[dict], n: int = 5) -> tuple[list[dict], list[dict]]:
    rows = [r for r in stocks if r.get("day_pct") is not None]
    rows.sort(key=lambda r: r["day_pct"], reverse=True)
    pick = lambda r: {"symbol": r["symbol"], "name": r["name"], "day_pct": r["day_pct"], "price": r.get("price"),
                      "currency": r.get("currency"), "rvol": r.get("rvol")}
    return [pick(r) for r in rows[:n]], [pick(r) for r in rows[::-1][:n]]


def morning(ctx: dict, s: Settings) -> dict:
    today = utcnow().astimezone(s.tz).date().isoformat()
    sections = []
    us = [i for i in ctx["overview"] if i["symbol"] in ("^GSPC", "^NDX", "^DJI") and i.get("available")]
    if us:
        sections.append({"title": "Was ist über Nacht passiert?", "tag": "BESTÄTIGTE DATEN",
                         "items": [f"{i['name']}: letzter Schluss {_p(i.get('day_pct'))} ({i['quote']['time'][:16].replace('T', ' ')} UTC)" for i in us]})
    on = [i for i in ctx["overnight"] if i.get("available")]
    if on:
        sections.append({"title": "Internationale Märkte", "tag": "BESTÄTIGTE DATEN",
                         "items": [f"{i['name']}: {_p(i.get('day_pct'))}, Trend {i['trend']}" for i in on]})
    news = ctx.get("market_news") or []
    if news:
        sections.append({"title": "Wichtige Nachrichten", "tag": "BESTÄTIGTE NACHRICHT (Überschriften, Quelle verlinkt)",
                         "items": [{"text": n["title"], "url": n.get("url"), "source": n.get("publisher")} for n in news[:6]]})
    else:
        own = ctx.get("watch_news") or []
        sections.append({"title": "Wichtige Nachrichten (Depot & Watchlist)", "tag": "BESTÄTIGTE NACHRICHT",
                         "items": [{"text": f"{n['symbol']}: {n['title']}", "url": n.get("url"), "source": n.get("publisher")} for n in own[:6]]
                         or ["Keine neuen Meldungen. Für allgemeine Marktnachrichten FINNHUB_API_KEY setzen."]})
    focus = [x for x in ctx["signals_short"] if x["rating"] in ("STRONG BUY", "BUY", "SELL", "STRONG SELL")][:6]
    sections.append({"title": "Aktien im Fokus", "tag": "EIGENE MODELLINTERPRETATION",
                     "items": [f"{x['name']} ({x['symbol']}): {x['rating']} kurzfristig, Score {x['score']} – {x['pros'][0] if x['pros'] else x['reason'][:120]}" for x in focus]
                     or ["Heute keine Werte mit bestätigtem Kauf- oder Verkaufssignal."]})
    cal = [e for e in ctx["calendar"]["events"] if e["date"] <= _plus(today, 1)]
    sections.append({"title": "Termine heute und morgen", "tag": "BESTÄTIGTE DATEN",
                     "items": [f"{e['date']}: {e['title']} – {e['why']}" for e in cal] or ["Keine eingetragenen Termine."]})
    risks = []
    v = ctx["sentiment"].get("vix")
    if v and v["value"] >= 20:
        risks.append(f"VIX bei {_n(v['value'], 1)} – erhöhte Schwankungen möglich.")
    for e in cal:
        if e["category"] in ("fed", "ecb", "inflation", "labor"):
            risks.append(f"{e['title']}: Zinserwartungen können sich schnell verschieben.")
        if e.get("in_depot"):
            risks.append(f"{e['title']} betrifft dein Depot – Kurslücke möglich.")
    risks += [w["text"] for w in ctx["risk_warnings"] if w["level"] in ("HIGH", "MEDIUM")][:4]
    sections.append({"title": "Mögliche Risiken heute", "tag": "EIGENE MODELLINTERPRETATION", "items": risks or ["Keine besonderen Risiken in den Daten erkennbar."]})
    rep = _wrap("morning", "Morgenbericht", sections, ctx, s,
                "Schreibe einen Morgenkommentar (6–8 Sätze): Was ist über Nacht passiert, was ist heute wichtig, welche Risiken bestehen?")
    return rep


def intraday(ctx: dict, s: Settings) -> dict:
    up, down = _movers(ctx["stock_rows"])
    sections = [{"title": "Auffällige Kursbewegungen", "tag": "BESTÄTIGTE DATEN",
                 "items": [f"▲ {m['name']}: {_p(m['day_pct'])}" + (f", Volumen {_n(m['rvol'], 1)}×" if m.get("rvol") else "") for m in up[:4]] +
                          [f"▼ {m['name']}: {_p(m['day_pct'])}" + (f", Volumen {_n(m['rvol'], 1)}×" if m.get("rvol") else "") for m in down[:4]]}]
    own = ctx.get("watch_news") or []
    sections.append({"title": "Neue Unternehmensnachrichten", "tag": "BESTÄTIGTE NACHRICHT",
                     "items": [{"text": f"{n['symbol']}: {n['title']}", "url": n.get("url"), "source": n.get("publisher")} for n in own[:6]] or ["Keine neuen Meldungen für Depot und Watchlist."]})
    ch = ctx.get("rating_changes") or []
    sections.append({"title": "Veränderte technische Lage & neue Signale", "tag": "EIGENE MODELLINTERPRETATION",
                     "items": [f"{c['name']} ({c['symbol']}, {'kurzfristig' if c['horizon'] == 'short' else 'langfristig'}): {c.get('prev_rating') or 'neu'} → {c['rating']}" for c in ch[:10]]
                     or ["Keine Änderungen der Einstufungen seit dem letzten Lauf."]})
    return _wrap("intraday", "Zwischenbericht", sections, ctx, s,
                 "Schreibe einen kurzen Zwischenstand (4–5 Sätze) zum laufenden Handelstag.")


def evening(ctx: dict, s: Settings) -> dict:
    idx = [i for i in ctx["overview"] if i.get("available")]
    sections = [{"title": "Zusammenfassung des Handelstages", "tag": "BESTÄTIGTE DATEN",
                 "items": [f"{i['name']}: {_p(i.get('day_pct'))} (Woche {_p(i.get('week_pct'))})" for i in idx]}]
    up, down = _movers(ctx["stock_rows"])
    sections.append({"title": "Gewinner", "tag": "BESTÄTIGTE DATEN", "items": [f"{m['name']}: {_p(m['day_pct'])}" for m in up]})
    sections.append({"title": "Verlierer", "tag": "BESTÄTIGTE DATEN", "items": [f"{m['name']}: {_p(m['day_pct'])}" for m in down]})
    v = ctx["depot_val"]
    sections.append({"title": "Dein virtuelles Depot", "tag": "BESTÄTIGTE DATEN (Planspiel)",
                     "items": [f"Depotwert {_n(v['total_eur'], 2)} € ({_p(v['pnl_pct'])} seit Start), heute {_n(v['day_eur'], 2, True)} €",
                               f"Cash {_n(v['cash_eur'], 2)} €, {len(v['positions'])} Positionen"] +
                              [f"{p['name']}: {_p(p.get('unrealized_pct'))} seit Kauf" for p in v["positions"][:6]]})
    ev = ctx.get("recent_evaluations") or []
    sections.append({"title": "Bewertung früherer Signale", "tag": "BESTÄTIGTE DATEN",
                     "items": [f"{e['name'] or e['symbol']}: {e['rating']} vom {e['time'][:10]} nach {e['days']} Tagen {_p(e['return_net_directional'])} netto in Signalrichtung – {'Treffer' if e['hit'] else 'Fehlschlag'}" for e in ev[:8]]
                     or ["Heute wurden keine Signale fällig."]})
    nxt = sorted([x for x in ctx["signals_short"] if x["rating"] in ("BUY", "STRONG BUY")], key=lambda x: -x["score"])[:6]
    sections.append({"title": "Interessant für den nächsten Handelstag", "tag": "EIGENE MODELLINTERPRETATION",
                     "items": [f"{x['name']} ({x['symbol']}): {x['rating']}, Score {x['score']}, CRV {x['levels'].get('crv') or 'n. v.'}, Unsicherheit {x['uncertainty']['level']}" for x in nxt]
                     or ["Keine Werte mit bestätigtem Kaufszenario."]})
    return _wrap("evening", "Abendbericht", sections, ctx, s,
                 "Schreibe eine Tageszusammenfassung (6–8 Sätze): Marktverlauf, auffällige Werte, Depotentwicklung, Ausblick auf morgen ohne Prognosen.")


def _wrap(kind: str, title: str, sections: list[dict], ctx: dict, s: Settings, llm_task: str) -> dict:
    now = utcnow()
    rep: dict[str, Any] = {"kind": kind, "title": title, "date": now.astimezone(s.tz).date().isoformat(), "time": iso(now),
                           "sections": sections, "environment": ctx["environment"], "demo": ctx.get("demo", False),
                           "sources": ctx.get("sources", [])}
    commentary = llm.comment(s, llm_task, {"sections": sections, "environment": ctx["environment"], "sentiment": ctx["sentiment"].get("label")})
    if commentary:
        rep["commentary"] = {"text": commentary, "tag": "KI-TEXT (nur auf Basis der gelieferten Daten)", "model": s.get("reports.llm.model")}
    return rep


def _plus(d: str, n: int) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def to_telegram(rep: dict) -> str:
    import html
    e = html.escape
    out = [f"<b>{e(rep['title'])} – {e(rep['date'])}</b>", f"Umfeld: <b>{e(rep['environment']['verdict'])}</b>"]
    for sec in rep["sections"][:6]:
        out.append(f"\n<b>{e(sec['title'])}</b>")
        for it in sec["items"][:5]:
            out.append("• " + e(it["text"] if isinstance(it, dict) else str(it)))
    if rep.get("commentary"):
        out.append("\n<i>" + e(rep["commentary"]["text"][:900]) + "</i>")
    return "\n".join(out)[:4000]
