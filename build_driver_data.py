#!/usr/bin/env python3
"""
build_driver_data.py  —  FXStrength Live Driver Meter data pipeline.

Pulls the FRED series (free CSV, no API key), computes each currency-driver's
current reading for all three periods (Reactive / Swing / Position), and writes
ONE small JSON (public/driver-data.json) that the meter frontend reads.

Nothing is manual: colours come from the data via fixed rules + the pre-computed
weights in g10_driver_weights.json. Re-run on a schedule to refresh.

Stdlib only (urllib/csv/json) — matches build_lessons.py, no pip installs.
"""

import csv
import io
import json
import os
import statistics
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "public", "driver-data.json")

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

# ── Series ────────────────────────────────────────────────────────────────
VIX = "VIXCLS"
IRON = "PIORECRUSDM"
YIELD = {  # 10Y government yields
    "US": "IRLTLT01USM156N", "DE": "IRLTLT01DEM156N", "GB": "IRLTLT01GBM156N",
    "JP": "IRLTLT01JPM156N", "CH": "IRLTLT01CHM156N", "CA": "IRLTLT01CAM156N",
    "AU": "IRLTLT01AUM156N", "NZ": "IRLTLT01NZM156N",
}
CCY_COUNTRY = {"EUR": "DE", "GBP": "GB", "JPY": "JP", "CHF": "CH",
               "CAD": "CA", "AUD": "AU", "NZD": "NZ"}  # USD handled specially

# ── Drivers + signs + weights (from g10_driver_weights.json — stable only) ──
# sign is on each series' NATURAL axis: VIX up = risk-off; yield-diff up = wider
# edge; iron ore up = commodity/growth cycle stronger. Colour = sign * change.
DRIVERS = {
    "EUR": [("yield", +1, 0.451), ("iron", +1, 0.279), ("risk", -1, 0.191)],
    "GBP": [("risk", -1, 0.612), ("iron", +1, 0.173), ("yield", +1, 0.127)],
    "AUD": [("risk", -1, 0.504), ("yield", +1, 0.249), ("iron", +1, 0.175)],
    "NZD": [("risk", -1, 0.475), ("yield", +1, 0.241), ("iron", +1, 0.206)],
    "USD": [("risk", +1, 0.388), ("yield", +1, 0.357), ("iron", -1, 0.212)],
    "CAD": [("risk", -1, 0.328), ("yield", +1, 0.312), ("iron", +1, 0.183)],
    "CHF": [("yield", +1, 0.465), ("iron", +1, 0.219)],
    "JPY": [("yield", +1, 0.834)],
}
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
COMMOD = {"AUD", "NZD", "CAD"}  # get a literal "iron ore" label; others = risk cycle

PERIODS = {"reactive": 1, "swing": 3, "position": 12}  # months of lookback
STD_WINDOW = 36   # trailing months for volatility standardization
FLAT_Z = 0.5      # |z| below this = amber (flat)


def fetch_monthly(series_id):
    """Fetch a FRED CSV and collapse to month-end values {'YYYY-MM': float}."""
    url = FRED.format(series_id)
    with urllib.request.urlopen(url, timeout=30) as r:
        text = r.read().decode("utf-8")
    monthly = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0] in ("DATE", "observation_date"):
            continue
        date, val = row[0].strip(), row[1].strip()
        if val in (".", ""):
            continue
        try:
            f = float(val)
        except ValueError:
            continue
        ym = date[:7]  # YYYY-MM
        monthly[ym] = f  # later date in same month overwrites → month-end
    return monthly


def ordered(monthly):
    return sorted(monthly.items())  # [(ym, val), ...] ascending


def diff_series(local, us):
    """local10Y - us10Y over shared months → ordered [(ym, diff)]."""
    out = []
    for ym in sorted(set(local) & set(us)):
        out.append((ym, local[ym] - us[ym]))
    return out


def usd_yield_series(yields_by_country):
    """USD yield advantage = US10Y minus the average of the other seven."""
    us = yields_by_country["US"]
    others = [c for c in yields_by_country if c != "US"]
    out = []
    for ym in sorted(us):
        vals = [yields_by_country[c][ym] for c in others if ym in yields_by_country[c]]
        if len(vals) >= 4:  # need a reasonable basket
            out.append((ym, us[ym] - statistics.mean(vals)))
    return out


