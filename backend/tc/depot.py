"""Virtuelles Depot (Planspiel). Führt KEINE echten Transaktionen aus.

Ausführungslogik (kein Look-ahead):
* Market-Order: Eröffnungskurs des ersten Kursbalkens NACH der Ordererteilung + Slippage.
* Limit-Kauf: wenn ein späterer Balken das Limit erreicht – Ausführung zum Limit oder besser (Eröffnung unter Limit).
* Stop-Kauf / Stop-Loss-Verkauf: wenn der Stop berührt wird – Ausführung zum Stop bzw. bei Kurslücke zum
  schlechteren Eröffnungskurs, jeweils + Slippage.
* Geprüft wird mit 15-Minuten-Balken (Yahoo), ersatzweise mit Tagesbalken.
"""
from __future__ import annotations

from .fmt import n as _n, pc as _pc

import math
import uuid
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .config import JsonStore, Settings, iso, parse_iso, utcnow
from .data.hub import DataHub
from .fx import FX

ORDER_TYPES = ("MARKET", "LIMIT", "STOP")


def new_depot(s: Settings) -> dict:
    cap = float(s.get("depot.start_capital", 10000))
    now = iso(utcnow())
    return {"created": now, "start_capital": cap, "cash": cap, "positions": {}, "orders": [], "transactions": [],
            "tax": {"year": utcnow().year, "allowance_used": 0.0, "loss_pot_stocks": 0.0, "loss_pot_other": 0.0, "paid_total": 0.0,
                    "paid_year": 0.0},
            "equity": [{"time": now, "value": cap, "cash": cap, "invested": 0.0}], "resets": []}


