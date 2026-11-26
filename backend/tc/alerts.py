"""Benachrichtigungssystem: erzeugt, entdoppelt, speichert und versendet Meldungen.

Jede Meldung sagt ausdrücklich, ob es eine reine Information oder ein Modellsignal ist.
Es gibt keine automatischen Transaktionen – auch nicht im Planspiel.
"""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from typing import Any

import requests

from .config import JsonStore, Settings, env, iso, parse_iso, utcnow

log = logging.getLogger(__name__)
PRIO = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def make_alert(kind: str, priority: str, symbol: str | None, name: str | None, headline: str, reason: str,
               risk: str, todo: str, quote: dict | None, source: str, info_time: str | None, tag: str,
               dedupe: str, signal_label: str | None = None, is_signal: bool = False, link: str | None = None) -> dict:
    title = f"{'AKTIENALARM' if symbol and not symbol.startswith(('MARKT', 'DEPOT')) else 'HINWEIS'} – {name or symbol or 'Markt'}"
    return {"id": f"{dedupe}|{iso(utcnow())}", "dedupe": dedupe, "kind": kind, "priority": priority, "symbol": symbol,
            "name": name, "title": title, "headline": headline, "signal_label": signal_label,
            "type_label": "MODELLSIGNAL – analytische Orientierung, keine Anlageberatung" if is_signal else "BENACHRICHTIGUNG – keine Kaufempfehlung",
            "is_signal": is_signal, "quote": quote, "reason": reason, "risk": risk, "todo": todo,
            "source": source, "info_time": info_time, "created": iso(utcnow()), "tag": tag, "link": link, "delivered": []}


class AlertCenter:
    def __init__(self, store: JsonStore, s: Settings) -> None:
        self.store = store
        self.s = s
        self.log: list[dict] = store.load("alerts", [])
        self.new: list[dict] = []

    def add(self, a: dict) -> bool:
        hours = float(self.s.get("alerts.dedupe_hours", 20))
        cutoff = utcnow() - timedelta(hours=hours)
        for old in reversed(self.log[-800:]):
            if old["dedupe"] == a["dedupe"] and parse_iso(old["created"]) >= cutoff:
                return False
        if any(n["dedupe"] == a["dedupe"] for n in self.new):
            return False
        self.new.append(a)
        return True

    def dispatch(self, send: bool = True) -> dict[str, Any]:
        channels = self.s.get("alerts.channels", ["dashboard"]) or ["dashboard"]
        if not send:
            channels = ["dashboard"]
        minp = PRIO.get(self.s.get("alerts.min_priority_to_send", "MEDIUM"), 1)
        to_send = sorted([a for a in self.new if PRIO[a["priority"]] >= minp], key=lambda a: -PRIO[a["priority"]])
        status: dict[str, Any] = {}
        senders = {"telegram": Telegram(), "push": Ntfy(), "email": Email()}
        for ch in channels:
            if ch == "dashboard":
                continue
            snd = senders.get(ch)
            if not snd or not snd.enabled:
                status[ch] = "nicht konfiguriert"
                continue
            if not to_send:
                status[ch] = "nichts zu senden"
                continue
            try:
                individual = to_send[:8]
                for a in individual:
                    snd.send(a)
                    a["delivered"].append(ch)
                if len(to_send) > 8:
                    snd.send_digest(to_send[8:])
                    for a in to_send[8:]:
                        a["delivered"].append(f"{ch} (Sammelmeldung)")
                status[ch] = f"{len(to_send)} gesendet"
            except Exception as e:  # noqa: BLE001
                log.warning("Versand %s fehlgeschlagen: %s", ch, e)
                status[ch] = f"Fehler: {str(e)[:120]}"
        for a in self.new:
            a["delivered"].append("dashboard")
        self.log.extend(self.new)
        return status

    def save(self) -> None:
        self.store.save("alerts", self.log[-1500:])


# ------------------------------------------------------------------ Format
def fmt_price(q: dict | None) -> str:
    if not q or q.get("price") is None:
        return "nicht verfügbar"
    p = f"{q['price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    t = q.get("time") or "?"
    return f"{p} {q.get('currency') or ''} ({q.get('quality')}, {t[:16].replace('T', ' ')} UTC, {q.get('source')})"


