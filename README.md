# StrengthGrid

A free, fast, **multi-timeframe currency strength meter** — the 8 major
currencies plus **gold (XAU)** and **silver (XAG)**, scored across daily,
weekly and intraday windows on one grid.

Built as a standalone tool and the top-of-funnel for FXFlow. The differentiator
over the incumbents (currencystrengthmeter.org etc.) is the **multi-timeframe
grid + metals + a shareable Pine Script export** (planned), with a confluence /
discount-zone layer as retention depth.

## How it works

```
worker/build_matrix.py   →  public/data/matrix.json   →  static front-end (public/)
   (cron, server-side)         (tiny static file, CDN)      (fetch + render)
```

- **`worker/build_matrix.py`** — pulls closes from Yahoo Finance for 28 FX
  crosses + gold/silver futures, computes each currency's relative strength
  (average % move vs the other seven, from the window start — the exact FXFlow
  method), and writes a single `matrix.json`. Standard library only; no `pip`.
- **`public/`** — a static HTML/CSS/JS site. The SEO copy is real HTML (great
  for crawlers); the live numbers hydrate client-side by fetching `matrix.json`.
  No server to run, deployable free on Cloudflare Pages / Netlify / Vercel.
- **`.github/workflows/build-matrix.yml`** — reruns the worker every ~15 min and
  commits the refreshed JSON. Swap for a dedicated worker later for 60s updates.

## Run locally

```bash
# 1. build the data
python worker/build_matrix.py

# 2. serve the static site (any static server works)
cd public
python -m http.server 8080
# open http://localhost:8080
```

## Data contract — `matrix.json`

```jsonc
{
  "generated_at": "2026-07-01T04:19:22+00:00",
  "market_open": true,
  "currencies": ["USD","EUR","JPY","GBP","AUD","CHF","CAD","NZD","XAU","XAG"],
  "timeframe_order": ["intraday","daily","weekly"],
  "timeframes": {
    "daily": {
      "label": "Daily · last 30 days",
      "window": 30,
      "asof": "2026-07-01",
      "scores": {
        "USD": { "pct": 2.55, "score": 10.0, "arrow": "up", "rank": 1 }
        // …one entry per currency
      }
    }
    // …intraday, weekly
  },
  "source": "Yahoo Finance"
}
```

- `pct` — raw strength (% vs the basket) for the window.
- `score` — 0 (weakest) to 10 (strongest), symmetric scale driven by the eight
  fiats; gold/silver clamp at the extremes.
- `arrow` — short-term slope: `up` / `down` / `flat`.
- `rank` — 1 = strongest that timeframe.

Both the grid and the planned Pine Script exporter consume this contract.

## Roadmap

- [ ] Pine Script v6 exporter (viral loop) — validate `request.security` limits first
- [ ] Confluence / discount-zone column (retention depth)
- [ ] Wire email capture to a list provider (funnel → FXFlow)
- [ ] Prop-firm affiliate widget
- [ ] EN / JP language toggle

> **Not financial advice.** Information tool only; FX/CFD trading carries a high
> risk of loss. Gold/silver use front-month futures (`GC=F` / `SI=F`) — % change
> is used, but contract rolls can add noise; treat metals as beta.