def zscore(series, window_months):
    """
    series: ordered [(ym, level)]. Returns (change_now, z, latest_ym) for the
    given lookback, standardized by trailing std of that same change measure.
    """
    if len(series) <= window_months + 2:
        return 0.0, 0.0, series[-1][0] if series else None
    vals = [v for _, v in series]
    changes = [vals[i] - vals[i - window_months] for i in range(window_months, len(vals))]
    change_now = changes[-1]
    hist = changes[-(STD_WINDOW + 1):-1] if len(changes) > STD_WINDOW else changes[:-1]
    if len(hist) < 6:
        return change_now, 0.0, series[-1][0]
    sd = statistics.pstdev(hist)
    z = change_now / sd if sd > 1e-9 else 0.0
    return change_now, z, series[-1][0]


def reason(key, ccy, direction, colour):
    """Plain-English reason string (no numbers)."""
    if key == "risk":
        phrase = "Risk-off" if direction > 0 else "Risk-on" if direction < 0 else "Risk steady"
    elif key == "yield":
        phrase = ("Yield edge widening" if direction > 0 else
                  "Yield edge narrowing" if direction < 0 else "Yield edge steady")
    else:  # iron
        if ccy in COMMOD:
            phrase = ("Iron ore rising" if direction > 0 else
                      "Iron ore falling" if direction < 0 else "Iron ore steady")
        else:
            phrase = ("Global risk cycle strengthening" if direction > 0 else
                      "Global risk cycle weakening" if direction < 0 else "Global risk cycle steady")
    effect = ("supports " + ccy if colour == "green" else
              "weighs on " + ccy if colour == "red" else "neutral")
    return phrase + " — " + effect


def label(key, ccy):
    if key == "risk":
        return "Risk sentiment"
    if key == "yield":
        return "Yield advantage"
    return "Iron ore / commodities" if ccy in COMMOD else "Global risk cycle"


def main():
    print("Fetching FRED series...")
    vix = fetch_monthly(VIX)
    iron = fetch_monthly(IRON)
    yields = {c: fetch_monthly(sid) for c, sid in YIELD.items()}
    print("  VIX months:", len(vix), "| iron:", len(iron),
          "| yields:", {c: len(v) for c, v in yields.items()})

    # Build the per-driver level series each currency needs.
    risk_series = ordered(vix)
    iron_series = ordered(iron)
    yld_series = {"USD": usd_yield_series(yields)}
    for ccy, country in CCY_COUNTRY.items():
        yld_series[ccy] = diff_series(yields[country], yields["US"])

    latest_months = set()
    out_periods = {}
    for pname, w in PERIODS.items():
        per = {}
        for ccy in ORDER:
            drivers_out, tilt = [], 0.0
            for key, sign, weight in DRIVERS[ccy]:
                if key == "risk":
                    series = risk_series
                elif key == "iron":
                    series = iron_series
                else:
                    series = yld_series[ccy]
                change_now, z, latest = zscore(series, w)
                if latest:
                    latest_months.add(latest)
                # colour: sign * change, with a flat band on |z|
                if abs(z) < FLAT_Z:
                    colour, cval = "amber", 0
                else:
                    supports = sign * (1 if change_now > 0 else -1)
                    colour, cval = ("green", 1) if supports > 0 else ("red", -1)
                tilt += cval * weight
                # amber = the move is too small to matter → describe it as steady
                rdir = 0 if colour == "amber" else (1 if change_now > 0 else -1)
                drivers_out.append({
                    "key": key,
                    "label": label(key, ccy),
                    "colour": colour,
                    "reason": reason(key, ccy, rdir, colour),
                    "weight": round(weight, 3),
                })
            drivers_out.sort(key=lambda d: d["weight"], reverse=True)
            per[ccy] = {"tilt": round(tilt, 4), "drivers": drivers_out}
        out_periods[pname] = per

    # Honest freshness = the MOST-LAGGED input (monthly yields/iron lag ~2 months).
    as_of = min(latest_months) if latest_months else None
    data = {
        "as_of": as_of,                    # e.g. "2026-06"
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Direction of evidence, not a signal. Colours computed from FRED data via fixed rules + calibrated weights.",
        "periods": out_periods,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Wrote", OUT, "| data as of", as_of)


if __name__ == "__main__":
    main()