class Depot:
    def __init__(self, store: JsonStore, s: Settings) -> None:
        self.store = store
        self.s = s
        self.d: dict = store.load("depot", None) or new_depot(s)
        self.events: list[dict] = []   # für Alerts: Ausführungen, Ablehnungen

    # ------------------------------------------------------------ Befehle
    def place(self, cmd: dict, known: set[str]) -> dict:
        sym = (cmd.get("symbol") or "").strip().upper()
        side = (cmd.get("side") or "").upper()
        typ = (cmd.get("order_type") or "MARKET").upper()
        o = {"id": cmd.get("id") or uuid.uuid4().hex[:10], "created_at": cmd.get("created_at") or iso(utcnow()),
             "symbol": sym, "side": side, "type": typ, "qty": _f(cmd.get("qty")), "amount_eur": _f(cmd.get("amount_eur")),
             "limit": _f(cmd.get("limit")), "stop": _f(cmd.get("stop")), "sl": _f(cmd.get("sl")), "tp": _f(cmd.get("tp")),
             "strategy": (cmd.get("strategy") or "manuell")[:40], "note": (cmd.get("note") or "")[:200],
             "status": "offen", "oco": cmd.get("oco"), "parent": cmd.get("parent"), "kind": cmd.get("kind") or "stock",
             "valid_until": iso(utcnow() + timedelta(days=int(self.s.get("depot.order_validity_days", 90))))}
        err = None
        if side not in ("BUY", "SELL"):
            err = "Seite muss BUY oder SELL sein"
        elif typ not in ORDER_TYPES:
            err = f"Ordertyp {typ} unbekannt"
        elif sym not in known:
            err = f"{sym}: kein Kurs verfügbar – Symbol im Yahoo-Format prüfen und ggf. ins Universum aufnehmen"
        elif (o["qty"] is None or o["qty"] <= 0) and (o["amount_eur"] is None or o["amount_eur"] <= 0):
            err = "Stückzahl oder Betrag in EUR fehlt"
        elif typ == "LIMIT" and not o["limit"]:
            err = "Limit fehlt"
        elif typ == "STOP" and not o["stop"]:
            err = "Stop-Kurs fehlt"
        elif side == "SELL" and sym not in self.d["positions"] and not o["parent"]:
            err = f"{sym} ist nicht im Depot (Leerverkäufe sind im Planspiel nicht vorgesehen)"
        if o["qty"] and not self.s.get("depot.allow_fractional", True):
            o["qty"] = math.floor(o["qty"])
        if err:
            o["status"] = "abgelehnt"
            o["reason"] = err
            self.events.append({"kind": "order_rejected", "order": o})
        self.d["orders"].append(o)
        return o

    def cancel(self, order_id: str, reason: str = "vom Nutzer storniert") -> bool:
        for o in self.d["orders"]:
            if o["id"] == order_id and o["status"] == "offen":
                o["status"] = "storniert"
                o["reason"] = reason
                o["closed_at"] = iso(utcnow())
                return True
        return False

    def reset(self) -> None:
        old = {"time": iso(utcnow()), "final_value": self.d["equity"][-1]["value"] if self.d["equity"] else None}
        resets = self.d.get("resets", []) + [old]
        self.d = new_depot(self.s)
        self.d["resets"] = resets

    # --------------------------------------------------------- Ausführung
    def process(self, hub: DataHub, fx: FX) -> None:
        now = utcnow()
        for o in self.d["orders"]:
            if o["status"] == "offen" and parse_iso(o["valid_until"]) and now > parse_iso(o["valid_until"]):
                o["status"] = "abgelaufen"
                o["closed_at"] = iso(now)
        symbols = sorted({o["symbol"] for o in self.d["orders"] if o["status"] == "offen"})
        for sym in symbols:
            def open_orders():
                return [o for o in self.d["orders"] if o["status"] == "offen" and o["symbol"] == sym]
            start = min(parse_iso(o.get("last_checked") or o["created_at"]) for o in open_orders())
            bars = self._bars_after(hub, sym, start)
            if bars is None or bars.empty:
                continue
            # chronologisch über alle Orders des Werts, damit OCO-Paare korrekt reagieren
            for ts, b in bars.iterrows():
                tsd = ts.to_pydatetime()
                for o in open_orders():
                    ref = parse_iso(o.get("last_checked") or o["created_at"])
                    if self._is_daily(ts):
                        if ts.normalize() <= pd.Timestamp(ref).normalize():
                            continue
                    elif ts <= pd.Timestamp(ref):
                        continue
                    fill = self._match(o, b)
                    if fill is not None:
                        self._execute(o, fill, tsd, hub, fx)
            last = iso(bars.index[-1].to_pydatetime())
            for o in open_orders():
                if parse_iso(o.get("last_checked") or o["created_at"]) < bars.index[-1].to_pydatetime():
                    o["last_checked"] = last

    @staticmethod
    def _is_daily(ts: pd.Timestamp) -> bool:
        return ts.hour == 0 and ts.minute == 0

    def _bars_after(self, hub: DataHub, sym: str, t0: datetime) -> pd.DataFrame | None:
        i = hub.load_intraday([sym]).get(sym)
        d = hub.load_daily([sym]).get(sym)
        frames = []
        if i is not None and i.ok:
            frames.append(i.df[i.df.index > pd.Timestamp(t0)])
        if d is not None and d.ok:
            # Tagesbalken nur für Tage, die NICHT im Intraday-Fenster liegen (z. B. lange Pausen)
            dd = d.df[d.df.index.normalize() > pd.Timestamp(t0).normalize()]
            if frames and not frames[0].empty:
                dd = dd[dd.index.normalize() < frames[0].index[0].normalize()]
            frames.insert(0, dd)
        if not frames:
            return None
        out = pd.concat(frames).sort_index()
        return out[~out.index.duplicated()]

    def _match(self, o: dict, b: pd.Series) -> float | None:
        slip = float(self.s.get("depot.slippage_bps", 5)) / 10000
        op, hi, lo = float(b["Open"]), float(b["High"]), float(b["Low"])
        if any(map(math.isnan, (op, hi, lo))):
            return None
        if o["type"] == "MARKET":
            return op * (1 + slip) if o["side"] == "BUY" else op * (1 - slip)
        if o["type"] == "LIMIT":
            if o["side"] == "BUY" and lo <= o["limit"]:
                return min(op, o["limit"])
            if o["side"] == "SELL" and hi >= o["limit"]:
                return max(op, o["limit"])
            return None
        if o["type"] == "STOP":
            if o["side"] == "BUY" and hi >= o["stop"]:
                return max(op, o["stop"]) * (1 + slip)
            if o["side"] == "SELL" and lo <= o["stop"]:
                return min(op, o["stop"]) * (1 - slip)
        return None

    def _execute(self, o: dict, price: float, ts: datetime, hub: DataHub, fx: FX) -> None:
        sym = o["symbol"]
        d = hub.daily(sym)
        ccy = d.currency if d is not None and d.currency else ""
        per_eur = fx.per_eur(ccy)
        if not per_eur:
            o["status"] = "abgelehnt"
            o["reason"] = f"Kein Wechselkurs für {ccy} verfügbar"
            self.events.append({"kind": "order_rejected", "order": o})
            return
        unit_eur = fx.to_eur(price, ccy)
        fee = float(self.s.get("depot.fee_fixed", 1.0))
        fee_pct = float(self.s.get("depot.fee_percent", 0.0)) / 100
        fx_fee = float(self.s.get("depot.fx_fee_percent", 0.0)) / 100 if ccy not in ("EUR", "") else 0.0
        qty = o["qty"]
        if not qty and o.get("amount_eur"):
            budget = o["amount_eur"] - fee
            qty = budget / (unit_eur * (1 + fee_pct + fx_fee)) if budget > 0 else 0
            qty = round(qty, 4) if self.s.get("depot.allow_fractional", True) else math.floor(qty)
        if not qty or qty <= 0:
            o["status"] = "abgelehnt"
            o["reason"] = "Betrag reicht nicht für eine Einheit inkl. Gebühren"
            self.events.append({"kind": "order_rejected", "order": o})
            return
        gross = qty * unit_eur
        fees = fee + gross * (fee_pct + fx_fee)
        pos = self.d["positions"].get(sym)
        tx: dict[str, Any] = {"time": iso(ts), "side": o["side"], "symbol": sym, "qty": qty, "price": price, "currency": ccy,
                              "fx_per_eur": per_eur, "gross_eur": gross, "fees_eur": fees, "order_id": o["id"],
                              "strategy": o.get("strategy"), "type": o["type"]}
        if o["side"] == "BUY":
            cost = gross + fees
            if cost > self.d["cash"] + 1e-9:
                o["status"] = "abgelehnt"
                o["reason"] = f"Nicht genug Cash ({_n(self.d['cash'], 2)} € verfügbar, {_n(cost, 2)} € benötigt)"
                self.events.append({"kind": "order_rejected", "order": o})
                return
            self.d["cash"] -= cost
            if pos:
                tot = pos["qty"] + qty
                pos["cost_eur"] += cost
                pos["avg_price_local"] = (pos["avg_price_local"] * pos["qty"] + price * qty) / tot
                pos["qty"] = tot
            else:
                self.d["positions"][sym] = {"qty": qty, "cost_eur": cost, "avg_price_local": price, "currency": ccy,
                                            "opened": iso(ts), "kind": o.get("kind") or "stock", "strategy": o.get("strategy")}
            tx["cash_after"] = self.d["cash"]
        else:
            if not pos or pos["qty"] + 1e-9 < qty:
                held = pos["qty"] if pos else 0
                o["status"] = "abgelehnt"
                o["reason"] = f"Nur {held:g} Stück im Depot"
                self.events.append({"kind": "order_rejected", "order": o})
                return
            basis = pos["cost_eur"] * (qty / pos["qty"])
            proceeds = gross - fees
            realized = proceeds - basis
            tax = self._tax(realized, pos.get("kind") == "etf", ts)
            self.d["cash"] += proceeds - tax
            pos["cost_eur"] -= basis
            pos["qty"] -= qty
            tx.update({"cost_basis_eur": basis, "realized_eur": realized, "tax_eur": tax,
                       "realized_after_tax_eur": realized - tax, "holding_days": _days(pos.get("opened"), ts)})
            if pos["qty"] <= 1e-6:
                del self.d["positions"][sym]
                for other in self.d["orders"]:  # verwaiste Verkaufsorders schließen
                    if other["status"] == "offen" and other["symbol"] == sym and other["side"] == "SELL" and other["id"] != o["id"]:
                        other["status"] = "storniert"
                        other["reason"] = "Position vollständig verkauft"
            tx["cash_after"] = self.d["cash"]
        o["status"] = "ausgeführt"
        o["fill"] = {"time": iso(ts), "price": price, "qty": qty, "fees_eur": fees, "tax_eur": tx.get("tax_eur", 0.0)}
        o["closed_at"] = iso(utcnow())
        self.d["transactions"].append(tx)
        self.events.append({"kind": "order_filled", "order": o, "tx": tx})
        # OCO: Geschwister stornieren
        if o.get("oco"):
            for other in self.d["orders"]:
                if other.get("oco") == o["oco"] and other["id"] != o["id"] and other["status"] == "offen":
                    other["status"] = "storniert"
                    other["reason"] = "OCO: Gegenorder ausgeführt"
        # Bracket: nach Kauf Stop-Loss / Take-Profit anlegen
        if o["side"] == "BUY" and (o.get("sl") or o.get("tp")):
            group = uuid.uuid4().hex[:8]
            for typ, lvl in (("STOP", o.get("sl")), ("LIMIT", o.get("tp"))):
                if lvl:
                    self.d["orders"].append({
                        "id": uuid.uuid4().hex[:10], "created_at": iso(ts), "symbol": sym, "side": "SELL", "type": typ,
                        "qty": qty, "amount_eur": None, "limit": lvl if typ == "LIMIT" else None, "stop": lvl if typ == "STOP" else None,
                        "sl": None, "tp": None, "strategy": o.get("strategy"), "note": "Stop-Loss" if typ == "STOP" else "Take-Profit",
                        "status": "offen", "oco": group, "parent": o["id"],
                        "valid_until": iso(ts + timedelta(days=int(self.s.get("depot.order_validity_days", 90))))})

    def _tax(self, realized: float, is_etf: bool, ts: datetime) -> float:
        cfg = self.s.get("depot.taxes", {}) or {}
        if not cfg.get("enabled", True):
            return 0.0
        t = self.d["tax"]
        if t["year"] != ts.year:
            t.update({"year": ts.year, "allowance_used": 0.0, "paid_year": 0.0})
        g = realized * (1 - float(cfg.get("etf_partial_exemption", 0.3))) if is_etf else realized
        pot_key = "loss_pot_other" if is_etf else "loss_pot_stocks"
        if g < 0:
            t[pot_key] += -g
            return 0.0
        # Verluste verrechnen: Aktienverluste nur mit Aktiengewinnen, allgemeiner Topf mit allem
        for k in ([pot_key] if is_etf else ["loss_pot_stocks", "loss_pot_other"]):
            use = min(g, t[k])
            g -= use
            t[k] -= use
        free = max(0.0, float(cfg.get("allowance", 1000)) - t["allowance_used"])
        use = min(g, free)
        t["allowance_used"] += use
        g -= use
        rate = float(cfg.get("rate", 0.25)) * (1 + float(cfg.get("soli", 0.055)) + float(cfg.get("church", 0.0)))
        tax = max(0.0, g * rate)
        t["paid_total"] += tax
        t["paid_year"] += tax
        return tax

    # ----------------------------------------------------------- Bewertung
    def valuation(self, hub: DataHub, fx: FX, funds: dict[str, dict], names: dict[str, str]) -> dict:
        rows = []
        invested = 0.0
        hub.load_daily(list(self.d["positions"]))
        hub.load_intraday(list(self.d["positions"]))
        for sym, p in self.d["positions"].items():
            q = hub.quote(sym)
            val = fx.to_eur(q.price * p["qty"], p["currency"]) if q.price is not None else None
            day = None
            if q.price is not None and q.prev_close:
                day = fx.to_eur((q.price - q.prev_close) * p["qty"], p["currency"])
            row = {"symbol": sym, "name": names.get(sym) or (funds.get(sym) or {}).get("name") or sym, "qty": p["qty"],
                   "avg_price_local": p["avg_price_local"], "currency": p["currency"], "cost_eur": p["cost_eur"],
                   "avg_cost_eur": p["cost_eur"] / p["qty"] if p["qty"] else None,
                   "quote": q.as_dict(), "value_eur": val,
                   "unrealized_eur": (val - p["cost_eur"]) if val is not None else None,
                   "unrealized_pct": (val / p["cost_eur"] - 1) if val is not None and p["cost_eur"] else None,
                   "day_eur": day, "sector": (funds.get(sym) or {}).get("sector") or ("ETF" if p.get("kind") == "etf" else "unbekannt"),
                   "country": (funds.get(sym) or {}).get("country") or "unbekannt", "kind": p.get("kind", "stock"),
                   "opened": p.get("opened"), "strategy": p.get("strategy")}
            if val is None:
                row["value_eur"] = p["cost_eur"]
                row["value_note"] = "kein aktueller Kurs – zum Einstandswert angesetzt"
            invested += row["value_eur"]
            rows.append(row)
        total = self.d["cash"] + invested
        for r in rows:
            r["weight"] = r["value_eur"] / total if total else 0
        rows.sort(key=lambda r: -r["value_eur"])
        realized = sum(t.get("realized_eur", 0) for t in self.d["transactions"])
        fees = sum(t.get("fees_eur", 0) for t in self.d["transactions"])
        taxes = sum(t.get("tax_eur", 0) for t in self.d["transactions"])
        unreal = sum(r["unrealized_eur"] or 0 for r in rows)
        return {"total_eur": total, "cash_eur": self.d["cash"], "invested_eur": invested, "positions": rows,
                "start_capital": self.d["start_capital"], "pnl_eur": total - self.d["start_capital"],
                "pnl_pct": total / self.d["start_capital"] - 1, "realized_eur": realized, "unrealized_eur": unreal,
                "fees_eur": fees, "taxes_eur": taxes, "day_eur": sum(r["day_eur"] or 0 for r in rows),
                "tax_state": self.d["tax"]}

    def snapshot(self, val: dict) -> None:
        now = iso(utcnow())
        eq = self.d["equity"]
        point = {"time": now, "value": val["total_eur"], "cash": val["cash_eur"], "invested": val["invested_eur"]}
        # pro Kalendertag höchstens den letzten Stand + bis zu 24 Intraday-Punkte für heute behalten
        eq.append(point)
        today = now[:10]
        older = [p for p in eq if p["time"][:10] != today]
        by_day: dict[str, dict] = {}
        for p in older:
            by_day[p["time"][:10]] = p
        self.d["equity"] = list(by_day.values()) + [p for p in eq if p["time"][:10] == today][-24:]

    def save(self) -> None:
        self.d["orders"] = [o for o in self.d["orders"] if o["status"] == "offen"] + \
                           [o for o in self.d["orders"] if o["status"] != "offen"][-400:]
        self.store.save("depot", self.d)


def _f(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def _days(a: str | None, b: datetime) -> int | None:
    pa = parse_iso(a) if a else None
    return (b - pa).days if pa else None
