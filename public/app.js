// StrengthGrid front-end. Loads the static matrix.json (built by the worker and
// served from the CDN) and renders the multi-timeframe strength grid. No server,
// no framework — just fetch + render, re-polled while the tab is open.

const REFRESH_MS = 60_000;
const CCY_NAME = {
  USD: 'US Dollar', EUR: 'Euro', JPY: 'Yen', GBP: 'Pound', AUD: 'Aussie',
  CHF: 'Franc', CAD: 'Loonie', NZD: 'Kiwi', XAU: 'Gold', XAG: 'Silver',
};
const ARROWS = { up: '▲', down: '▼', flat: '—' };

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

async function load() {
  try {
    const r = await fetch('data/matrix.json?t=' + Date.now(), { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    render(await r.json());
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

load();
initCapture();
setInterval(load, REFRESH_MS);
