#!/usr/bin/env python3
"""
build_driver_data.py  —  FXStrength Live Driver Meter data pipeline.

Pulls the FRED series (free CSV, no API key), computes each currency-driver's
current reading for all three periods (Reactive / Swing / Position), and writes
ONE small JSON (public/driver-data.json) that the meter frontend reads.

Freshness by driver (deliberate — see Brain's data-lag note):
  * Risk (VIX)  → DAILY. The highest-weight driver, current to ~yesterday.
  * Yield diff  → MONTHLY. The foreign 10Y leg is monthly-only on free data.
  * Iron ore    → MONTHLY.
Each driver carries its OWN `as_of`; top level exposes `as_of_risk` (daily) and
`as_of_slow` (monthly) so the frontend can date them honestly and never claim a
slow driver is fresher than it is.

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
YIELD = {  # 10Y government yields (monthly)
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

# "iron" driver labelling: literal iron ore ONLY for AUD; NZD/CAD are commodity
# exporters but not iron-ore, so "Commodity cycle"; the rest = "Global risk cycle".
def iron_group(ccy):
    if ccy == "AUD":
        return "ironore"
    if ccy in ("NZD", "CAD"):
        return "commodity"
    return "globalrisk"

# Period lookbacks: months for the slow (monthly) drivers, trading-days for risk.
PERIODS_M = {"reactive": 1, "swing": 3, "position": 12}
PERIODS_D = {"reactive": 21, "swing": 63, "position": 252}
STD_M = 36      # trailing months for slow-driver volatility
STD_D = 504     # trailing trading days (~2y) for risk volatility
FLAT_Z = 0.5    # |z| below this = amber (flat)


def fetch_rows(series_id):
    """Fetch a FRED CSV → ordered [(date 'YYYY-MM-DD', float)], skipping gaps."""
    url = FRED.format(series_id)
    with urllib.request.urlopen(url, timeout=30) as r:
        text = r.read().decode("utf-8")
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0] in ("DATE", "observation_date"):
            continue
        date, val = row[0].strip(), row[1].strip()
        if val in (".", ""):
            continue
        try:
            out.append((date, float(val)))
        except ValueError:
            continue
    out.sort()
    return out


def to_monthly(rows):
    """Collapse daily/any rows to month-end values → ordered [(YYYY-MM, val)]."""
    m = {}
    for date, val in rows:
        m[date[:7]] = val  # later date in the month overwrites → month-end
    return sorted(m.items())


def diff_series(local, us):
    """local10Y - us10Y over shared months → ordered [(YYYY-MM, diff)]."""
    ld, ud = dict(local), dict(us)
    return [(ym, ld[ym] - ud[ym]) for ym in sorted(set(ld) & set(ud))]


def usd_yield_series(monthly_by_country):
    """USD yield advantage = US10Y minus the equal-weight mean of the other seven."""
    us = dict(monthly_by_country["US"])
    others = [c for c in monthly_by_country if c != "US"]
    od = {c: dict(monthly_by_country[c]) for c in others}
    out = []
    for ym in sorted(us):
        vals = [od[c][ym] for c in others if ym in od[c]]
        if len(vals) >= 4:
            out.append((ym, us[ym] - statistics.mean(vals)))
    return out


def zscore(series, window, std_window):
    """
    series: ordered [(date, level)]. Returns (change_now, z, latest_date) for the
    given lookback, standardized by trailing std of that same change measure.
    """
    if len(series) <= window + 2:
        return 0.0, 0.0, (series[-1][0] if series else None)
    vals = [v for _, v in series]
    changes = [vals[i] - vals[i - window] for i in range(window, len(vals))]
    change_now = changes[-1]
    hist = changes[-(std_window + 1):-1] if len(changes) > std_window else changes[:-1]
    latest = series[-1][0]
    if len(hist) < 6:
        return change_now, 0.0, latest
    sd = statistics.pstdev(hist)
    z = change_now / sd if sd > 1e-9 else 0.0
    return change_now, z, latest


def reason(key, ccy, direction, colour):
    """Plain-English reason string (no numbers)."""
    if key == "risk":
        phrase = "Risk-off" if direction > 0 else "Risk-on" if direction < 0 else "Risk steady"
    elif key == "yield":
        phrase = ("Yield edge widening" if direction > 0 else
                  "Yield edge narrowing" if direction < 0 else "Yield edge steady")
    else:  # iron
        g = iron_group(ccy)
        if g == "ironore":
            phrase = ("Iron ore rising" if direction > 0 else
                      "Iron ore falling" if direction < 0 else "Iron ore steady")
        elif g == "commodity":
            phrase = ("Commodity cycle strengthening" if direction > 0 else
                      "Commodity cycle weakening" if direction < 0 else "Commodity cycle steady")
        else:
            phrase = ("Global risk cycle strengthening" if direction > 0 else
                      "Global risk cycle weakening" if direction < 0 else "Global risk cycle steady")
    # "currently" reinforces evidence-not-signal (a driver's effect isn't permanent).
    effect = ("currently supports " + ccy if colour == "green" else
              "currently weighs on " + ccy if colour == "red" else "neutral")
    return phrase + " — " + effect


def label(key, ccy):
    if key == "risk":
        return "Risk sentiment"
    if key == "yield":
        return "Yield advantage"
    g = iron_group(ccy)
    return ("Iron ore / commodities" if g == "ironore" else
            "Commodity cycle" if g == "commodity" else "Global risk cycle")


def main():
    print("Fetching FRED series...")
    vix_daily = fetch_rows(VIX)                 # DAILY — kept daily
    iron_monthly = to_monthly(fetch_rows(IRON))  # monthly
    yields_monthly = {c: to_monthly(fetch_rows(sid)) for c, sid in YIELD.items()}
    print("  VIX daily obs:", len(vix_daily), "| iron months:", len(iron_monthly),
          "| yield months:", {c: len(v) for c, v in yields_monthly.items()})

    # Per-driver level series.
    risk_series = vix_daily
    iron_series = iron_monthly
    yld_series = {"USD": usd_yield_series(yields_monthly)}
    for ccy, country in CCY_COUNTRY.items():
        yld_series[ccy] = diff_series(yields_monthly[country], yields_monthly["US"])

    as_of_risk = risk_series[-1][0] if risk_series else None       # daily YYYY-MM-DD
    slow_dates = [iron_series[-1][0]] + [s[-1][0] for s in yld_series.values() if s]
    as_of_slow = min(slow_dates) if slow_dates else None           # monthly YYYY-MM

    out_periods = {}
    for pname in PERIODS_M:
        wm, wd = PERIODS_M[pname], PERIODS_D[pname]
        per = {}
        for ccy in ORDER:
            drivers_out, tilt = [], 0.0
            for key, sign, weight in DRIVERS[ccy]:
                if key == "risk":
                    series, win, sw = risk_series, wd, STD_D
                elif key == "iron":
                    series, win, sw = iron_series, wm, STD_M
                else:
                    series, win, sw = yld_series[ccy], wm, STD_M
                change_now, z, latest = zscore(series, win, sw)
                if abs(z) < FLAT_Z:
                    colour, cval = "amber", 0
                else:
                    supports = sign * (1 if change_now > 0 else -1)
                    colour, cval = ("green", 1) if supports > 0 else ("red", -1)
                tilt += cval * weight
                rdir = 0 if colour == "amber" else (1 if change_now > 0 else -1)
                drivers_out.append({
                    "key": key,
                    "label": label(key, ccy),
                    "colour": colour,
                    "reason": reason(key, ccy, rdir, colour),
                    "weight": round(weight, 3),
                    "as_of": latest,
                })
            drivers_out.sort(key=lambda d: d["weight"], reverse=True)
            per[ccy] = {"tilt": round(tilt, 4), "drivers": drivers_out}
        out_periods[pname] = per

    data = {
        "as_of": as_of_slow,          # legacy field = the most-lagged (honest) month
        "as_of_risk": as_of_risk,     # daily
        "as_of_slow": as_of_slow,     # monthly (rates & commodities)
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Direction of evidence, not a signal. Colours computed from FRED data via fixed rules + calibrated weights.",
        "periods": out_periods,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Wrote", OUT, "| risk as of", as_of_risk, "| rates/commodities as of", as_of_slow)


if __name__ == "__main__":
    main()