def to_text(a: dict) -> str:
    lines = [f"[{a['priority']}] {a['title']}", a["type_label"]]
    if a.get("signal_label"):
        lines.append(f"Signal: {a['signal_label']}")
    lines += [f"Ereignis: {a['headline']}", f"Aktueller Kurs: {fmt_price(a.get('quote'))}", "",
              f"Grund: {a['reason']}", f"Risiko: {a['risk']}", f"Was ist zu tun? {a['todo']}", "",
              f"Quelle: {a['source']} · Stand der Information: {(a.get('info_time') or '?')[:16].replace('T', ' ')} UTC",
              f"Einordnung: {a['tag']}"]
    return "\n".join(lines)


def to_html(a: dict) -> str:
    e = html.escape
    parts = [f"<b>[{e(a['priority'])}] {e(a['title'])}</b>", f"<i>{e(a['type_label'])}</i>"]
    if a.get("signal_label"):
        parts.append(f"<b>Signal:</b> {e(a['signal_label'])}")
    parts += [f"<b>Ereignis:</b> {e(a['headline'])}", f"<b>Aktueller Kurs:</b> {e(fmt_price(a.get('quote')))}",
              f"<b>Grund:</b> {e(a['reason'])}", f"<b>Risiko:</b> {e(a['risk'])}", f"<b>Was ist zu tun?</b> {e(a['todo'])}",
              f"<i>Quelle: {e(a['source'])} · {e((a.get('info_time') or '?')[:16].replace('T', ' '))} UTC · {e(a['tag'])}</i>"]
    if a.get("link"):
        parts.append(f'<a href="{e(a["link"])}">Originalquelle</a>')
    site = env("SITE_URL")
    if site:
        parts.append(f'<a href="{e(site)}#/alerts">Im Trading Center öffnen</a>')
    return "\n".join(parts)


# ------------------------------------------------------------------ Kanäle
class Telegram:
    def __init__(self) -> None:
        self.token, self.chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat)

    def _post(self, text: str) -> None:
        r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          json={"chat_id": self.chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status()

    def send(self, a: dict) -> None:
        self._post(to_html(a))

    def send_digest(self, alerts: list[dict]) -> None:
        self._post("<b>Weitere Meldungen</b>\n" + "\n".join(f"[{a['priority']}] {html.escape(a['title'])}: {html.escape(a['headline'])}" for a in alerts))

    def send_text(self, text_html: str) -> None:
        self._post(text_html)


class Ntfy:
    def __init__(self) -> None:
        self.topic = env("NTFY_TOPIC")
        self.server = env("NTFY_SERVER") or "https://ntfy.sh"

    @property
    def enabled(self) -> bool:
        return bool(self.topic)

    def _post(self, title: str, body: str, prio: str, click: str | None = None) -> None:
        headers = {"Title": title.encode("utf-8"), "Priority": {"HIGH": "5", "MEDIUM": "4"}.get(prio, "3"), "Tags": "chart_with_upwards_trend"}
        if click:
            headers["Click"] = click
        r = requests.post(f"{self.server}/{self.topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
        r.raise_for_status()

    def send(self, a: dict) -> None:
        site = env("SITE_URL")
        self._post(f"[{a['priority']}] {a['title']}", to_text(a), a["priority"], f"{site}#/alerts" if site else None)

    def send_digest(self, alerts: list[dict]) -> None:
        self._post(f"{len(alerts)} weitere Meldungen", "\n".join(f"[{a['priority']}] {a['title']}: {a['headline']}" for a in alerts), "MEDIUM")

    def send_text(self, title: str, body: str) -> None:
        self._post(title, body, "LOW")


class Email:
    def __init__(self) -> None:
        self.host, self.user, self.pw = env("SMTP_HOST"), env("SMTP_USER"), env("SMTP_PASSWORD")
        self.port = int(env("SMTP_PORT") or 587)
        self.to = env("ALERT_EMAIL_TO")

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self.pw and self.to)

    def _send(self, subject: str, body: str) -> None:
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = subject, self.user, self.to
        m.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(self.user, self.pw)
            s.send_message(m)

    def send(self, a: dict) -> None:
        self._send(f"[{a['priority']}] {a['title']}", to_text(a))

    def send_digest(self, alerts: list[dict]) -> None:
        self._send(f"Trading Center: {len(alerts)} weitere Meldungen", "\n\n".join(to_text(a) for a in alerts))

    def send_text(self, subject: str, body: str) -> None:
        self._send(subject, body)
