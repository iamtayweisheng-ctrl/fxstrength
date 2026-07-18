// Cloudflare Worker (cron trigger) for FXStrength.
//
// Why: the data refresh runs as a GitHub Actions workflow, but GitHub's own
// scheduler throttles hard (fires only every few hours, with long gaps) so the
// site looks "hung". API-triggered `workflow_dispatch` runs promptly, and
// Cloudflare cron triggers fire reliably — so this Worker just pings GitHub on a
// schedule. It does NOT compute anything; GitHub Actions still does the work.
//
// Setup (see README.md): store a GitHub fine-grained PAT (Actions: read/write on
// the fxstrength repo) as the secret GH_TOKEN, and set the cron in wrangler.toml.

const REPO = 'iamtayweisheng-ctrl/fxstrength';
const WORKFLOW = 'build-matrix.yml';

async function trigger(env) {
  return fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'fxstrength-refresh-cron',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ref: 'main' }),
    },
  );
}

export default {
  // Fires on the cron schedule defined in wrangler.toml.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(
      trigger(env).then(async (res) => {
        if (!res.ok) console.log('dispatch failed', res.status, await res.text());
      }),
    );
  },

  // Visiting the Worker URL triggers a refresh too — handy for a manual test.
  async fetch(request, env) {
    const res = await trigger(env);
    const body = res.ok ? 'ok — refresh triggered' : `failed ${res.status}: ${await res.text()}`;
    return new Response(body, { status: res.ok ? 200 : 502 });
  },
};
