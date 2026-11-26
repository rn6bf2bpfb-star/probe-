"""Technische Indikatoren – kausal berechnet (nur Daten bis zum jeweiligen Zeitpunkt)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    m = ema(close, fast) - ema(close, slow)
    sig = m.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": m, "signal": sig, "hist": m - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["High"].diff()
    dn = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = atr(df, n)
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rvol(volume: pd.Series, n: int = 20) -> pd.Series:
    base = volume.shift(1).rolling(n, min_periods=n).mean()
    return volume / base.replace(0, np.nan)


def support_resistance(df: pd.DataFrame, lookback: int = 180, window: int = 5, tol: float = 0.015) -> dict:
    """Zonen aus lokalen Hoch-/Tiefpunkten, zusammengefasst wenn näher als tol."""
    d = df.tail(lookback)
    if len(d) < window * 2 + 1:
        return {"supports": [], "resistances": []}
    hi, lo = d["High"].values, d["Low"].values
    pivots = []
    for i in range(window, len(d) - window):
        if hi[i] == hi[i - window:i + window + 1].max():
            pivots.append(hi[i])
        if lo[i] == lo[i - window:i + window + 1].min():
            pivots.append(lo[i])
    pivots.sort()
    zones: list[list[float]] = []
    for p in pivots:
        if zones and abs(p / np.mean(zones[-1]) - 1) < tol:
            zones[-1].append(p)
        else:
            zones.append([p])
    last = float(d["Close"].iloc[-1])
    lv = [(float(np.mean(z)), len(z)) for z in zones]
    sup = sorted([{"level": round(l, 4), "touches": t} for l, t in lv if l < last], key=lambda x: -x["level"])[:3]
    res = sorted([{"level": round(l, 4), "touches": t} for l, t in lv if l > last], key=lambda x: x["level"])[:3]
    return {"supports": sup, "resistances": res}


def trend_channel(close: pd.Series, n: int = 60) -> dict | None:
    c = close.dropna().tail(n)
    if len(c) < n // 2:
        return None
    x = np.arange(len(c))
    y = np.log(c.values)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    sd = resid.std()
    mid = float(np.exp(slope * x[-1] + intercept))
    r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum() if len(c) > 2 else 0
    return {"slope_pct_per_day": float(slope * 100), "upper": mid * float(np.exp(2 * sd)),
            "mid": mid, "lower": mid * float(np.exp(-2 * sd)), "r2": float(r2), "days": int(len(c))}


def realized_vol(close: pd.Series, n: int = 60) -> float | None:
    r = np.log(close).diff().dropna().tail(n)
    return float(r.std() * np.sqrt(252)) if len(r) >= 20 else None


def perf(close: pd.Series, bars: int) -> float | None:
    c = close.dropna()
    if len(c) <= bars:
        return None
    return float(c.iloc[-1] / c.iloc[-1 - bars] - 1)


def compute_all(df: pd.DataFrame, bench: pd.Series | None = None) -> dict:
    """Alle Kennzahlen für den letzten Balken."""
    c = df["Close"]
    out: dict = {"bars": int(len(df))}
    if len(df) < 30:
        return out
    last = float(c.iloc[-1])
    for n in (20, 50, 100, 200):
        v = sma(c, n).iloc[-1]
        out[f"sma{n}"] = None if pd.isna(v) else float(v)
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    out["sma50_slope"] = float(s50.iloc[-1] / s50.iloc[-11] - 1) if len(s50.dropna()) > 11 else None
    out["sma200_slope"] = float(s200.iloc[-1] / s200.iloc[-21] - 1) if len(s200.dropna()) > 21 else None
    cross = None
    if len(s200.dropna()) > 21:
        diff = (s50 - s200).dropna().tail(21)
        if (diff.iloc[0] < 0) and (diff.iloc[-1] > 0):
            cross = "golden_cross"
        elif (diff.iloc[0] > 0) and (diff.iloc[-1] < 0):
            cross = "death_cross"
    out["cross_20d"] = cross
    r = rsi(c)
    out["rsi"] = None if pd.isna(r.iloc[-1]) else float(r.iloc[-1])
    m = macd(c)
    out["macd"] = float(m["macd"].iloc[-1]) if not pd.isna(m["macd"].iloc[-1]) else None
    out["macd_signal"] = float(m["signal"].iloc[-1]) if not pd.isna(m["signal"].iloc[-1]) else None
    out["macd_hist"] = float(m["hist"].iloc[-1]) if not pd.isna(m["hist"].iloc[-1]) else None
    h = m["hist"].dropna()
    out["macd_cross"] = None
    if len(h) > 3:
        if h.iloc[-1] > 0 >= h.iloc[-4:-1].min():
            out["macd_cross"] = "bullish"
        elif h.iloc[-1] < 0 <= h.iloc[-4:-1].max():
            out["macd_cross"] = "bearish"
    b = bollinger(c)
    if not pd.isna(b["upper"].iloc[-1]):
        width = b["upper"].iloc[-1] - b["lower"].iloc[-1]
        out["boll_pos"] = float((last - b["lower"].iloc[-1]) / width) if width else None
        out["boll_upper"], out["boll_lower"] = float(b["upper"].iloc[-1]), float(b["lower"].iloc[-1])
    a = atr(df)
    out["atr"] = None if pd.isna(a.iloc[-1]) else float(a.iloc[-1])
    out["atr_pct"] = out["atr"] / last if out["atr"] else None
    ad = adx(df)
    out["adx"] = None if pd.isna(ad.iloc[-1]) else float(ad.iloc[-1])
    rv = rvol(df["Volume"])
    out["rvol"] = None if pd.isna(rv.iloc[-1]) else float(rv.iloc[-1])
    out["avg_volume_20"] = float(df["Volume"].tail(20).mean()) if df["Volume"].notna().any() else None
    out["volume"] = float(df["Volume"].iloc[-1]) if not pd.isna(df["Volume"].iloc[-1]) else None
    out.update({f"perf_{k}": perf(c, b_) for k, b_ in (("1d", 1), ("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))})
    out["vol_60"] = realized_vol(c, 60)
    hi52 = df["High"].tail(252).max()
    lo52 = df["Low"].tail(252).min()
    out["high_52w"], out["low_52w"] = float(hi52), float(lo52)
    out["dist_52w_high"] = float(last / hi52 - 1)
    out["sr"] = support_resistance(df)
    out["channel"] = trend_channel(c)
    if bench is not None and len(bench.dropna()) > 130:
        bj = bench.reindex(c.index, method="ffill")
        p_s, p_b = perf(c, 126), perf(bj, 126)
        out["rel_strength_6m"] = (p_s - p_b) if p_s is not None and p_b is not None else None
        p_s, p_b = perf(c, 21), perf(bj, 21)
        out["rel_strength_1m"] = (p_s - p_b) if p_s is not None and p_b is not None else None
    # Trendzustand
    out["trend"] = classify_trend(last, out.get("sma50"), out.get("sma200"), out.get("sma50_slope"))
    return out


def classify_trend(last: float, s50: float | None, s200: float | None, slope50: float | None) -> str:
    if s50 is None:
        return "unbestimmt"
    if s200 is None:
        return "aufwärts" if last > s50 and (slope50 or 0) > 0 else "abwärts" if last < s50 and (slope50 or 0) < 0 else "seitwärts"
    if last > s50 > s200 and (slope50 or 0) > 0:
        return "aufwärts"
    if last < s50 < s200 and (slope50 or 0) < 0:
        return "abwärts"
    return "seitwärts"
