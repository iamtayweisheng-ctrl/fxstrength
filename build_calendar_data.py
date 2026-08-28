#!/usr/bin/env python3
"""
build_calendar_data.py  —  FXStrength Live Driver Meter, calendar layer (Phase 1, FREE).

Pulls ForexFactory's free weekly calendar JSON, keeps the High-impact events, maps each
one to the meter's own drivers (Yield / Commodity / Oil / Risk), splits released vs
upcoming, and writes public/calendar-data.json grouped by currency. The meter reads that
file (same-origin) and shows "this week — events driving the meter".

Guardrail: events are CONTEXT, not signals. We show the surprise (actual vs forecast) and
which driver to watch — never a buy/sell read.

Stdlib only (urllib/json). Refresh daily via CI.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "public", "calendar-data.json")

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CURRENCIES = {"EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"}

# Per-currency label for the commodity driver, to match the meter cards.
def commodity_label(ccy):
    return "Iron ore / commodities" if ccy == "AUD" else "Commodity cycle"

DRIVER_LABEL = {"yield": "Yield advantage", "oil": "Oil", "risk": "Risk sentiment"}


def map_event(country, title):
    """Which (currency, driver) pairs this event is context for. [] = skip."""
    t = title.lower()
    # Oil / OPEC → the Oil driver, which the meter carries on CAD.
    if any(k in t for k in ("oil", "crude", "opec", "wti")):
        return [("CAD", "oil")]
    # China data → the Commodity cycle for AUD & NZD (China's demand reaches them there).
    if country in ("CNY", "CNH"):
        return [("AUD", "commodity"), ("NZD", "commodity")]
    if country not in CURRENCIES:
        return []
    # Everything else that's high-impact — inflation, rates, jobs, growth, central-bank
    # speak — runs through rate expectations = the Yield driver.
    return [(country, "yield")]


def to_num(s):
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def surprise(actual, forecast):
    a, f = to_num(actual), to_num(forecast)
    if a is None or f is None:
        return None
    if abs(a - f) < 1e-9:
        return "in line"
    return "above" if a > f else "below"


def fetch():
    req = urllib.request.Request(FEED, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    events = fetch()
    by_ccy = {}          # ccy -> list of event dicts
    for e in events:
        if (e.get("impact") or "").lower() != "high":
            continue
        country = e.get("country", "")
        title = e.get("title", "")
        actual = e.get("actual") or ""
        forecast = e.get("forecast") or ""
        previous = e.get("previous") or ""
        date = e.get("date", "")
        try:
            dt = datetime.fromisoformat(date)
            day = dt.strftime("%a")          # Mon, Tue…
            iso = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            day, iso = "", date
        released = bool(actual.strip())
        for ccy, driver in map_event(country, title):
            label = commodity_label(ccy) if driver == "commodity" else DRIVER_LABEL[driver]
            by_ccy.setdefault(ccy, []).append({
                "title": title,
                "driver": driver,
                "driver_label": label,
                "day": day,
                "date": iso,
                "when": "released" if released else "upcoming",
                "forecast": forecast,
                "previous": previous,
                "actual": actual if released else "",
                "surprise": surprise(actual, forecast) if released else None,
            })

    # sort each currency's events by date; released first is handled in the frontend
    for ccy in by_ccy:
        by_ccy[ccy].sort(key=lambda x: x["date"])

    # order currencies by how many events they have (busiest first), then alphabetically
    order = sorted(by_ccy, key=lambda c: (-len(by_ccy[c]), c))

    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ForexFactory weekly calendar (High-impact)",
        "note": "This week's high-impact events, mapped to the meter's drivers. Context, not signals.",
        "order": order,
        "currencies": by_ccy,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    total = sum(len(v) for v in by_ccy.values())
    print(f"Wrote {OUT} | {total} high-impact event-tags across {len(by_ccy)} currencies")


if __name__ == "__main__":
    main()
