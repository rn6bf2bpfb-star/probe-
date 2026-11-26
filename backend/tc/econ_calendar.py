"""Wirtschaftskalender: feste Termine (mit Quelle), FRED-Veröffentlichungen, Quartalszahlen und Dividenden."""
from __future__ import annotations

from datetime import date, timedelta

from .config import Settings, utcnow

WHY = {
    "fed": "Der US-Leitzins bestimmt Finanzierungskosten und die Bewertung von Aktien weltweit; Überraschungen bewegen Anleihen, Dollar und Wachstumswerte besonders stark.",
    "ecb": "Der EZB-Zins beeinflusst Kreditkosten, den Euro und damit europäische Banken, Immobilienwerte und Exporteure.",
    "inflation": "Inflationsdaten verändern die Zinserwartungen. Höher als erwartet belastet meist Anleihen und hoch bewertete Aktien.",
    "labor": "Der Arbeitsmarkt zeigt die Stärke der Konjunktur und beeinflusst die Zinspolitik der Fed.",
    "gdp": "Das BIP misst die Wirtschaftsleistung; schwache Werte schüren Rezessionssorgen, starke können Zinssenkungen verzögern.",
    "earnings": "Quartalszahlen und Ausblick bewegen die Aktie oft stark (Kurslücken). Vorher Positionsgröße und Stop prüfen.",
    "dividend": "Am Ex-Tag wird die Aktie um etwa die Dividende niedriger gehandelt – das ist kein Verlust, sondern eine Auszahlung.",
    "agm": "Auf der Hauptversammlung werden Dividende und wichtige Beschlüsse abgestimmt; Ausblicke des Vorstands können Kurse bewegen.",
    "other": "Kann je nach Ausgang Marktbewegungen auslösen.",
}
CAT_DE = {"fed": "Fed", "ecb": "EZB", "inflation": "Inflation", "labor": "Arbeitsmarkt", "gdp": "BIP",
          "earnings": "Quartalszahlen", "dividend": "Dividende", "agm": "Hauptversammlung", "other": "Sonstiges"}


def build_calendar(s: Settings, release_dates: list[dict], company_events: dict[str, dict], names: dict[str, str],
                   holdings: set[str], watch: set[str], days: int = 45) -> dict:
    today = utcnow().astimezone(s.tz).date()
    end = today + timedelta(days=days)
    out: list[dict] = []

    def add(d: date, title: str, cat: str, source: str, symbol: str | None = None, confirmed: bool = True):
        if today - timedelta(days=1) <= d <= end:
            out.append({"date": d.isoformat(), "title": title, "category": cat, "category_de": CAT_DE.get(cat, cat),
                        "why": WHY.get(cat, WHY["other"]), "source": source, "symbol": symbol,
                        "in_depot": symbol in holdings if symbol else False, "on_watchlist": symbol in watch if symbol else False,
                        "confirmed": confirmed})

    for e in s.events:
        try:
            d = e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"]))
        except (KeyError, ValueError):
            continue
        add(d, e.get("title", "Termin"), e.get("category", "other"), e.get("source", "config/events.yaml"),
            e.get("symbol"))
    for r in release_dates:
        try:
            add(date.fromisoformat(r["date"]), r["title"], r["category"], r["source"])
        except (KeyError, ValueError):
            continue
    for sym, ev in company_events.items():
        cal = (ev or {}).get("calendar") or {}
        nm = names.get(sym, sym)
        if cal.get("earnings_date"):
            try:
                add(date.fromisoformat(cal["earnings_date"][:10]), f"Quartalszahlen {nm}", "earnings",
                    "Yahoo Finance (Termin laut Unternehmenskalender, kann sich verschieben)", sym, confirmed=False)
            except ValueError:
                pass
        if cal.get("ex_dividend_date"):
            try:
                add(date.fromisoformat(cal["ex_dividend_date"][:10]), f"Ex-Dividenden-Tag {nm}", "dividend", "Yahoo Finance", sym)
            except ValueError:
                pass
    out.sort(key=lambda x: (x["date"], x["category"]))
    gaps = []
    if not release_dates:
        gaps.append("US-Konjunkturtermine (CPI, Arbeitsmarkt, BIP) benötigen FRED_API_KEY.")
    gaps.append("Euroraum-Konjunkturtermine und Hauptversammlungen gibt es nicht als freie API – eigene Termine in config/events.yaml eintragen.")
    return {"events": out, "from": today.isoformat(), "to": end.isoformat(), "gaps": gaps}
