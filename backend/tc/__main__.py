"""Kommandozeile.

  python -m tc run                     # normaler Lauf (Bericht automatisch nach Uhrzeit)
  python -m tc run --report morning    # Bericht erzwingen: morning|intraday|evening|none
  python -m tc demo                    # DEMO mit synthetischen Daten (deutlich gekennzeichnet, kein Versand)
  python -m tc enqueue --json '{...}'  # Befehl in den Eingangskorb legen (nutzt GitHub Actions)
  python -m tc status                  # Kanäle, Schlüssel und letzter Lauf
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import os
import uuid
from datetime import datetime, timezone


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tc")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--report", default="auto", choices=["auto", "morning", "intraday", "evening", "none"])
    r.add_argument("--no-send", action="store_true")
    r.add_argument("--command-json", default=None, help="einzelner Befehl als JSON (z. B. Order)")
    d = sub.add_parser("demo")
    d.add_argument("--report", default="evening")
    e = sub.add_parser("enqueue")
    e.add_argument("--json", required=True)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    if a.cmd == "demo":
        # Demo nutzt einen eigenen Zustand, damit das echte Planspiel-Depot unberührt bleibt
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        os.environ.setdefault("TC_STATE_DIR", str(root / "demo_state"))
    from .config import STATE_DIR, JsonStore, env

    if a.cmd == "enqueue":
        cmd = json.loads(a.json)
        if not cmd.get("type"):
            print("Befehl ohne 'type'", file=sys.stderr)
            return 2
        cmd.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        p = STATE_DIR / "inbox" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cmd, ensure_ascii=False), encoding="utf-8")
        print(f"Befehl abgelegt: {p.name}")
        return 0

    if a.cmd == "status":
        st = JsonStore()
        meta = st.load("meta", {})
        keys = ["FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "NTFY_TOPIC", "SMTP_HOST", "SITE_URL"]
        print("Letzter Lauf:", meta.get("last_run", "noch keiner"))
        for k in keys:
            print(f"  {k:20s} {'gesetzt' if env(k) else '–'}")
        return 0

    from .pipeline import Run
    if a.cmd == "demo":
        res = Run(demo=True, report=a.report, send=False).execute()
    else:
        extra = [json.loads(a.command_json)] if a.command_json else []
        res = Run(demo=False, report=a.report, send=not a.no_send).execute(extra)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
