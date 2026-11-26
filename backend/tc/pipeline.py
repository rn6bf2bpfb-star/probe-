"""Ein Lauf = Daten holen → Orders ausführen → analysieren → Alerts → Bericht → Website-Daten schreiben."""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any

import pandas as pd

from . import alerts as al
from . import analyst as an
from . import market as mk
from . import reports as rp
from . import risk as rk
from .config import DATA_OUT, STATE_DIR, JsonStore, Settings, env, iso, utcnow, write_site_json
from .data.base import suffix
from .data.hub import DataHub
from .depot import Depot
from .econ_calendar import build_calendar
from .fx import FX
from .indicators import compute_all, sma
from .signals import SignalBook

log = logging.getLogger("tc")


def make_provider(demo: bool, now: datetime | None = None, scenarios: dict | None = None):
    if demo:
        from .data.synthetic import SyntheticProvider
        return SyntheticProvider(scenarios=scenarios, now=now)
    from .data.yahoo import YahooProvider
    return YahooProvider()


def report_kind(s: Settings, meta: dict, forced: str) -> str:
    if forced != "auto":
        return forced
    local = utcnow().astimezone(s.tz)
    today = local.date().isoformat()
    if local.weekday() >= 5:
        return "none"
    if local.hour < 10 and meta.get("last_morning") != today:
        return "morning"
    if local.hour >= 22 and meta.get("last_evening") != today:
        return "evening"
    if 9 <= local.hour < 22:
        return "intraday"
    return "none"


