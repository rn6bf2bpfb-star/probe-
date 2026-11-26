"""Optionaler KI-Kommentar über die Anthropic-API. Wird nur mit ANTHROPIC_API_KEY genutzt.

Das Modell bekommt ausschließlich die vom System berechneten Daten und darf nichts ergänzen.
Ohne Schlüssel entstehen alle Texte regelbasiert – die Plattform funktioniert vollständig ohne KI-Schlüssel.
"""
from __future__ import annotations

import json
import logging

import requests

from .config import Settings, env

log = logging.getLogger(__name__)

SYSTEM = (
    "Du bist ein nüchterner Börsenanalyst und schreibst auf Deutsch für einen Privatanleger, der ein Börsen-Planspiel "
    "mit virtuellem Geld spielt. Verwende AUSSCHLIESSLICH die Fakten aus den gelieferten JSON-Daten. Erfinde keine "
    "Kurse, Kennzahlen, Nachrichten, Termine oder Ursachen. Wenn eine Ursache aus den Daten nicht hervorgeht, sage das. "
    "Trenne klar zwischen Fakten ('Fakt:') und Einschätzungen ('Einschätzung:'). Keine Kaufaufforderungen, keine Garantien. "
    "Schreibe kompakt, ohne Markdown-Überschriften."
)


def enabled(s: Settings) -> bool:
    mode = s.get("reports.llm.enabled", "auto")
    if mode is False or str(mode).lower() in ("false", "off", "no"):
        return False
    return bool(env("ANTHROPIC_API_KEY"))


def comment(s: Settings, task: str, data: dict, max_tokens: int | None = None) -> str | None:
    if not enabled(s):
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": s.get("reports.llm.model", "claude-sonnet-5-5"),
                  "max_tokens": int(max_tokens or s.get("reports.llm.max_tokens", 900)),
                  "system": SYSTEM,
                  "messages": [{"role": "user", "content": f"{task}\n\nDATEN (JSON):\n{json.dumps(data, ensure_ascii=False, default=str)[:60000]}"}]},
            timeout=90)
        r.raise_for_status()
        parts = r.json().get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
        return text or None
    except Exception as e:  # noqa: BLE001
        log.warning("KI-Kommentar fehlgeschlagen: %s", e)
        return None
