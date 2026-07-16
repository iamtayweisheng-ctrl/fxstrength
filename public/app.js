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
let chartMain = null;
let chartDay = 'today';

// Tradeable instruments for the trade-ideas panel: the 28 fiat crosses plus
// gold & silver vs USD. slice(0,3)/slice(3) splits base/quote (works for XAU/XAG too).
const PAIRS = [
  'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD',
  'EURGBP', 'EURJPY', 'EURCHF', 'EURAUD', 'EURCAD', 'EURNZD',
  'GBPJPY', 'GBPCHF', 'GBPAUD', 'GBPCAD', 'GBPNZD',
  'AUDJPY', 'AUDCHF', 'AUDCAD', 'AUDNZD',
  'CADJPY', 'CHFJPY', 'NZDJPY', 'NZDCHF', 'NZDCAD', 'CADCHF',
  'XAUUSD', 'XAGUSD',            // gold & silver vs USD
];
let ideasTf = 'daily';
let lastMatrix = null;

// Risk-on (commodity) vs safe-haven currencies, for the risk gauge.
const RISK_ON = ['AUD', 'NZD', 'CAD'];
const HAVENS = ['USD', 'JPY', 'CHF'];

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

// ── risk sentiment ──────────────────────────────────────────────────────
// FX-derived gauge (commodity currencies vs havens) plus VIX / S&P context.
function renderRisk(matrix) {
  const sec = document.querySelector('.risk');
  if (!sec) return;
  const tf = matrix.timeframes.daily ? 'daily' : matrix.timeframe_order[0];
  const sc = matrix.timeframes[tf].scores;
  const avg = (arr) => {
    const vals = arr.map((c) => (sc[c] ? sc[c].score : 5));
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  };
  const gauge = avg(RISK_ON) - avg(HAVENS);        // roughly -10 … +10
  const pos = Math.max(2, Math.min(98, ((gauge + 10) / 20) * 100));
  document.getElementById('risk-needle').style.left = pos + '%';

  const lbl = document.getElementById('risk-label');
  const state = gauge > 1.5 ? 'on' : gauge < -1.5 ? 'off' : 'mid';
  lbl.textContent = `${state === 'on' ? 'Risk ON' : state === 'off' ? 'Risk OFF' : 'Mixed'} · FX ${gauge >= 0 ? '+' : ''}${gauge.toFixed(1)}`;
  lbl.className = 'risk-label ' + state;

  const m = matrix.market || {};
  const chips = [];
  if (m.vix) {
    const lv = m.vix.level;
    const band = lv >= 30 ? 'high' : lv >= 20 ? 'elevated' : lv >= 15 ? 'normal' : 'calm';
    chips.push(`<div class="rchip ${lv >= 20 ? 'off' : 'on'}">VIX ${lv} <span>${band} · ${m.vix.chg >= 0 ? '+' : ''}${m.vix.chg}</span></div>`);
  }
  if (m.sp500) {
    const up = m.sp500.pct >= 0;
    chips.push(`<div class="rchip ${up ? 'on' : 'off'}">S&amp;P 500 <span>${up ? '+' : ''}${m.sp500.pct}% · ${m.sp500.level}</span></div>`);
  }
  document.getElementById('risk-context').innerHTML =
    chips.join('') || '<span class="hint">Market context unavailable.</span>';
}

// ── trade ideas ─────────────────────────────────────────────────────────
// For each pair, the strength gap between its two currencies. Buy the strong
// one / sell the weak one; a wider gap = a clearer imbalance. Pure client-side
// derivation from the grid scores — no worker involvement.
function renderIdeas(matrix) {
  const list = document.getElementById('ideas-list');
  if (!list) return;
  const tf = matrix.timeframes[ideasTf] ? ideasTf : matrix.timeframe_order[0];
  const scores = matrix.timeframes[tf].scores;

  const ideas = PAIRS.map((p) => {
    const base = p.slice(0, 3), quote = p.slice(3);
    const b = scores[base], q = scores[quote];
    if (!b || !q) return null;
    const gap = b.score - q.score;                 // 0–10 scale, consistent with grid
    const buy = gap >= 0;
    return {
      pair: p, buy,
      strongC: buy ? base : quote, weakC: buy ? quote : base,
      strongS: buy ? b.score : q.score, weakS: buy ? q.score : b.score,
      gap: Math.abs(gap),
    };
  }).filter(Boolean).sort((a, b) => b.gap - a.gap).slice(0, 8);

  list.innerHTML = ideas.map((i) => {
    const dir = i.buy ? 'buy' : 'sell';
    const pct = Math.min(100, (i.gap / 10) * 100);
    return `
      <div class="idea ${dir}">
        <div class="idea-top">
          <span class="idea-pair">${i.pair}</span>
          <span class="idea-dir ${dir}">${i.buy ? 'Buy' : 'Sell'}</span>
        </div>
        <div class="idea-detail">
          <span class="s-strong">${i.strongC} ${i.strongS.toFixed(1)}</span>
          &nbsp;vs&nbsp;
          <span class="s-weak">${i.weakC} ${i.weakS.toFixed(1)}</span>
        </div>
        <div class="idea-gap"><span style="width:${pct}%"></span></div>
        <div class="idea-gaptext">strength gap ${i.gap.toFixed(1)} / 10</div>
      </div>`;
  }).join('') || '<p class="loading">No data.</p>';
}

function initIdeasToggle() {
  const bar = document.getElementById('ideas-tf');
  if (!bar) return;
  bar.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-tf]');
    if (!btn) return;
    ideasTf = btn.dataset.tf;
    bar.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
    if (lastMatrix) renderIdeas(lastMatrix);
  });
}

