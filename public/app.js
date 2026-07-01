// FXStrength front-end. Loads the static matrix.json (built by the worker and
// served from the CDN) and renders the multi-timeframe strength grid. No server,
// no framework — just fetch + render, re-polled while the tab is open.

const REFRESH_MS = 60_000;

// Where the live strength data comes from. In production the JSON lives on a
// separate `data` branch (refreshed by GitHub Actions) and is served from
// GitHub's CDN, so the site itself never rebuilds when data updates. Locally we
// just read the committed copy.
const IS_LOCAL = ['localhost', '127.0.0.1', ''].includes(location.hostname);
const DATA_URL = IS_LOCAL
  ? 'data/matrix.json'
  : 'https://raw.githubusercontent.com/iamtayweisheng-ctrl/fxstrength/data/matrix.json';
const CCY_NAME = {
  USD: 'US Dollar', EUR: 'Euro', JPY: 'Yen', GBP: 'Pound', AUD: 'Aussie',
  CHF: 'Franc', CAD: 'Loonie', NZD: 'Kiwi', XAU: 'Gold', XAG: 'Silver',
};
const ARROWS = { up: '▲', down: '▼', flat: '—' };
const LINE_COLORS = {
  USD: '#f59e0b', EUR: '#ef4444', JPY: '#22d3ee', GBP: '#22c55e',
  AUD: '#3b82f6', CHF: '#a78bfa', CAD: '#ec4899', NZD: '#14b8a6',
  XAU: '#fde047', XAG: '#cbd5e1',
};
const LINE_ORDER = ['USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CHF', 'CAD', 'NZD', 'XAU', 'XAG'];
let chartToday = null;
let chartPrev = null;

// score (0-10) -> colour, interpolated red → grey → green
function scoreColor(s) {
  const t = Math.max(0, Math.min(10, s)) / 10;      // 0..1
  if (t < 0.5) {                                     // red → neutral
    const k = t / 0.5;
    return `rgb(${239 - k * 139}, ${68 + k * 48}, ${68 + k * 71})`;
  }
  const k = (t - 0.5) / 0.5;                          // neutral → green
  return `rgb(${100 - k * 66}, ${116 + k * 81}, ${139 - k * 45})`;
}

function cell(score) {
  const c = document.createElement('div');
  c.className = 'gcell';
  if (!score) { c.innerHTML = '<div class="bar"><span class="score">·</span></div>'; return c; }
  const col = scoreColor(score.score);
  const pct = (score.score / 10) * 100;
  c.innerHTML = `
    <div class="bar" title="${score.pct >= 0 ? '+' : ''}${score.pct}% vs the basket · rank ${score.rank}">
      <span class="fill" style="width:${pct}%;background:${col}"></span>
      <span class="score" style="color:${col}">${score.score.toFixed(1)}</span>
      <span class="arrow ${score.arrow}">${ARROWS[score.arrow] || '—'}</span>
    </div>`;
  return c;
}

function render(matrix) {
  const grid = document.getElementById('grid');
  const order = matrix.timeframe_order || Object.keys(matrix.timeframes);
  const tfs = order.filter((m) => matrix.timeframes[m]);

  grid.innerHTML = '';
  grid.style.gridTemplateColumns = `72px repeat(${tfs.length}, 1fr)`;

  // header row
  grid.appendChild(hcell('', 'ghead rowlabel'));
  tfs.forEach((m) => grid.appendChild(hcell(m, 'ghead')));

  // currency rows, ordered by the daily rank (fall back to first tf)
  const rankTf = matrix.timeframes.daily || matrix.timeframes[tfs[0]];
  const ccys = [...matrix.currencies].sort(
    (a, b) => (rankTf.scores[a]?.rank || 99) - (rankTf.scores[b]?.rank || 99)
  );

  ccys.forEach((ccy) => {
    const scores = tfs.map((m) => matrix.timeframes[m].scores[ccy]);
    const label = hcell('', 'ghead rowlabel');
    const isMetal = ccy === 'XAU' || ccy === 'XAG';
    label.innerHTML =
      `<span class="ccy${isMetal ? ' metal' : ''}">${ccy}</span>`;
    label.title = CCY_NAME[ccy] || ccy;

    // highlight rows aligned strong / weak across every timeframe
    const vals = scores.filter(Boolean).map((s) => s.score);
    if (vals.length === tfs.length && vals.every((v) => v >= 6.5)) label.classList.add('aligned-strong');
    if (vals.length === tfs.length && vals.every((v) => v <= 3.5)) label.classList.add('aligned-weak');

    grid.appendChild(label);
    scores.forEach((s) => grid.appendChild(cell(s)));
  });

  // status line
  const gen = new Date(matrix.generated_at);
  document.getElementById('updated').textContent =
    'updated ' + gen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const mkt = document.getElementById('market-status');
  mkt.textContent = matrix.market_open ? 'Market open' : 'Market closed';
  mkt.className = 'market ' + (matrix.market_open ? 'open' : 'closed');
  if (matrix.source) document.getElementById('src').textContent = matrix.source;
}

