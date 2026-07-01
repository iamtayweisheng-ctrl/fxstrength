#!/usr/bin/env python3
"""
FXStrength — matrix builder.

Fetches FX (and gold/silver) closes from Yahoo, computes each currency's
relative strength across three timeframes, and writes a single static
`public/data/matrix.json` that the front-end loads from a CDN.

The fiat maths mirror the FXFlow app verbatim (fx-scanner-v2.html
`computeStrength`) so the numbers here match the desktop tool:
each currency's strength = average % move vs the other seven, across all
28 crosses, measured from the start of the window.

Gold (XAU) and silver (XAG) are added as bonus "currencies": their strength
is their move vs the 8-fiat basket, derived from each fiat's USD value.

No third-party packages — standard library only, so it runs anywhere
(locally and on GitHub Actions) with zero install.
"""

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── universe ──────────────────────────────────────────────────────────
CCYS = ["USD", "EUR", "JPY", "GBP", "AUD", "CHF", "CAD", "NZD"]
MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]
MINORS = ["EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
          "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
          "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
          "CADJPY", "CHFJPY", "NZDJPY", "NZDCHF", "NZDCAD", "CADCHF"]
ALL_PAIRS = MAJORS + MINORS          # 28 crosses
# code -> Yahoo symbol. Gold/silver via the front-month futures (spot XAUUSD=X
# 404s on Yahoo); we only use their % change, so contract rolls are immaterial.
COMMODITIES = {"XAU": "GC=F", "XAG": "SI=F"}

# Each fiat's price expressed in USD, and whether the raw USD pair is inverted.
# usdVal(F) = +ret(F+USD) if F is the base of its USD pair, else -ret(USD+F).
USD_PAIR = {"USD": None,
            "EUR": ("EURUSD", +1), "GBP": ("GBPUSD", +1),
            "AUD": ("AUDUSD", +1), "NZD": ("NZDUSD", +1),
            "JPY": ("USDJPY", -1), "CHF": ("USDCHF", -1), "CAD": ("USDCAD", -1)}