// ── intraday line chart (single, full-width, Today / Previous-day toggle) ──
let intraData = null;      // stashed intraday block for toggle + theme rebuilds

function chartOpts() {
  const cs = getComputedStyle(document.body);
  const tick = cs.getPropertyValue('--chart-tick').trim() || '#5b6884';
  const grid = cs.getPropertyValue('--chart-grid').trim() || 'rgba(30,39,64,.5)';
  const legend = cs.getPropertyValue('--muted').trim() || '#8a97b1';
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { color: legend, boxWidth: 10, boxHeight: 10, font: { size: 11 } } },
      tooltip: {
        callbacks: {
          label: (c) => `${c.dataset.label}: ${c.parsed.y >= 0 ? '+' : ''}${c.parsed.y.toFixed(2)}%`,
        },
      },
    },
    scales: {
      x: { ticks: { color: tick, maxTicksLimit: 12, font: { size: 10 } }, grid: { color: grid } },
      y: { ticks: { color: tick, font: { size: 10 }, callback: (v) => v + '%' }, grid: { color: grid } },
    },
  };
}

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

function drawChart() {
  if (!intraData || typeof Chart === 'undefined') return;
  const day = intraData[chartDay];
  const label = document.getElementById('chart-day-label');
  const dateEl = document.getElementById('chart-date');
  if (label) label.textContent = chartDay === 'today' ? 'Today' : 'Previous day';
  const el = document.getElementById('chart-main');
  if (!el) return;
  if (!day) {                              // e.g. no previous day yet
    if (chartMain) { chartMain.destroy(); chartMain = null; }
    if (dateEl) dateEl.textContent = '(no data)';
    return;
  }
  if (dateEl) dateEl.textContent = day.date + ' UTC';
  const ds = datasets(day.lines);
  if (chartMain) {                         // update in place, keep legend toggles
    chartMain.data.labels = day.times;
    const byLabel = Object.fromEntries(ds.map((d) => [d.label, d.data]));
    chartMain.data.datasets.forEach((d) => { d.data = byLabel[d.label] || []; });
    chartMain.update('none');
  } else {
    chartMain = new Chart(el, { type: 'line', data: { labels: day.times, datasets: ds }, options: chartOpts() });
  }
}

function renderCharts(intra) {
  if (!intra) return;
  intraData = intra;
  drawChart();
}

async function load() {
  try {
    const r = await fetch(DATA_URL + '?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const matrix = await r.json();
    lastMatrix = matrix;
    render(matrix);
    renderRisk(matrix);
    renderIdeas(matrix);
    renderCharts(matrix.timeframes.intraday);
  } catch (e) {
    document.getElementById('grid').innerHTML =
      `<p class="loading">Couldn't load strength data (${e.message}). Retrying…</p>`;
  }
}

// Plausible custom-event helper (safe if the script is blocked/not loaded).
function track(event, props) {
  try { if (window.plausible) window.plausible(event, props ? { props } : undefined); } catch (e) { /* ignore */ }
}

// Email capture → ESP. Set SUBSCRIBE_ENDPOINT to the ESP's subscribe URL once the
// list is created (MailerLite/Beehiiv/Kit). Until then the form still validates,
// fires the Plausible "Signup" goal (so we measure intent + source immediately),
// and acknowledges — the real POST turns on the moment the endpoint is filled.
// Brevo subscription form endpoint (from the form's embed). The site's own styled
// form posts here directly; the response is opaque (no-cors), so we verify the
// contact lands via Brevo Contacts. 'email_address_check' is Brevo's honeypot (stays empty).
const SUBSCRIBE_ENDPOINT = 'https://95e1cb32.sibforms.com/serve/MUIFAIKhyQh6CGkKVNSeY3PosPVQD4EVB-LtNRAK6boe5Ftk9MfOVfqm8jCWu3t7Vr6jgB3f5szihJ4r_0drvErPkuxB-uBanxXUJqsebdxRjpqi-AM3eH-VtDQaKSWbsWQ54ntlFxGz9vd3mItlg_naooEP1Dfz1PSdgaDhyVoGYkxqmzzpUVlVhE02yNKtBiplU09v5l7Lnq6J8w==';

function initCapture() {
  const form = document.getElementById('capture-form');
  const note = document.getElementById('capture-note');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const email = document.getElementById('capture-email').value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
      note.textContent = 'Please enter a valid email.';
      return;
    }
    note.textContent = 'Adding you…';
    if (SUBSCRIBE_ENDPOINT) {
      try {
        const fd = new FormData();
        fd.append('EMAIL', email);
        fd.append('email_address_check', '');   // Brevo honeypot — must stay empty
        fd.append('locale', 'en');
        await fetch(SUBSCRIBE_ENDPOINT, { method: 'POST', mode: 'no-cors', body: fd });
      } catch (e) { /* opaque response in no-cors; treat as sent */ }
    }
    track('Signup');
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

function initChartToggle() {
  const bar = document.getElementById('chart-toggle');
  if (!bar) return;
  bar.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-day]');
    if (!btn) return;
    chartDay = btn.dataset.day;
    bar.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
    drawChart();
  });
}

// ── light / dark theme (persisted) ──────────────────────────────────────
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('fxs_theme', t); } catch (e) { /* private mode */ }
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = t === 'light' ? '☀' : '☾';
}

function initTheme() {
  let saved = 'dark';
  try { saved = localStorage.getItem('fxs_theme') || 'dark'; } catch (e) { /* ignore */ }
  applyTheme(saved);
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    applyTheme(next);
    if (chartMain) { chartMain.destroy(); chartMain = null; }  // rebuild with themed axis colours
    drawChart();
  });
}

initTheme();
load();
initCapture();
initRefresh();
initIdeasToggle();
initChartToggle();
setInterval(load, REFRESH_MS);