class Run:
    def __init__(self, demo: bool = False, provider: Any = None, report: str = "auto", send: bool = True) -> None:
        self.t0 = time.time()
        self.s = Settings()
        self.store = JsonStore()
        self.demo = demo
        self.hub = DataHub(self.s, provider or make_provider(demo), self.store, demo=demo, use_rest=not demo)
        self.meta = self.store.load("meta", {})
        self.report_arg = report
        self.send = send and not demo
        self.cmd_log: list[dict] = self.store.load("command_log", [])

    # ---------------------------------------------------------------- Befehle
    def _watchlist(self) -> list[str]:
        wl = self.store.load("watchlist", None)
        return wl if wl is not None else list(self.s.universe.get("watchlist", []) or [])

    def _price_alerts(self) -> list[dict]:
        pa = self.store.load("price_alerts", None)
        if pa is None:
            from .config import load_yaml
            pa = []
            for i, a in enumerate(load_yaml("price_alerts.yaml").get("price_alerts", []) or []):
                pa.append({"id": f"cfg{i}", **a, "active": True})
        return pa

    def commands(self, extra: list[dict]) -> list[dict]:
        inbox = STATE_DIR / "inbox"
        cmds = []
        for p in sorted(inbox.glob("*.json")):
            try:
                cmds.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Befehl %s unlesbar: %s", p.name, e)
                p.unlink(missing_ok=True)
        return [(None, c) for c in extra] + cmds

    def apply_commands(self, depot: Depot, cmds: list, known: set[str]) -> list[dict]:
        results = []
        wl = self._watchlist()
        pa = self._price_alerts()
        etfs = set(self.s.etf_symbols)
        for path, c in cmds:
            typ = c.get("type")
            res: dict[str, Any] = {"time": iso(utcnow()), "command": {k: v for k, v in c.items() if k != "token"}, "ok": True}
            try:
                if typ == "order":
                    c = {**c, "kind": "etf" if (c.get("symbol") or "").upper() in etfs else "stock"}
                    o = depot.place(c, known)
                    res.update({"ok": o["status"] != "abgelehnt", "message": o.get("reason") or f"Order {o['id']} angenommen", "order_id": o["id"]})
                elif typ == "cancel":
                    ok = depot.cancel(c.get("order_id", ""))
                    res.update({"ok": ok, "message": "storniert" if ok else "Order nicht gefunden oder nicht mehr offen"})
                elif typ == "reset":
                    depot.reset()
                    res["message"] = "Depot zurückgesetzt"
                elif typ == "watch_add":
                    sym = (c.get("symbol") or "").upper()
                    if sym and sym not in wl:
                        wl.append(sym)
                    res["message"] = f"{sym} auf der Watchlist"
                elif typ == "watch_remove":
                    sym = (c.get("symbol") or "").upper()
                    wl = [w for w in wl if w != sym]
                    res["message"] = f"{sym} entfernt"
                elif typ == "price_alert_add":
                    a = {"id": hashlib.md5(json.dumps(c, sort_keys=True).encode()).hexdigest()[:8], "ticker": (c.get("symbol") or "").upper(),
                         "direction": c.get("direction", "above"), "level": float(str(c.get("level")).replace(",", ".")),
                         "note": c.get("note", ""), "active": True, "created": iso(utcnow())}
                    pa.append(a)
                    res["message"] = f"Kursmarke {a['ticker']} {a['direction']} {a['level']} angelegt"
                elif typ == "price_alert_remove":
                    pa = [a for a in pa if a["id"] != c.get("id")]
                    res["message"] = "Kursmarke entfernt"
                else:
                    res.update({"ok": False, "message": f"unbekannter Befehl {typ}"})
            except Exception as e:  # noqa: BLE001
                res.update({"ok": False, "message": str(e)[:200]})
            results.append(res)
            if path is not None:
                path.unlink(missing_ok=True)
        self.store.save("watchlist", wl)
        self.store.save("price_alerts", pa)
        self.cmd_log = (self.cmd_log + results)[-200:]
        return results

    # ------------------------------------------------------------------ Lauf
    def execute(self, extra_commands: list[dict] | None = None) -> dict:
        s, hub = self.s, self.hub
        now = utcnow()
        kind = report_kind(s, self.meta, self.report_arg)
        log.info("Lauf startet (%s), Bericht: %s", "DEMO" if self.demo else "LIVE", kind)
        depot = Depot(self.store, s)
        stocks, etfs = s.stocks, s.etf_symbols
        watch = self._watchlist()
        cmds = self.commands(extra_commands or [])
        order_syms = {(c.get("symbol") or "").upper() for _, c in cmds if c.get("type") == "order"}
        holdings = set(depot.d["positions"])
        open_syms = {o["symbol"] for o in depot.d["orders"] if o["status"] == "offen"}
        bench_map = s.universe.get("benchmarks", {})
        benches = set(bench_map.get("by_suffix", {}).values()) | {bench_map.get("default", "EUNL.DE")}
        universe = list(dict.fromkeys(stocks + etfs + watch + sorted(holdings) + sorted(open_syms) + sorted(order_syms - {""})))
        hub.load_daily(universe + sorted(benches))
        hub.load_intraday(universe)
        known = {sym for sym in universe if hub.daily(sym) is not None and hub.daily(sym).ok}
        cmd_results = self.apply_commands(depot, cmds, known)
        watch = self._watchlist()
        fx = FX(hub, s)
        depot.process(hub, fx)
        holdings = set(depot.d["positions"])

        # ---------------- Technik
        def bench_of(sym: str) -> str:
            return bench_map.get("by_suffix", {}).get(suffix(sym), bench_map.get("default", "EUNL.DE"))

        bench_for = {sym: bench_of(sym) for sym in universe}
        tech: dict[str, dict] = {}
        for sym in universe:
            d = hub.daily(sym)
            if d is None or not d.ok:
                continue
            df = d.df.copy()
            q = hub.quote(sym)
            # aktuellen Intraday-Kurs als laufenden Tagesbalken berücksichtigen
            if q.price is not None and q.time and q.time > df.index[-1].to_pydatetime() and q.time.date() > df.index[-1].date():
                df.loc[pd.Timestamp(q.time).normalize()] = [q.price, q.price, q.price, q.price, float("nan")]
            b = hub.daily(bench_for[sym])
            t = compute_all(df, b.df["Close"] if b is not None and b.ok else None)
            t["last"] = float(df["Close"].iloc[-1])
            tech[sym] = t

        # ---------------- Fundamentaldaten & Ereignisse
        refresh_all = kind in ("morning",) or not self.store.path("cache/fundamentals").exists()
        funds: dict[str, dict] = {}
        for sym in stocks + [w for w in watch if w not in etfs] + [h for h in holdings if h not in etfs]:
            if sym in known:
                funds[sym] = hub.fundamentals(sym, refresh=refresh_all or sym in holdings or sym in watch)
        priority = set(watch) | holdings
        events: dict[str, dict] = {}
        for sym in [x for x in stocks + etfs + watch + sorted(holdings) if x in known]:
            if sym in events:
                continue
            events[sym] = hub.events(sym, max_age_hours=3.0 if sym in priority else 20.0)
        names = {e["symbol"]: e["name"] for e in s.etfs}
        for sym, f in funds.items():
            if f.get("name"):
                names[sym] = f["name"]
        medians = an.sector_medians(funds)

        # ---------------- Markt
        overview = mk.build_overview(hub, s)
        overnight = mk.build_overnight(hub, s)
        sent = mk.sentiment(hub, s, {k: v for k, v in tech.items() if k in stocks})
        macro = hub.macro()
        env_ = mk.environment(sent, overview, macro)
        market_news = [an.classify_news(n) for n in hub.market_news()]

        # ---------------- Signale
        book = SignalBook(self.store, s)
        signals: dict[str, dict[str, dict]] = {}
        changes: list[dict] = []
        for sym in [x for x in universe if x in tech]:
            is_etf = sym in etfs
            q = hub.quote(sym).as_dict()
            te = an.tech_eval(tech[sym])
            fe = an.fund_eval(funds.get(sym, {}), medians, is_etf=is_etf)
            ne = an.news_eval(events.get(sym, {}), now, int(s.get("data.news_max_age_days", 7)))
            nm = names.get(sym, sym)
            signals[sym] = {}
            for h in ("short", "long"):
                sig = an.build_signal(sym, nm, q, tech[sym], te, fe, ne, env_, s, h, is_etf=is_etf)
                signals[sym][h] = sig
                rec = book.record(sig)
                if rec and rec.get("prev_rating") is not None or (rec and rec["rating"] != "HOLD"):
                    changes.append(rec)
        before = {r["id"]: set(r["evaluations"]) for r in book.history}
        book.evaluate(hub, bench_for)
        recent_evals = []
        for r in book.history:
            for h, ev in r["evaluations"].items():
                if h not in before.get(r["id"], set()):
                    recent_evals.append({**ev, "symbol": r["symbol"], "name": r.get("name"), "rating": r["rating"], "time": r["time"], "days": int(h)})

        # ---------------- Depot & Risiko
        val = depot.valuation(hub, fx, funds, names)
        depot.snapshot(val)
        rf = (macro.get("deposit_rate") or {}).get("value", 0.0) / 100 if macro.get("deposit_rate") else 0.0
        em = rk.equity_metrics(depot.d["equity"], rf)
        ts = rk.trade_stats(depot.d["transactions"])
        div = rk.diversification(val)
        corr = rk.correlations(hub, list(holdings))
        warn = rk.warnings(val, div, ts, em, tech, depot.d, s)
        rscore = rk.risk_score(val, div, em, tech)
        bench_sym = bench_map.get("default", "EUNL.DE")
        bench_perf = None
        bd = hub.daily(bench_sym)
        if bd is not None and bd.ok:
            c = bd.df["Close"].dropna()
            start = pd.Timestamp(depot.d["created"])
            base = c[c.index <= start]
            bench_perf = float(c.iloc[-1] / (base.iloc[-1] if len(base) else c.iloc[0]) - 1)

        # ---------------- Watchlist-/Depot-News (neu seit letztem Lauf)
        seen = set(self.meta.get("seen_news", []))
        watch_news = []
        for sym in sorted(priority):
            for n in (events.get(sym) or {}).get("news", [])[:10]:
                h = hashlib.md5(f"{sym}{n.get('title')}".encode()).hexdigest()[:12]
                if h not in seen:
                    seen.add(h)
                    watch_news.append({**an.classify_news(n), "symbol": sym, "hash": h})

        # ---------------- Alerts
        center = al.AlertCenter(self.store, s)
        self._alerts(center, signals, changes, tech, names, holdings, set(watch), watch_news, events, sent, env_, warn, depot, hub)

        # ---------------- Kalender & Screener
        cal = build_calendar(s, hub.release_calendar(), events, names, holdings, set(watch))
        rows = self._rows(universe, tech, funds, signals, names, hub, fx, etfs)
        picks = self._picks(rows, signals)

        # ---------------- Bericht
        ctx = {"overview": overview, "overnight": overnight, "sentiment": sent, "environment": env_, "market_news": market_news,
               "watch_news": watch_news, "signals_short": sorted([v["short"] for v in signals.values()], key=lambda x: -x["score"]),
               "calendar": cal, "risk_warnings": warn, "stock_rows": [r for r in rows if r["kind"] == "stock"],
               "rating_changes": changes, "depot_val": val, "recent_evaluations": recent_evals, "demo": self.demo}
        report = None
        if kind == "morning":
            report = rp.morning(ctx, s)
            self.meta["last_morning"] = utcnow().astimezone(s.tz).date().isoformat()
        elif kind == "evening":
            report = rp.evening(ctx, s)
            self.meta["last_evening"] = utcnow().astimezone(s.tz).date().isoformat()
        elif kind == "intraday":
            report = rp.intraday(ctx, s)
        delivery = center.dispatch(self.send)
        if not self.send:
            delivery = {"hinweis": "Versand deaktiviert (Demo/Test) – Meldungen nur im Dashboard"}
        if report and kind in ("morning", "evening") and self.send:
            tg = al.Telegram()
            if tg.enabled:
                try:
                    tg.send_text(rp.to_telegram(report))
                except Exception as e:  # noqa: BLE001
                    delivery["bericht"] = f"Telegram-Bericht fehlgeschlagen: {e}"

        # ---------------- Ausgabe
        self._write(overview, overnight, sent, macro, env_, market_news, signals, tech, funds, events, names, rows, picks,
                    val, depot, em, ts, div, corr, warn, rscore, bench_perf, bench_sym, center, cal, book, report, kind,
                    cmd_results, delivery, hub, watch)
        self.meta["seen_news"] = list(seen)[-3000:]
        self.meta["last_sentiment"] = sent.get("label")
        self.meta["last_verdict"] = env_["verdict"]
        self.meta["last_run"] = iso(utcnow())
        self.store.save("meta", self.meta)
        self.store.save("command_log", self.cmd_log)
        depot.save()
        book.save()
        center.save()
        hub.persist()
        took = time.time() - self.t0
        log.info("Lauf fertig in %.0f s: %d Werte, %d neue Alerts, %d Datenlücken", took, len(tech), len(center.new), len(hub.gaps.items))
        return {"kind": kind, "symbols": len(tech), "alerts": len(center.new), "gaps": len(hub.gaps.items), "seconds": round(took),
                "commands": cmd_results, "delivery": delivery}

    # ----------------------------------------------------------------- Regeln
    def _alerts(self, center, signals, changes, tech, names, holdings, watch, watch_news, events, sent, env_, warn, depot, hub):
        s = self.s
        today = utcnow().date().isoformat()
        first_run = not self.meta.get("last_run")  # beim allerersten Lauf keine Signalflut melden
        for rec in ([] if first_run else changes):
            sym = rec["symbol"]
            sig = signals[sym][rec["horizon"]]
            h_de = "kurzfristig" if rec["horizon"] == "short" else "langfristig"
            if rec["rating"] in ("BUY", "STRONG BUY"):
                center.add(al.make_alert(
                    "buy_opportunity", "HIGH" if rec["rating"] == "STRONG BUY" else "MEDIUM", sym, names.get(sym, sym),
                    f"Neues Kaufszenario ({h_de}): {rec.get('prev_rating') or 'neu'} → {rec['rating']}",
                    sig["reason"][:400], "; ".join(sig["counterarguments"][:2]) or "siehe Analyse",
                    "Aktie genauer beobachten und das Szenario anhand der aktuellen Daten überprüfen. Im Planspiel ggf. mit Stop-Loss testen.",
                    sig["quote"], f"{sig['quote'].get('source')} + eigene Analyse", sig["quote"].get("time"), an.INTERP,
                    f"sig|{sym}|{rec['horizon']}|{rec['rating']}|{today}", signal_label=f"MÖGLICHES KAUFSZENARIO ({rec['rating']})", is_signal=True))
            elif rec["rating"] in ("SELL", "STRONG SELL") and sym in holdings:
                center.add(al.make_alert(
                    "sell_signal", "HIGH", sym, names.get(sym, sym), f"Verkaufssignal ({h_de}) für eine Depotposition: {rec['rating']}",
                    sig["reason"][:400], "Ein Verkauf realisiert Gewinne/Verluste; Gegenargumente prüfen.",
                    "These der Position überprüfen; Stop-Loss enger setzen oder Teilverkauf im Planspiel erwägen.",
                    sig["quote"], f"{sig['quote'].get('source')} + eigene Analyse", sig["quote"].get("time"), an.INTERP,
                    f"sig|{sym}|{rec['horizon']}|{rec['rating']}|{today}", signal_label=f"VERKAUFSSZENARIO ({rec['rating']})", is_signal=True))
        # Kursmarken
        pa = self._price_alerts()
        changed = False
        for a in pa:
            if not a.get("active"):
                continue
            q = hub.quote(a["ticker"])
            if q.price is None:
                continue
            hit = q.price >= a["level"] if a["direction"] == "above" else q.price <= a["level"]
            if hit:
                a["active"] = False
                a["triggered"] = iso(utcnow())
                changed = True
                center.add(al.make_alert(
                    "price_level", "HIGH", a["ticker"], names.get(a["ticker"], a["ticker"]),
                    f"Kursmarke {a['level']} {'überschritten' if a['direction'] == 'above' else 'unterschritten'}",
                    a.get("note") or "Von dir definierte Kursmarke erreicht.", "Kursmarken sind keine Signale – Gesamtbild prüfen.",
                    "Analyse öffnen und entscheiden, ob dein Plan noch gilt.", q.as_dict(), q.source, al.iso(q.time) if q.time else None,
                    an.FACT, f"pa|{a['id']}"))
        if changed:
            self.store.save("price_alerts", pa)
        # Volumen & starke Bewegungen
        thr_move = float(s.get("alerts.strong_move_percent", 4.0)) / 100
        thr_vol = float(s.get("alerts.volume_spike_rvol", 2.5))
        for sym, t in tech.items():
            q = hub.quote(sym)
            mine = sym in holdings or sym in watch
            day = (q.price / q.prev_close - 1) if q.price and q.prev_close else None
            if day is not None and abs(day) >= thr_move:
                prio = "HIGH" if sym in holdings and abs(day) >= thr_move * 1.75 else "MEDIUM" if mine else "LOW"
                center.add(al.make_alert(
                    "strong_move", prio, sym, names.get(sym, sym), f"Starke Kursbewegung: {_pc(day, 1, True)} zum Vortag",
                    _news_hint(events.get(sym)), "Starke Bewegungen setzen sich nicht zwingend fort; Kurslücken möglich.",
                    "Ursache in den Nachrichten prüfen, nicht impulsiv handeln.", q.as_dict(), q.source, al.iso(q.time) if q.time else None,
                    an.FACT, f"mv|{sym}|{today}|{'up' if day > 0 else 'dn'}"))
            rv = t.get("rvol")
            if rv is not None and rv >= thr_vol and (t.get("volume") or 0) > 0:
                center.add(al.make_alert(
                    "volume_spike", "MEDIUM" if mine else "LOW", sym, names.get(sym, sym), f"Ungewöhnlich hohes Handelsvolumen ({_n(rv, 1)}× Durchschnitt)",
                    f"Volumen deutlich über dem 20-Tage-Schnitt bei Tagesveränderung {_pc((t.get('perf_1d') or 0), 1, True)}. {_news_hint(events.get(sym))}",
                    "Hohes Volumen kann Trendwechsel oder Nachrichtenreaktion anzeigen – Richtung noch offen.",
                    "Beobachten, ob der Kurs die Bewegung am nächsten Tag bestätigt.", q.as_dict(), q.source, al.iso(q.time) if q.time else None,
                    an.FACT, f"vol|{sym}|{today}"))
        # Nachrichten & Quartalszahlen
        for n in watch_news[:20]:
            imp = any(c in n["categories"] for c in ("Übernahme/Fusion", "Management", "Quartalszahlen"))
            center.add(al.make_alert(
                "news", "MEDIUM" if imp or n["symbol"] in holdings else "LOW", n["symbol"], names.get(n["symbol"], n["symbol"]),
                f"Nachricht ({', '.join(n['categories'])}): {n['title']}", (n.get("summary") or "Siehe Originalquelle.")[:300],
                f"Tonalität laut Stichwortanalyse {n['tone']} – Inhalt in der Originalquelle prüfen.",
                "Originalmeldung lesen und Auswirkungen auf deine These prüfen.", hub.quote(n["symbol"]).as_dict(),
                f"{n.get('publisher') or '?'} via {n.get('via')}", n.get("published"), "BESTÄTIGTE NACHRICHT", f"news|{n['hash']}", link=n.get("url")))
        for sym in sorted(holdings | watch):
            for e in (events.get(sym) or {}).get("earnings", [])[:3]:
                d = an._parse_dt(e.get("date"))
                if e.get("eps_reported") is not None and d and (utcnow() - d).days <= 2:
                    sp = e.get("surprise_pct")
                    center.add(al.make_alert(
                        "earnings", "HIGH" if sym in holdings else "MEDIUM", sym, names.get(sym, sym), "Neue Quartalszahlen veröffentlicht",
                        f"EPS {e['eps_reported']} vs. Erwartung {e.get('eps_estimate')}" + (f" ({_n(sp, 1, True)} % Überraschung)" if sp is not None else "") + ".",
                        "Reaktion auf Zahlen hängt stark vom Ausblick ab, nicht nur vom EPS.", "Bericht und Ausblick in den IR-Unterlagen lesen.",
                        hub.quote(sym).as_dict(), "Yahoo Finance (Earnings)", e.get("date"), an.FACT, f"earn|{sym}|{str(e.get('date'))[:10]}"))
        # Marktstimmung
        if self.meta.get("last_sentiment") and sent.get("label") and sent["label"] != self.meta["last_sentiment"]:
            center.add(al.make_alert(
                "sentiment", "MEDIUM", "MARKT", "Marktstimmung", f"Stimmung wechselt: {self.meta['last_sentiment']} → {sent['label']} ({sent['score']}/100)",
                "; ".join(c["detail"] for c in sent["components"][:3]), "Stimmungsindikatoren sind keine Timing-Signale.",
                "Risiko im Depot an das veränderte Umfeld anpassen.", None, "eigene Berechnung", sent["time"], an.INTERP, f"sent|{sent['label']}|{today}"))
        if self.meta.get("last_verdict") and env_["verdict"] != self.meta["last_verdict"]:
            center.add(al.make_alert(
                "environment", "MEDIUM", "MARKT", "Marktumfeld", f"Marktumfeld jetzt {env_['verdict']} (vorher {self.meta['last_verdict']})",
                env_["explanation"], "Einschätzung aus Regeln; kann schnell wieder drehen.", "Signale und Positionsgrößen strenger prüfen.",
                None, "eigene Berechnung", iso(utcnow()), an.INTERP, f"env|{env_['verdict']}|{today}"))
        # Risiko im Depot
        for w in warn:
            if w["level"] in ("HIGH", "MEDIUM"):
                sym = w.get("symbol") or "DEPOT"
                center.add(al.make_alert(
                    f"risk_{w['kind']}", w["level"], sym, names.get(sym, "Depot") if sym != "DEPOT" else "Depot", "Erhöhtes Risiko im Depot",
                    w["text"], "Risiko- und Positionsgrößenregeln beachten.", "Gewichtung, Stop-Loss und Streuung prüfen.",
                    hub.quote(sym).as_dict() if sym != "DEPOT" else None, "eigene Risikoanalyse", iso(utcnow()), an.INTERP, f"risk|{w['kind']}|{sym}|{today}"))
        for sym in holdings:
            t = tech.get(sym) or {}
            q = hub.quote(sym)
            stops = [o["stop"] for o in depot.d["orders"] if o["status"] == "offen" and o["symbol"] == sym and o["type"] == "STOP" and o["side"] == "SELL"]
            if stops and q.price and t.get("atr") and 0 < q.price - max(stops) < t["atr"]:
                center.add(al.make_alert(
                    "near_stop", "MEDIUM", sym, names.get(sym, sym), f"Kurs nahe am Stop-Loss {_n(max(stops), 2)}",
                    "Abstand kleiner als eine durchschnittliche Tagesschwankung (ATR).", "Ausführung zum Stop oder darunter (Kurslücke) möglich.",
                    "Stop bewusst bestätigen oder anpassen – nicht aus Angst ständig verschieben.", q.as_dict(), q.source,
                    al.iso(q.time) if q.time else None, an.FACT, f"stop|{sym}|{today}"))
        # Ausführungen im Depot
        for e in depot.events:
            o = e["order"]
            if e["kind"] == "order_filled":
                tx = e["tx"]
                center.add(al.make_alert(
                    "order_filled", "MEDIUM", o["symbol"], names.get(o["symbol"], o["symbol"]),
                    f"Planspiel-Order ausgeführt: {'Kauf' if o['side'] == 'BUY' else 'Verkauf'} {tx['qty']:g} Stück zu {_n(tx['price'], 2)} {tx['currency']}",
                    f"{o['type']}-Order {o['id']}" + (f", realisiert {_n(tx['realized_eur'], 2, True)} €" if "realized_eur" in tx else ""),
                    "Virtuelle Ausführung – keine echte Transaktion.", "Depot prüfen.", hub.quote(o["symbol"]).as_dict(),
                    "Planspiel-Engine", tx["time"], "BESTÄTIGTE DATEN (Planspiel)", f"fill|{o['id']}"))
            elif e["kind"] == "order_rejected":
                center.add(al.make_alert(
                    "order_rejected", "MEDIUM", o["symbol"] or "DEPOT", o["symbol"] or "Depot", "Planspiel-Order abgelehnt",
                    o.get("reason", "?"), "–", "Order korrigieren und neu erteilen.", None, "Planspiel-Engine", iso(utcnow()),
                    "BESTÄTIGTE DATEN (Planspiel)", f"rej|{o['id']}"))

    # --------------------------------------------------------------- Screener
    def _rows(self, universe, tech, funds, signals, names, hub, fx, etfs) -> list[dict]:
        rows = []
        for sym in universe:
            t = tech.get(sym)
            if not t:
                continue
            f = funds.get(sym, {})
            q = hub.quote(sym)
            mc = f.get("market_cap")
            ccy = f.get("currency") or q.currency
            mc_eur = fx.to_eur(mc, "GBP" if ccy == "GBp" else ccy) if mc else None
            sh, lo = signals[sym]["short"], signals[sym]["long"]
            rows.append({"symbol": sym, "name": names.get(sym, sym), "kind": "etf" if sym in etfs else "stock",
                         "sector": f.get("sector") or ("ETF" if sym in etfs else None), "industry": f.get("industry"), "country": f.get("country"),
                         "market_cap_eur": mc_eur, "price": q.price, "currency": q.currency, "quality": q.quality, "time": iso(q.time) if q.time else None,
                         "day_pct": (q.price / q.prev_close - 1) if q.price and q.prev_close else None,
                         "perf_1w": t.get("perf_1w"), "perf_1m": t.get("perf_1m"), "perf_3m": t.get("perf_3m"), "perf_6m": t.get("perf_6m"), "perf_1y": t.get("perf_1y"),
                         "pe": f.get("pe"), "forward_pe": f.get("forward_pe"), "pb": f.get("pb"), "peg": f.get("peg"),
                         "revenue_growth": f.get("revenue_growth"), "earnings_growth": f.get("earnings_growth"), "dividend_yield": f.get("dividend_yield"),
                         "rsi": t.get("rsi"), "volume": t.get("volume"), "avg_volume": t.get("avg_volume_20"), "rvol": t.get("rvol"),
                         "volatility": t.get("vol_60"), "adx": t.get("adx"), "trend": t.get("trend"), "dist_52w_high": t.get("dist_52w_high"),
                         "short_rating": sh["rating"], "short_score": sh["score"], "long_rating": lo["rating"], "long_score": lo["score"],
                         "uncertainty": sh["uncertainty"]["level"]})
        return rows

    def _picks(self, rows, signals) -> list[dict]:
        best: dict[str, dict] = {}
        for r in rows:
            if r["kind"] != "stock":
                continue
            for h in ("short", "long"):
                sig = signals[r["symbol"]][h]
                if sig["rating"] not in ("BUY", "STRONG BUY"):
                    continue
                key = r["sector"] or "Sonstige"
                cand = {"symbol": r["symbol"], "name": r["name"], "sector": key, "horizon": h, "rating": sig["rating"], "score": sig["score"],
                        "why": sig["pros"][:3], "against": sig["counterarguments"][:2], "uncertainty": sig["uncertainty"]["level"]}
                if key not in best or cand["score"] > best[key]["score"]:
                    best[key] = cand
        return sorted(best.values(), key=lambda x: -x["score"])[:10]

    # ---------------------------------------------------------------- Ausgabe
    def _write(self, overview, overnight, sent, macro, env_, market_news, signals, tech, funds, events, names, rows, picks,
               val, depot, em, ts, div, corr, warn, rscore, bench_perf, bench_sym, center, cal, book, report, kind,
               cmd_results, delivery, hub, watch):
        now = iso(utcnow())
        demo = self.demo
        sources = sorted({"Yahoo Finance (verzögert)" if not demo else "DEMO (synthetisch)"} |
                         ({"Finnhub"} if hub.finnhub and hub.finnhub.enabled else set()) |
                         ({"Financial Modeling Prep"} if hub.fmp and hub.fmp.enabled else set()) |
                         ({"FRED"} if hub.fred and hub.fred.enabled else set()) | ({"EZB Data Portal"} if hub.ecb else set()))
        write_site_json("meta", {"time": now, "demo": demo, "report_kind": kind, "sources": sources, "gaps": hub.gaps.items[-200:],
                                 "commands": cmd_results, "command_log": self.cmd_log[-30:], "delivery": delivery,
                                 "repo": env("GITHUB_REPOSITORY"), "workflow": "trading-center.yml",
                                 "llm": bool(env("ANTHROPIC_API_KEY")), "channels": {"telegram": al.Telegram().enabled, "push": al.Ntfy().enabled, "email": al.Email().enabled},
                                 "settings": {"depot": self.s.get("depot"), "signals": self.s.get("signals"), "risk": self.s.get("risk")},
                                 "watchlist": watch, "price_alerts": self._price_alerts()})
        write_site_json("market", {"time": now, "overview": overview, "overnight": overnight, "sentiment": sent, "macro": macro,
                                   "environment": env_, "news": market_news[:20]})
        light = []
        for sym, d in signals.items():
            for h in ("short", "long"):
                x = d[h]
                light.append({k: x[k] for k in ("symbol", "name", "horizon", "rating", "score", "quote", "time", "reason", "uncertainty", "levels", "pros", "counterarguments", "invalidation", "rating_note", "raw_rating")})
        write_site_json("signals", {"time": now, "signals": light, "picks": picks})
        write_site_json("screener", {"time": now, "rows": rows})
        for sym, t in tech.items():
            d = hub.daily(sym)
            df = d.df.tail(400)
            c = d.df["Close"]
            hist = {"t": [x.strftime("%Y-%m-%d") for x in df.index], "o": _r(df["Open"]), "h": _r(df["High"]), "l": _r(df["Low"]),
                    "c": _r(df["Close"]), "v": [None if pd.isna(x) else int(x) for x in df["Volume"]],
                    "sma20": _r(sma(c, 20).tail(400)), "sma50": _r(sma(c, 50).tail(400)), "sma200": _r(sma(c, 200).tail(400))}
            f = {k: v for k, v in (funds.get(sym) or {}).items() if k not in ("summary",)}
            write_site_json(f"stocks/{_safe(sym)}", {
                "symbol": sym, "name": names.get(sym, sym), "time": now, "quote": hub.quote(sym).as_dict(), "tech": t,
                "fundamentals": f, "summary": (funds.get(sym) or {}).get("summary"), "signals": signals[sym],
                "events": {"calendar": (events.get(sym) or {}).get("calendar"), "earnings": (events.get(sym) or {}).get("earnings", [])[:6],
                           "upgrades": (events.get(sym) or {}).get("upgrades", [])[:8]},
                "history": hist, "source": d.source, "currency": d.currency,
                "in_depot": sym in depot.d["positions"], "on_watchlist": sym in watch})
        eq = depot.d["equity"]
        write_site_json("depot", {"time": now, "valuation": val, "orders": depot.d["orders"][-200:], "transactions": depot.d["transactions"][-300:],
                                  "equity": eq, "metrics": em, "trades": ts, "benchmark": {"symbol": bench_sym, "since_start": bench_perf},
                                  "created": depot.d["created"], "resets": depot.d.get("resets", []), "demo": demo,
                                  "assumptions": self.s.get("depot")})
        write_site_json("risk", {"time": now, "diversification": div, "correlations": corr, "warnings": warn, "risk_score": rscore,
                                 "metrics": em, "trades": ts})
        write_site_json("alerts", {"time": now, "alerts": list(reversed(center.log[-300:])), "new": len(center.new), "delivery": delivery})
        write_site_json("calendar", {"time": now, **cal})
        hist = list(reversed(book.history[-500:]))
        write_site_json("track", {"time": now, "stats": book.stats(), "history": hist})
        # Berichte
        rep_dir = DATA_OUT / "reports"
        rep_dir.mkdir(parents=True, exist_ok=True)
        if report:
            write_site_json(f"reports/{report['date']}_{report['kind']}", report)
            self.store.save(f"reports/{report['date']}_{report['kind']}", report)
        # Index über alle gespeicherten Berichte (aus dem State, damit nichts verloren geht)
        keep = int(self.s.get("reports.keep_days", 30))
        idx = []
        st_dir = self.store.base / "reports"
        st_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(st_dir.glob("*.json"), reverse=True)
        dates = sorted({p.stem.split("_")[0] for p in files}, reverse=True)[:keep]
        for p in files:
            dt, k = p.stem.split("_", 1)
            if dt not in dates:
                p.unlink()
                continue
            idx.append({"date": dt, "kind": k, "file": f"reports/{p.stem}.json"})
            target = rep_dir / p.name
            if not target.exists():
                target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        write_site_json("reports_index", {"time": now, "reports": idx})


def _r(s: pd.Series) -> list:
    return [None if pd.isna(x) else round(float(x), 4) for x in s]


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


def _news_hint(ev: dict | None) -> str:
    news = (ev or {}).get("news") or []
    if news:
        return f"Jüngste Meldung: „{news[0].get('title')}“ ({news[0].get('publisher') or 'Quelle unbekannt'})."
    return "Keine passende Meldung in den abgerufenen Nachrichten – Ursache unklar."
