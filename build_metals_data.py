"""
FXStrength Meter — METALS block generator (XAU / XAG).
Self-contained. Pulls the metal FACTORS from FRED (real yields, USD, risk) — all free/daily —
and emits driver-data blocks for XAU + XAG in the exact shape the meter frontend reads.

Weights are PRINCIPLED (established gold/silver macro), NOT yet data-calibrated — labelled as such.
Gold: dominantly real yields (-), then USD (-), then risk-off (+, haven). Silver: same shape, more
risk-sensitive + more volatile (higher betas); its risk relationship is the least certain (dual
precious/industrial nature) → prime candidate to recalibrate when clean price data is available.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

START = "2015-01-01"
WIN = {"daily": 21, "weekly": 130}      # trading days, matches the currency meter
Z_FLAT = 0.5
Z_TRAIL = 252

# (key, sign, weight[within-asset share, ordering], beta[raw sensitivity, cross-comparable tilt])
# sign = +1 if driver-UP helps the metal, -1 if driver-UP hurts it.
CONFIG = {
    "XAU": [("realyield", -1, 0.50, 0.50), ("usd", -1, 0.30, 0.30), ("risk", +1, 0.20, 0.20)],
    "XAG": [("realyield", -1, 0.40, 0.45), ("usd", -1, 0.25, 0.28), ("risk", +1, 0.35, 0.35)],
}
LABEL = {"realyield": "Real yields (US 10Y)", "usd": "US dollar", "risk": "Risk sentiment"}


def fred(sid: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}"
    df = pd.read_csv(url, parse_dates=["observation_date"], na_values=["."])
    return df.set_index("observation_date")[sid].astype(float).dropna().sort_index()


idx = pd.bdate_range(START, pd.Timestamp.today())
realyield = fred("DFII10").reindex(idx).ffill()               # US 10Y real yield (%)
usd = np.log(fred("DTWEXBGS")).reindex(idx).ffill()           # broad USD index (log level)
vix = fred("VIXCLS").reindex(idx).ffill()


def change_series(key: str, w: int) -> pd.Series:
    if key == "realyield":
        return realyield - realyield.shift(w)     # level change (%-pts)
    if key == "usd":
        return usd - usd.shift(w)                 # log-change (% move)
    if key == "risk":
        return vix - vix.shift(w)                 # level change
    raise ValueError(key)


def reading(key: str, sign: int, w: int):
    s = change_series(key, w).dropna()
    trail = s.iloc[-Z_TRAIL:]
    sd = trail.std(ddof=1)
    z = 0.0 if (sd == 0 or np.isnan(sd)) else float((s.iloc[-1] - trail.mean()) / sd)
    raw = float(s.iloc[-1])
    if abs(z) < Z_FLAT:
        return "amber", raw
    support = (1 if raw > 0 else -1) * sign
    return ("green" if support > 0 else "red"), raw


def reason_for(key: str, colour: str, asset: str) -> str:
    name = "XAU" if asset == "XAU" else "XAG"
    if key == "realyield":
        if colour == "green":
            return f"Real yields falling — supports {name}"
        if colour == "red":
            return f"Real yields rising — weighs on {name}"
        return "Real yields roughly flat"
    if key == "usd":
        if colour == "green":
            return f"Dollar softening — supports {name}"
        if colour == "red":
            return f"Dollar firming — weighs on {name}"
        return "Dollar roughly flat"
    # risk (haven)
    if colour == "green":
        return f"Risk-off — supports {name} (haven)"
    if colour == "red":
        return f"Risk-on — weighs on {name}"
    return "Risk sentiment roughly flat"


CVAL = {"green": 1, "amber": 0, "red": -1}
periods = {}
for pname, w in WIN.items():
    periods[pname] = {}
    for asset in ("XAU", "XAG"):
        drivers, tilt = [], 0.0
        for key, sign, weight, beta in CONFIG[asset]:
            colour, _raw = reading(key, sign, w)
            tilt += CVAL[colour] * beta
            drivers.append({"key": key, "label": LABEL[key], "colour": colour,
                            "reason": reason_for(key, colour, asset),
                            "weight": round(weight, 3), "beta": round(beta, 3)})
        drivers.sort(key=lambda d: d["weight"], reverse=True)
        periods[pname][asset] = {"tilt": round(tilt, 3), "drivers": drivers}

out = {
    "_metals_note": ("Principled weights (established gold/silver macro), not yet data-calibrated. "
                     "Real yields dominant, USD second, risk-off (haven) third. Silver more risk-sensitive; "
                     "its risk relationship is least certain — recalibrate when price data available."),
    "as_of_metals": pd.Timestamp(fred("DFII10").index[-1]).strftime("%Y-%m-%d"),
    "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "metals_periods": periods,   # merge each asset under the matching driver-data.json period
}
import os
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "metals-data.json")
with open(_OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
