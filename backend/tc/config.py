"""Konfiguration, Pfade und JSON-Zustandsspeicher."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(os.environ.get("TC_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"
STATE_DIR = Path(os.environ.get("TC_STATE_DIR", ROOT / "state"))
SITE_DIR = Path(os.environ.get("TC_SITE_DIR", ROOT / "site"))
DATA_OUT = SITE_DIR / "data"
CACHE_DIR = STATE_DIR / "cache"


def load_yaml(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Settings:
    def __init__(self) -> None:
        self.raw = load_yaml("settings.yaml")
        self.universe = load_yaml("universe.yaml")
        self.events = load_yaml("events.yaml").get("events", []) or []
        self.tz = ZoneInfo(self.raw.get("timezone", "Europe/Berlin"))

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # Universum
    @property
    def stocks(self) -> list[str]:
        return list(dict.fromkeys(self.universe.get("stocks", []) or []))

    @property
    def etfs(self) -> list[dict]:
        return self.universe.get("etfs", []) or []

    @property
    def etf_symbols(self) -> list[str]:
        return [e["symbol"] for e in self.etfs]


def env(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def utcnow() -> datetime:
    override = os.environ.get("TC_NOW")  # nur für Tests
    if override:
        return datetime.fromisoformat(override).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class JsonStore:
    """Dauerhafter Zustand als JSON-Dateien (wird von GitHub Actions ins Repo committet)."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = base or STATE_DIR
        self.base.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.base / f"{name}.json"

    def load(self, name: str, default: Any) -> Any:
        p = self.path(name)
        if not p.exists():
            return default
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def save(self, name: str, data: Any) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=_json_default)
        tmp.replace(p)


def _json_default(o: Any) -> Any:
    import numpy as np
    import pandas as pd

    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if f != f else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (datetime, pd.Timestamp)):
        return iso(o.to_pydatetime() if isinstance(o, pd.Timestamp) else o)
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not serializable: {type(o)}")


def write_site_json(name: str, data: Any) -> None:
    p = DATA_OUT / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(clean_nan(data), f, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def clean_nan(o: Any) -> Any:
    """NaN/Inf → None, damit das Frontend gültiges JSON bekommt."""
    if isinstance(o, float):
        return None if (o != o or o in (float("inf"), float("-inf"))) else o
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    try:
        import numpy as np

        if isinstance(o, np.floating):
            return clean_nan(float(o))
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.bool_):
            return bool(o)
    except ImportError:
        pass
    return o
