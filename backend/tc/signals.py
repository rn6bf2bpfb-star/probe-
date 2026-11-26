"""Signal-Historie und ehrliche Erfolgsstatistik (inkl. Fehlschlägen und Kosten)."""
from __future__ import annotations

from statistics import mean, median
from typing import Any

import pandas as pd

from .config import JsonStore, Settings, iso, parse_iso, utcnow
from .data.hub import DataHub


class SignalBook:
    def __init__(self, store: JsonStore, s: Settings) -> None:
        self.store = store
        self.s = s
        self.history: list[dict] = store.load("signal_history", [])

    def last_for(self, sym: str, horizon: str) -> dict | None:
        for r in reversed(self.history):
            if r["symbol"] == sym and r["horizon"] == horizon:
                return r
        return None

    def record(self, sig: dict) -> dict | None:
        """Speichert ein Signal, wenn sich die Einstufung geändert hat. Gibt den neuen Eintrag zurück."""
        prev = self.last_for(sig["symbol"], sig["horizon"])
        if prev and prev["rating"] == sig["rating"]:
            return None
        q = sig["quote"]
        if q.get("price") is None:
            return None
        rec = {"id": f"{sig['symbol']}|{sig['horizon']}|{sig['time']}", "symbol": sig["symbol"], "name": sig.get("name"),
               "horizon": sig["horizon"], "rating": sig["rating"], "prev_rating": prev["rating"] if prev else None,
               "score": sig["score"], "time": sig["time"], "price": q["price"], "price_time": q.get("time"),
               "price_quality": q.get("quality"), "currency": q.get("currency"),
               "risk_level": sig["levels"].get("risk_level"), "target_base": sig["levels"].get("scenario_base"),
               "evaluations": {}, "status": "offen" if sig["rating"] != "HOLD" else "nicht bewertet (HOLD)"}
        self.history.append(rec)
        return rec

    def evaluate(self, hub: DataHub, bench_for: dict[str, str]) -> None:
        cost = float(self.s.get("signals.roundtrip_cost_percent", 0.3)) / 100
        for r in self.history:
            if r["rating"] == "HOLD":
                continue
            hs = self.s.get("signals.track_horizons_short", [5, 20]) if r["horizon"] == "short" else self.s.get("signals.track_horizons_long", [60, 120])
            d = hub.daily(r["symbol"])
            if d is None or not d.ok:
                continue
            c = d.df["Close"].dropna()
            t0 = parse_iso(r["time"])
            after = c[c.index > pd.Timestamp(t0)]
            direction = 1 if "BUY" in r["rating"] else -1
            # Verlustbereich vor Ziel erreicht? (nur kurzfristig)
            if r["horizon"] == "short" and r.get("risk_level") and "stop_hit" not in r:
                lows = d.df["Low"][d.df.index > pd.Timestamp(t0)].head(max(hs))
                highs = d.df["High"][d.df.index > pd.Timestamp(t0)].head(max(hs))
                for ts in lows.index:
                    hit_stop = lows[ts] <= r["risk_level"] if direction > 0 else highs[ts] >= r["risk_level"]
                    hit_tgt = r.get("target_base") and (highs[ts] >= r["target_base"] if direction > 0 else lows[ts] <= r["target_base"])
                    if hit_stop:
                        r["stop_hit"] = iso(ts.to_pydatetime())
                        break
                    if hit_tgt:
                        r["target_hit"] = iso(ts.to_pydatetime())
                        break
            bsym = bench_for.get(r["symbol"])
            b = hub.daily(bsym) if bsym else None
            for h in hs:
                key = str(h)
                if key in r["evaluations"] or len(after) < h:
                    continue
                p1 = float(after.iloc[h - 1])
                gross = p1 / r["price"] - 1
                net = direction * gross - cost
                ev = {"date": after.index[h - 1].date().isoformat(), "price": p1, "return_gross": gross,
                      "return_net_directional": net, "hit": net > 0}
                if b is not None and b.ok:
                    bc = b.df["Close"].dropna()
                    b0 = bc[bc.index <= pd.Timestamp(t0)]
                    b1 = bc[bc.index <= after.index[h - 1]]
                    if len(b0) and len(b1):
                        ev["bench_return"] = float(b1.iloc[-1] / b0.iloc[-1] - 1)
                        ev["excess_directional"] = direction * (gross - ev["bench_return"])
                r["evaluations"][key] = ev
            if all(str(h) in r["evaluations"] for h in hs):
                r["status"] = "ausgewertet"

    def stats(self) -> dict[str, Any]:
        groups: dict[str, list[dict]] = {}
        for r in self.history:
            for h, ev in r["evaluations"].items():
                groups.setdefault(f"{r['horizon']}|{r['rating']}|{h}", []).append({**ev, "symbol": r["symbol"], "time": r["time"]})
                groups.setdefault(f"{r['horizon']}|ALLE|{h}", []).append({**ev, "symbol": r["symbol"], "time": r["time"]})
        rows = []
        for k, evs in sorted(groups.items()):
            horizon, rating, h = k.split("|")
            nets = [e["return_net_directional"] for e in evs]
            ex = [e["excess_directional"] for e in evs if e.get("excess_directional") is not None]
            rows.append({"horizon": horizon, "rating": rating, "days": int(h), "n": len(evs),
                         "hit_rate": sum(1 for e in evs if e["hit"]) / len(evs),
                         "avg_net": mean(nets), "median_net": median(nets), "best": max(nets), "worst": min(nets),
                         "avg_excess": mean(ex) if ex else None})
        failures = []
        for r in self.history:
            for h, ev in r["evaluations"].items():
                if not ev["hit"]:
                    failures.append({"symbol": r["symbol"], "rating": r["rating"], "horizon": r["horizon"], "time": r["time"],
                                     "days": int(h), "return_net_directional": ev["return_net_directional"],
                                     "stop_hit": r.get("stop_hit")})
        failures.sort(key=lambda x: x["return_net_directional"])
        stop_n = sum(1 for r in self.history if r.get("stop_hit"))
        tgt_n = sum(1 for r in self.history if r.get("target_hit"))
        open_n = sum(1 for r in self.history if r["status"] == "offen")
        return {"rows": rows, "failures": failures[:25], "stop_hits": stop_n, "target_hits": tgt_n,
                "open": open_n, "total": len(self.history),
                "method": f"Rendite in Signalrichtung (SELL = fallender Kurs ist Treffer) abzüglich {self.s.get('signals.roundtrip_cost_percent', 0.3)} % Kosten je Signal. "
                          "Einstieg zum letzten verfügbaren Kurs bei Signalerzeugung, Auswertung zum Schlusskurs nach N Handelstagen. HOLD wird nicht bewertet.",
                "note": "Kleine Stichproben sind statistisch nicht aussagekräftig. Vergangene Treffer sagen nichts über künftige aus."}

    def save(self) -> None:
        self.store.save("signal_history", self.history[-3000:])
