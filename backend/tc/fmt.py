"""Deutsche Zahlenformate für alle erzeugten Texte."""
from __future__ import annotations


def _de(s: str) -> str:
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


def n(v: float | None, d: int = 2, signed: bool = False) -> str:
    if v is None:
        return "n. v."
    return _de(f"{v:{'+' if signed else ''},.{d}f}")


def pc(v: float | None, d: int = 1, signed: bool = False) -> str:
    if v is None:
        return "n. v."
    return _de(f"{v * 100:{'+' if signed else ''},.{d}f}") + " %"
