# fxstrength-refresh — Cloudflare Worker (reliable data refresh)

GitHub's scheduled workflows throttle badly (every few hours, long gaps), which
makes fxstrength.org look frozen. This tiny Worker fires on a **reliable
Cloudflare cron** and pings the GitHub Actions `build-matrix` workflow via
`workflow_dispatch` (which runs promptly). No compute here — GitHub still does
the work. Free on Cloudflare's Workers free plan.

## Deploy (dashboard — no CLI/Node needed)

1. **Make a scoped GitHub token**
   GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate:
   - Repository access: **Only** `iamtayweisheng-ctrl/fxstrength`
   - Permissions → Repository → **Actions: Read and write**
   - Generate and copy the token (`github_pat_…`).

2. **Create the Worker**
   Cloudflare dashboard → **Workers & Pages → Create → Worker** → name it
   `fxstrength-refresh` → Deploy → **Edit code** → paste the contents of
   `src/index.js` → **Deploy**.

3. **Add the token as a secret**
   Worker → **Settings → Variables and Secrets** → add a **Secret**:
   name `GH_TOKEN`, value = the token from step 1.

4. **Add the cron trigger**
   Worker → **Settings → Triggers → Cron Triggers → Add** → `*/15 * * * *`.

5. **Test**
   Open the Worker's URL (`https://fxstrength-refresh.<your-subdomain>.workers.dev`)
   in a browser — it should say **"ok — refresh triggered"**. Then check
   GitHub → Actions (a run should start) and, a minute later, that the site's
   "updated" time moves.

## Notes
- CLI alternative: `wrangler deploy` then `wrangler secret put GH_TOKEN`.
- The GitHub Actions `schedule:` cron in `.github/workflows/build-matrix.yml` can
  be left as a backup or removed once this Worker is running.
