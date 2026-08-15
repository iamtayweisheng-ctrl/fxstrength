"""
Driver Meter v3 — ALIGNED to the strength meter.  (Brain's authoritative generator.)
Windows match the strength meter exactly: daily = ~30 calendar days, weekly = ~26 weeks.
Drivers computed over those windows using DAILY data (VIX, US 2Y/10Y, WTI from FRED),
so the meter moves at the strength meter's speed and EXPLAINS its scores.
Weights are the FRED-calibrated (fixed) values. Evidence, not a signal.

FXS note: identical to G10/build_driver_data_v3.py except the output path — this
writes public/driver-data.json (relative to the repo) so the CI + Cloudflare serve it.
Requires pandas + numpy (the CI installs them).
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
import numpy as np
import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "driver-data.json")

START = "2015-01-01"
# Strength-meter-matched windows, in TRADING days (~21/day-month, ~130/26-weeks).
WIN = {"daily": 21, "weekly": 130}
Z_FLAT = 0.5
Z_TRAIL = 252

CURRENCIES = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
CONFIG = {  # (key, sign, weight) — FRED-calibrated stable drivers
    "EUR": [("yield", +1, 0.451), ("iron", +1, 0.279), ("risk", -1, 0.191)],
    "GBP": [("risk", -1, 0.612), ("iron", +1, 0.173), ("yield", +1, 0.127)],
    "AUD": [("risk", -1, 0.504), ("yield", +1, 0.249), ("iron", +1, 0.175)],
    "NZD": [("risk", -1, 0.475), ("yield", +1, 0.241), ("iron", +1, 0.206)],
    "USD": [("risk", +1, 0.388), ("yield", +1, 0.357), ("iron", -1, 0.212)],
    "CAD": [("risk", -1, 0.328), ("yield", +1, 0.312), ("iron", +1, 0.183)],
    "CHF": [("yield", +1, 0.465), ("iron", +1, 0.219)],
    "JPY": [("yield", +1, 0.834)],
}
IRON_LITERAL = {"AUD"}
COMMODITY_CYCLE = {"NZD", "CAD"}
LOCAL10 = {"EUR": "IRLTLT01DEM156N", "GBP": "IRLTLT01GBM156N", "JPY": "IRLTLT01JPM156N",
           "CHF": "IRLTLT01CHM156N", "CAD": "IRLTLT01CAM156N", "AUD": "IRLTLT01AUM156N",
           "NZD": "IRLTLT01NZM156N"}


def fred(sid: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}"
    df = pd.read_csv(url, parse_dates=["observation_date"], na_values=["."])
    return df.set_index("observation_date")[sid].astype(float).dropna().sort_index()


# --- DAILY series on a common business-day index ---
idx = pd.bdate_range(START, pd.Timestamp.today())
vix = fred("VIXCLS").reindex(idx).ffill()
us10 = fred("DGS10").reindex(idx).ffill()                 # US 10Y, DAILY
iron = np.log(fred("PIORECRUSDM")).reindex(idx).ffill()   # monthly -> ffilled daily
local10 = {c: fred(s).reindex(idx).ffill() for c, s in LOCAL10.items()}  # monthly -> ffilled
exus = pd.concat(local10.values(), axis=1).mean(axis=1)
yadv = {c: (local10[c] - us10) for c in LOCAL10}
yadv["USD"] = (us10 - exus)


def change_series(key: str, ccy: str, w: int) -> pd.Series:
    if key == "risk":
        return vix - vix.shift(w)
    if key == "iron":
        return iron - iron.shift(w)
    if key == "yield":
        return yadv[ccy] - yadv[ccy].shift(w)
    raise ValueError(key)


def reading(key: str, sign: int, ccy: str, w: int):
    s = change_series(key, ccy, w).dropna()
    trail = s.iloc[-Z_TRAIL:]
    sd = trail.std(ddof=1)
    z = 0.0 if (sd == 0 or np.isnan(sd)) else float((s.iloc[-1] - trail.mean()) / sd)
    raw = float(s.iloc[-1])
    if abs(z) < Z_FLAT:
        return "amber", 0, raw
    support = (1 if raw > 0 else -1) * sign
    return ("green" if support > 0 else "red"), support, raw


def label_for(key, ccy):
    if key == "risk":
        return "Risk sentiment"
    if key == "yield":
        return "Yield advantage"
    if ccy in IRON_LITERAL:
        return "Iron ore / commodities"
    return "Commodity cycle" if ccy in COMMODITY_CYCLE else "Global risk cycle"


def reason_for(key, colour, ccy, raw, w):
    if key == "risk":
        move = f"VIX {'+' if raw >= 0 else ''}{raw:.1f} over {w//21 or 1}m"
        if colour == "green":
            return f"Risk-on ({move}) — supports {ccy}"
        if colour == "red":
            return f"Risk-off ({move}) — weighs on {ccy}"
        return f"Risk roughly flat ({move})"
    if key == "yield":
        move = f"{'+' if raw >= 0 else ''}{raw*100:.0f}bp"
        if colour == "green":
            return f"Yield edge widening ({move}) — supports {ccy}"
        if colour == "red":
            return f"Yield edge narrowing ({move}) — weighs on {ccy}"
        return f"Yield edge steady ({move})"
    noun = ("Commodity demand" if ccy in IRON_LITERAL
            else "Commodity cycle" if ccy in COMMODITY_CYCLE else "Global risk cycle")
    if colour == "green":
        return f"{noun} firming — supports {ccy}"
    if colour == "red":
        return f"{noun} softening — weighs on {ccy}"
    return f"{noun} roughly flat"


CVAL = {"green": 1, "amber": 0, "red": -1}
out = {
    "as_of_risk": pd.Timestamp(fred("VIXCLS").index[-1]).strftime("%Y-%m-%d"),
    "as_of_rates_us": pd.Timestamp(fred("DGS10").index[-1]).strftime("%Y-%m-%d"),
    "as_of_slow": pd.Timestamp(fred("PIORECRUSDM").index[-1]).strftime("%Y-%m"),
    "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "windows": {"daily": "~30 days (matches strength meter)", "weekly": "~26 weeks"},
    "note": ("Explains the strength meter over matching windows. Risk & US rates daily; "
             "foreign rates & commodities monthly. Evidence, not a signal."),
    "periods": {},
}
for pname, w in WIN.items():
    out["periods"][pname] = {}
    for ccy in CURRENCIES:
        drivers, tilt = [], 0.0
        for key, sign, weight in CONFIG[ccy]:
            colour, _s, raw = reading(key, sign, ccy, w)
            tilt += CVAL[colour] * weight
            drivers.append({"key": key, "label": label_for(key, ccy), "colour": colour,
                            "reason": reason_for(key, colour, ccy, raw, w),
                            "weight": round(weight, 3)})
        drivers.sort(key=lambda d: d["weight"], reverse=True)
        out["periods"][pname][ccy] = {"tilt": round(tilt, 3), "drivers": drivers}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print("Wrote", OUT)

# ---- ALIGNMENT CHECK vs live strength meter ----
try:
    import urllib.request
    m = json.loads(urllib.request.urlopen(
        "https://raw.githubusercontent.com/iamtayweisheng-ctrl/fxstrength/data/matrix.json", timeout=20).read())
    print("ALIGNMENT CHECK — driver tilt vs strength score (daily/30d window):")
    print(f"{'ccy':<5}{'driver_tilt':>12}{'strength_score':>16}{'strength_dir':>14}")
    for ccy in CURRENCIES:
        t = out["periods"]["daily"][ccy]["tilt"]
        sc = m["timeframes"]["daily"]["scores"].get(ccy, {})
        print(f"{ccy:<5}{t:>12.3f}{sc.get('score','?'):>16}{sc.get('arrow','?'):>14}")
except Exception as e:
    print("alignment check skipped:", e)