function hcell(text, cls) {
  const d = document.createElement('div');
  d.className = cls;
  d.textContent = text;
  return d;
}

// ── intraday line charts ────────────────────────────────────────────────
const CHART_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  interaction: { mode: 'index', intersect: false },
  plugins: {
    legend: { labels: { color: '#8a97b1', boxWidth: 10, boxHeight: 10, font: { size: 11 } } },
    tooltip: {
      callbacks: {
        label: (c) => `${c.dataset.label}: ${c.parsed.y >= 0 ? '+' : ''}${c.parsed.y.toFixed(2)}%`,
      },
    },
  },
  scales: {
    x: { ticks: { color: '#5b6884', maxTicksLimit: 8, font: { size: 10 } }, grid: { color: 'rgba(30,39,64,.5)' } },
    y: { ticks: { color: '#5b6884', font: { size: 10 }, callback: (v) => v + '%' }, grid: { color: 'rgba(30,39,64,.5)' } },
  },
};

function datasets(lines) {
  return LINE_ORDER.filter((c) => lines[c]).map((c) => {
    const metal = c === 'XAU' || c === 'XAG';
    return {
      label: c,
      data: lines[c],
      borderColor: LINE_COLORS[c] || '#888',
      backgroundColor: LINE_COLORS[c] || '#888',
      borderWidth: 2,
      borderDash: metal ? [5, 4] : [],
      pointRadius: 0,
      pointHoverRadius: 3,
      tension: 0.25,
      hidden: metal,            // metals off by default to keep it readable
    };
  });
}

function makeChart(id, inst, day) {
  const el = document.getElementById(id);
  if (!el) return inst;
  if (!day) {                    // no data (e.g. no previous day yet)
    if (inst) { inst.destroy(); }
    el.parentElement.style.opacity = 0.35;
    return null;
  }
  el.parentElement.style.opacity = 1;
  const ds = datasets(day.lines);
  if (inst) {                    // update in place, preserving legend toggles
    inst.data.labels = day.times;
    const byLabel = Object.fromEntries(ds.map((d) => [d.label, d.data]));
    inst.data.datasets.forEach((d) => { d.data = byLabel[d.label] || []; });
    inst.update('none');
    return inst;
  }
  return new Chart(el, { type: 'line', data: { labels: day.times, datasets: ds }, options: CHART_OPTS });
}

function renderCharts(intra) {
  if (!intra || typeof Chart === 'undefined') return;
  chartToday = makeChart('chart-today', chartToday, intra.today);
  chartPrev = makeChart('chart-prev', chartPrev, intra.prev);
  const td = document.getElementById('chart-today-date');
  const pd = document.getElementById('chart-prev-date');
  if (td && intra.today) td.textContent = intra.today.date + ' UTC';
  if (pd && intra.prev) pd.textContent = intra.prev.date + ' UTC';
}

async function load() {
  try {
    const r = await fetch(DATA_URL + '?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const matrix = await r.json();
    render(matrix);
    renderCharts(matrix.timeframes.intraday);
  } catch (e) {
    document.getElementById('grid').innerHTML =
      `<p class="loading">Couldn't load strength data (${e.message}). Retrying…</p>`;
  }
}

// email capture — front-end stub. Wire to a form backend (Formspree / Beehiiv /
// ConvertKit) before launch; for now it just acknowledges locally.
function initCapture() {
  const form = document.getElementById('capture-form');
  const note = document.getElementById('capture-note');
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const email = document.getElementById('capture-email').value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      note.textContent = 'Please enter a valid email.';
      return;
    }
    // TODO: POST to the list provider here.
    note.textContent = "You're on the list — we'll be in touch when alerts launch.";
    form.reset();
  });
}

function initRefresh() {
  const btn = document.getElementById('refresh');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    btn.classList.add('spinning');
    await load();
    setTimeout(() => btn.classList.remove('spinning'), 400);
  });
}

load();
initCapture();
initRefresh();
setInterval(load, REFRESH_MS);