# range / interval / window, matching FXFlow's CS_CFG.
MODES = {
    "intraday": {"range": "5d",  "interval": "60m", "win": 48,
                 "label": "Intraday · last ~48h (hourly)"},
    "daily":    {"range": "3mo", "interval": "1d",  "win": 30,
                 "label": "Daily · last 30 days"},
    "weekly":   {"range": "1y",  "interval": "1wk", "win": 26,
                 "label": "Weekly · last 26 weeks"},
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch_series(sym, rng, interval, retries=3):
    """Return {date_iso: close} for a full Yahoo symbol, or None."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?range={rng}&interval={interval}")
    intraday = "m" in interval or "h" in interval
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.load(r)
            res = (j.get("chart", {}).get("result") or [None])[0]
            if not res:
                return None
            ts = res.get("timestamp") or []
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            out = {}
            for t, c in zip(ts, closes):
                if c is None:
                    continue
                iso = datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
                key = iso[:16] if intraday else iso[:10]
                out[key] = c
            return out or None
        except Exception as e:                       # noqa: BLE001
            if attempt == retries - 1:
                print(f"  ! {sym} {interval} failed: {e}")
                return None
            time.sleep(1.5 * (attempt + 1))
    return None


def align(maps):
    """Union the date axes across pairs and forward-fill each onto it."""
    axis = sorted({d for m in maps.values() for d in m})
    filled = {}
    for pair, m in maps.items():
        last, col = None, []
        for d in axis:
            if d in m:
                last = m[d]
            col.append(last)
        filled[pair] = col
    return axis, filled


def pct_from_start(arr, start):
    """% change of each point vs the window-start price."""
    base = arr[start]
    if not base:
        return [0.0] * (len(arr) - start)
    return [(arr[start + k] / base - 1) * 100 for k in range(len(arr) - start)]


def compute_mode(mode):
    cfg = MODES[mode]
    rng, interval, win = cfg["range"], cfg["interval"], cfg["win"]
    # (key used in maths, full Yahoo symbol). Fiat crosses get the "=X" suffix;
    # commodities are already full symbols (GC=F / SI=F).
    symbols = [(p, f"{p}=X") for p in ALL_PAIRS] + \
              [(sym, sym) for sym in COMMODITIES.values()]

    maps = {}
    for key, sym in symbols:
        s = fetch_series(sym, rng, interval)
        if s:
            maps[key] = s
        time.sleep(0.15)                              # be gentle with Yahoo
    have = [p for p in ALL_PAIRS if p in maps]
    if len(have) < 10:
        print(f"  ! {mode}: only {len(have)} fiat pairs - skipping")
        return None

    axis, filled = align(maps)
    start = max(0, len(axis) - win)
    ret = {p: pct_from_start(filled[p], start) for p in filled}
    n = len(axis) - start

    # ── fiat strength (exact FXFlow method: avg vs the other seven) ──
    series = {}
    for C in CCYS:
        col = []
        for k in range(n):
            tot, cnt = 0.0, 0
            for X in CCYS:
                if X == C:
                    continue
                if C + X in ret:
                    r = ret[C + X][k]
                elif X + C in ret:
                    r = -ret[X + C][k]
                else:
                    continue
                tot += r
                cnt += 1
            col.append(tot / cnt if cnt else 0.0)
        series[C] = col

    # ── each fiat's value in USD, for the gold/silver basket ──
    usdval = {"USD": [0.0] * n}
    for F, spec in USD_PAIR.items():
        if spec is None:
            continue
        pr, sign = spec
        usdval[F] = [sign * v for v in ret[pr]] if pr in ret else [0.0] * n
    basket = [sum(usdval[F][k] for F in CCYS) / len(CCYS) for k in range(n)]

    # ── gold / silver strength = move vs the 8-fiat basket ──
    for code, pair in COMMODITIES.items():
        if pair in ret:
            series[code] = [ret[pair][k] - basket[k] for k in range(n)]

    return {"label": cfg["label"], "win": win, "n": n, "series": series,
            "asof": axis[-1] if axis else None}


def arrow(col):
    """Short-term slope over the last few points → up / down / flat."""
    if len(col) < 2:
        return "flat"
    k = min(3, len(col) - 1)
    slope = col[-1] - col[-1 - k]
    if slope > 0.03:
        return "up"
    if slope < -0.03:
        return "down"
    return "flat"


def to_scores(series):
    """Latest strength per currency + a symmetric 0–10 display score.

    The scale is driven by the eight fiats (the core grid), so the most-
    extended fiat pegs at 0/10 and the rest spread out meaningfully. Gold and
    silver ride the same axis and simply clamp at the extremes when they run
    far beyond the currency range.
    """
    latest = {c: col[-1] for c, col in series.items() if col}
    scale = max(1e-9, max(abs(latest[c]) for c in CCYS if c in latest))
    out = {}
    for c, col in series.items():
        if not col:
            continue
        pct = col[-1]
        score = max(0.0, min(10.0, 5 + 5 * pct / scale))
        out[c] = {"pct": round(pct, 3),
                  "score": round(score, 2),
                  "arrow": arrow(col)}
    ranked = sorted(out, key=lambda c: out[c]["pct"], reverse=True)
    for rank, c in enumerate(ranked, 1):
        out[c]["rank"] = rank
    return out


def market_open(now):
    """FX cash market: ~Sun 21:00 UTC → Fri 21:00 UTC."""
    wd, hr = now.weekday(), now.hour            # Mon=0 … Sun=6
    if wd == 5:                                 # Saturday
        return False
    if wd == 6 and hr < 21:                     # Sunday before open
        return False
    if wd == 4 and hr >= 21:                    # Friday after close
        return False
    return True


def main():
    now = datetime.now(timezone.utc)
    timeframes = {}
    for mode in MODES:
        print(f"- {mode} ...")
        r = compute_mode(mode)
        if not r:
            continue
        timeframes[mode] = {"label": r["label"], "window": r["win"],
                            "asof": r["asof"], "scores": to_scores(r["series"])}

    matrix = {
        "generated_at": now.isoformat(timespec="seconds"),
        "market_open": market_open(now),
        "currencies": CCYS + list(COMMODITIES),
        "timeframe_order": list(MODES),
        "timeframes": timeframes,
        "source": "Yahoo Finance",
    }

    out = Path(__file__).resolve().parent.parent / "public" / "data" / "matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(f"OK wrote {out}  ({len(timeframes)} timeframes)")


if __name__ == "__main__":
    main()
