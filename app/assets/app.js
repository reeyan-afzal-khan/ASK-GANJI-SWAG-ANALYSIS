/* Ask Ganji Swag analytics app. Plain JavaScript, no dependencies.
   Aggregates come from data/summary.js and subtitles from data/transcripts/, both built by
   bash app/run.sh. Data files load as scripts, so the app works from disk or any static host;
   the built-in YouTube player needs the page to be served over http(s). */
(() => {
'use strict';

const DATA = window.GANJI_DATA;
const main = document.getElementById('main');
if (!DATA) {
  main.innerHTML = '<p class="notice"><strong>No app data.</strong> Run <code>bash app/run.sh</code> to build <code>app/data/</code>.</p>';
  return;
}

/* ---------- Small helpers ---------- */
const sum = values => values.reduce((a, b) => a + b, 0);
const mean = values => values.length ? sum(values) / values.length : null;
function median(values) {
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
function countBy(items, key) {
  const counts = new Map();
  for (const item of items) {
    const k = key(item);
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return counts;
}
const r2 = v => Math.round(v * 100) / 100;
const shorten = (text, max) => text.length > max ? `${text.slice(0, max - 1)}…` : text;
// Whole words on as many lines as they need, each line at most max characters where the words allow.
function wrapWords(text, max) {
  const lines = [];
  for (const word of text.split(' ')) {
    if (lines.length && `${lines[lines.length - 1]} ${word}`.length <= max) lines[lines.length - 1] += ` ${word}`;
    else lines.push(word);
  }
  return lines;
}
function debounce(fn, wait) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

/* ---------- Data preparation ---------- */
const TABS = ['overview', 'categories', 'questions', 'insights', 'episodes', 'episode', 'about'];
const FILTER_TABS = new Set(['overview', 'categories', 'questions', 'insights', 'episodes']);
const CATEGORIES = DATA.categories;
const CAT = new Map(CATEGORIES.map(c => [c.id, c]));
const SUB = new Map();
for (const c of CATEGORIES) for (const sub of c.subcategories) SUB.set(sub.id, { ...sub, cat: c.id });
const PLACES = DATA.places;
const CITIES = DATA.cities || [];
const EPISODES = DATA.episodes.slice().sort((a, b) => a.n - b.n);
const BY_EP = new Map(EPISODES.map(e => [e.n, e]));
const QUESTIONS = DATA.questions;
const VOCAB = DATA.vocabulary;
const VOCAB_LANG = DATA.vocabularyLanguage;
const AVG = 10;
const catOf = code => code.split('.')[0];
const catName = id => (CAT.get(id) || { name: id }).name;
const subName = code => (SUB.get(code) || { name: code }).name;

for (const q of QUESTIONS) {
  q.cat = CAT.has(catOf(q.sub)) ? catOf(q.sub) : 'other';
  q.catName = catName(q.cat);
  q.subName = subName(q.sub);
  q.alsoCats = [...new Set(q.also.map(catOf))].filter(c => c !== q.cat && CAT.has(c));
  q.cities = q.cities || [];
}
const QS_BY_EP = new Map();
for (const q of QUESTIONS) {
  if (!QS_BY_EP.has(q.ep)) QS_BY_EP.set(q.ep, []);
  QS_BY_EP.get(q.ep).push(q);
}
for (const e of EPISODES) {
  const qs = (QS_BY_EP.get(e.n) || []).sort((a, b) => a.order - b.order);
  const lengths = qs.map(q => q.length).filter(v => v != null);
  e.qs = qs;
  e.lengthMin = e.duration / 60;
  e.pace = e.speech > 0 ? e.words / (e.speech / 60) : null;
  e.englishShare = e.english != null && e.words ? e.english / e.words : null;
  e.laughs = e.events.laughter || 0;
  e.laughRate = e.duration ? e.laughs / (e.duration / 3600) : null;
  e.intro = e.firstQuestion != null ? e.firstQuestion / 60 : null;
  e.perQuestion = lengths.length ? mean(lengths) / 60 : null;
  e.topList = [];
  for (let i = 0; i < e.top.length; i += 2) e.topList.push([e.top[i], e.top[i + 1]]);
}

/* Colours follow each category's overall size and never change with filters: the eight series hues
   first, then greys. In part-to-whole charts a category's subcategories alternate two ladders of
   lighter tints of its hue (largest first, in the full hue), so neighbours stay apart and still read
   as one family without turning dark. */
const CAT_COUNTS = countBy(QUESTIONS, q => q.cat);
const SUB_COUNTS = countBy(QUESTIONS, q => q.sub);
const CAT_ORDER = CATEGORIES.slice().sort((a, b) => (a.id === 'other') - (b.id === 'other') || (CAT_COUNTS.get(b.id) || 0) - (CAT_COUNTS.get(a.id) || 0));
const SLOTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'tail-1', 'tail-2', 'tail-3'];
const spread = (count, lo, hi, k) => count > 1 ? lo + (hi - lo) * k / (count - 1) : (lo + hi) / 2;
CAT_ORDER.forEach((c, i) => {
  c.color = `var(--${SLOTS[Math.min(i, SLOTS.length - 1)]})`;
  c.subs = c.subcategories.map(sb => SUB.get(sb.id)).filter(sb => SUB_COUNTS.get(sb.id))
    .sort((a, b) => SUB_COUNTS.get(b.id) - SUB_COUNTS.get(a.id));
  const pale = Math.ceil((c.subs.length - 1) / 2), soft = Math.floor((c.subs.length - 1) / 2);
  c.subs.forEach((sb, j) => {
    sb.color = c.color;
    sb.tone = j === 0 ? c.color
      : j % 2 ? `color-mix(in oklab, ${c.color} ${Math.round(spread(pale, 58, 34, (j - 1) / 2))}%, var(--surface))`
      : `color-mix(in oklab, ${c.color} ${Math.round(spread(soft, 82, 66, j / 2 - 1))}%, var(--surface))`;
  });
});
const LIVE_CATS = CAT_ORDER.filter(c => CAT_COUNTS.get(c.id));
const TOPICS = LIVE_CATS.filter(c => c.id !== 'other');
const SUBTOPIC_COUNT = sum(TOPICS.map(c => c.subs.length));
const colorOf = key => (CAT.get(key) || SUB.get(key) || {}).color || 'var(--acc)';
const catStyle = key => `--cat:${colorOf(key)}`;

/* ---------- State and URL hash ---------- */
const SORTS = {
  episode: { label: 'Episode order', compare: (a, b) => a.ep - b.ep || a.order - b.order },
  newest: { label: 'Newest first', compare: (a, b) => b.ep - a.ep || a.order - b.order },
  longest: { label: 'Longest answer', compare: (a, b) => (b.length ?? -1) - (a.length ?? -1) },
  shortest: { label: 'Shortest answer', compare: (a, b) => (a.length ?? Infinity) - (b.length ?? Infinity) },
  title: { label: 'Title A–Z', compare: (a, b) => a.title.localeCompare(b.title) },
};
const state = {
  tab: 'overview', cat: '', sub: '', sort: 'episode', openings: true, share: true,
  ep: EPISODES[EPISODES.length - 1].n, focus: 0, t: null, play: false, script: 'roman',
};
// The transcript's language (Roman Urdu or English) carries over between visits.
try {
  const saved = localStorage.getItem('ganji-script');
  if ((DATA.meta.scripts || []).includes(saved)) state.script = saved;
} catch (error) { /* storage unavailable */ }
let lastHash = '';

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  let tab = p.get('tab');
  // Links to the old search tab land on the question list instead.
  if (tab === 'search') tab = 'questions';
  state.tab = TABS.includes(tab) ? tab : 'overview';
  state.sub = SUB.has(p.get('sub')) ? p.get('sub') : '';
  state.cat = CAT.has(p.get('cat')) ? p.get('cat') : (state.sub ? SUB.get(state.sub).cat : '');
  if (state.sub && SUB.get(state.sub).cat !== state.cat) state.sub = '';
  state.sort = SORTS[p.get('sort')] ? p.get('sort') : 'episode';
  state.ep = BY_EP.has(Number(p.get('ep'))) ? Number(p.get('ep')) : state.ep;
  const t = Number(p.get('t'));
  state.t = p.has('t') && Number.isFinite(t) && t >= 0 ? t : null;
  if ((DATA.meta.scripts || []).includes(p.get('script'))) state.script = p.get('script');
  state.focus = 0;
  state.play = false;
}
function writeHash(push = false) {
  const p = new URLSearchParams({ tab: state.tab });
  if (FILTER_TABS.has(state.tab)) { if (state.cat) p.set('cat', state.cat); if (state.sub) p.set('sub', state.sub); }
  if (state.tab === 'questions' && state.sort !== 'episode') p.set('sort', state.sort);
  if (state.tab === 'episode') { p.set('ep', state.ep); if (state.t) p.set('t', Math.floor(state.t)); if (state.script !== 'roman') p.set('script', state.script); }
  const hash = `#${p}`;
  if (location.hash !== hash) history[push ? 'pushState' : 'replaceState'](null, '', hash);
  lastHash = location.hash;
}
const inScope = q => (!state.cat || q.cat === state.cat) && (!state.sub || q.sub === state.sub);
const scopedQuestions = () => QUESTIONS.filter(inScope);
const scopeName = () => state.sub ? subName(state.sub) : state.cat ? catName(state.cat) : '';
// A question's opening follows the transcript language: the English translation when chosen and there.
const excerptOf = q => state.script === 'english' && q.excerptEn ? q.excerptEn : q.excerpt;
function setScript(script) {
  state.script = script;
  try { localStorage.setItem('ganji-script', script); } catch (error) { /* storage unavailable */ }
}

/* ---------- DOM helpers ---------- */
function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}
function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') el.style.cssText = value;
    else if (key === 'on') for (const [type, fn] of Object.entries(value)) el.addEventListener(type, fn);
    else el.setAttribute(key, value === true ? '' : value);
  }
  return append(el, children);
}
const SVG_NS = 'http://www.w3.org/2000/svg';
function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) if (value != null) el.setAttribute(key, value);
  return append(el, children);
}
function icon(d) {
  return s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' }, s('path', { d }));
}
const strong = text => h('strong', { text });

/* ---------- Formatting ---------- */
const NF = new Intl.NumberFormat('en-US');
const pad2 = v => String(v).padStart(2, '0');
const fmtInt = v => v == null || !Number.isFinite(v) ? '–' : NF.format(Math.round(v));
const fmt1 = v => v == null || !Number.isFinite(v) ? '–' : v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmtPct = (v, digits = 0) => v == null || !Number.isFinite(v) ? '–' : `${(v * 100).toFixed(digits)}%`;
const fmtShare = v => fmtPct(v, v > 0 && v < 0.1 ? 1 : 0);
function fmtCompact(v) {
  if (v == null || !Number.isFinite(v)) return '–';
  const abs = Math.abs(v);
  const trim = x => String(Math.round(x * 10) / 10);
  if (abs >= 1e6) return `${trim(v / 1e6)}M`;
  if (abs >= 1e4) return `${trim(v / 1e3)}K`;
  if (abs < 10 && !Number.isInteger(v)) return trim(v);
  return fmtInt(v);
}
function fmtClock(seconds) {
  const t = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(t / 3600), minutes = Math.floor(t % 3600 / 60), secs = t % 60;
  return hours ? `${hours}:${pad2(minutes)}:${pad2(secs)}` : `${minutes}:${pad2(secs)}`;
}
function fmtDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '–';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${pad2(minutes % 60)} min`;
}
const fmtMinutes = v => v == null ? '–' : `${v < 10 ? fmt1(v) : fmtInt(v)} min`;
const fmtPoints = v => `${v >= 0 ? '+' : '−'}${fmt1(Math.abs(v))} pts`;
const plural = (n, word, many = word + 's') => `${fmtInt(n)} ${n === 1 ? word : many}`;

/* ---------- Navigation ---------- */
function navigate(changes, push = true) {
  Object.assign(state, changes);
  render(push);
}
function go(tab, changes = {}) {
  navigate({ ...changes, tab });
  window.scrollTo({ top: 0 });
  closeRail();
}
const setFilter = (cat, sub = '') => navigate({ cat, sub });
// The sidebar tree filters the current tab when it can, and opens the category page otherwise.
const pickCategory = (cat, sub = '') => go(FILTER_TABS.has(state.tab) ? state.tab : 'categories', { cat, sub });
function openEpisode(n, { order = 0, t = null, play = false } = {}) {
  go('episode', { ep: n, focus: order, t, play });
}
const openQuestion = q => openEpisode(q.ep, { order: q.order, t: q.start, play: true });

function watchUrl(ep, t) {
  const e = BY_EP.get(ep);
  if (!e || !e.video) return null;
  return `https://www.youtube.com/watch?v=${encodeURIComponent(e.video)}${t != null ? `&t=${Math.max(0, Math.floor(t))}s` : ''}`;
}
function youtubeLink(ep, t, label, cls = 'yt-link') {
  const url = watchUrl(ep, t);
  return url ? h('a', { href: url, target: '_blank', rel: 'noopener', class: cls, title: 'Watch on YouTube' }, label) : null;
}
function episodeLink(n, label = `Episode ${n}`) {
  return h('a', { href: `#tab=episode&ep=${n}`, on: { click: ev => { ev.preventDefault(); openEpisode(n); } } }, label);
}
function playButton(q) {
  return h('button', { class: 'q-play', type: 'button', title: 'Play this answer with its transcript',
    text: q.start == null ? '▶ Episode' : `▶ ${fmtClock(q.start)}`, on: { click: () => openQuestion(q) } });
}
function subTag(q) {
  return h('a', { class: 'tag primary', href: `#tab=questions&cat=${q.cat}&sub=${q.sub}`, style: catStyle(q.cat), title: (SUB.get(q.sub) || {}).description || '',
    on: { click: ev => { ev.preventDefault(); go('questions', { cat: q.cat, sub: q.sub }); } } },
  h('span', { class: 'dot' }), `${q.catName} › ${q.subName}`);
}

/* ---------- Tooltip ---------- */
const tooltip = document.getElementById('tooltip');
function showTip(point, title, rows = [], notes = null) {
  tooltip.replaceChildren();
  if (title) tooltip.append(h('div', { class: 'tt-title', text: title }));
  for (const row of rows) {
    if (!row) continue;
    tooltip.append(h('div', { class: 'tt-row' },
      row.color ? h('span', { class: 'tt-key', style: `background:${row.color};opacity:${row.shade || 1}` }) : null,
      h('strong', { text: row.value }),
      row.label ? h('span', { text: row.label }) : null));
  }
  for (const note of [].concat(notes || [])) if (note) tooltip.append(h('div', { class: 'tt-note', text: note }));
  tooltip.hidden = false;
  const pad = 14, box = tooltip.getBoundingClientRect();
  let x = point.clientX + pad, y = point.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = point.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = point.clientY - box.height - pad;
  tooltip.style.left = `${Math.max(8, x)}px`;
  tooltip.style.top = `${Math.max(8, y)}px`;
}
function pointOf(el) {
  const box = el.getBoundingClientRect();
  return { clientX: box.left + Math.min(box.width / 2, 120), clientY: box.bottom - 4 };
}
function hideTip() { tooltip.hidden = true; }
function attachTip(el, content) {
  el.addEventListener('pointermove', ev => showTip(ev, ...content()));
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', () => showTip(pointOf(el), ...content()));
  el.addEventListener('blur', hideTip);
}

/* ---------- Chart registry: charts redraw on width changes ---------- */
let activeCharts = [];
const hoverBus = new Set();
function registerChart(draw, fill = null) {
  activeCharts.push(draw);
  let height = null;
  // Charts measure their container, so draw after the current render has attached the card.
  queueMicrotask(() => {
    if (!activeCharts.includes(draw)) return;
    if (fill) height = Math.round(fill.clientHeight);
    draw();
  });
  // A chart that fills its card redraws when the card's height changes, as when the cards beside it grow.
  if (fill) {
    const watch = new ResizeObserver(([entry]) => {
      if (!activeCharts.includes(draw)) { watch.disconnect(); return; }
      const next = Math.round(entry.contentRect.height);
      if (height !== null && Math.abs(next - height) > 1) { height = next; draw(); }
    });
    watch.observe(fill);
  }
}
// The chart takes whatever height its card has to spare in its row, and at least its natural height.
function fillCard(container, natural) {
  container.classList.add('fill');
  container.style.setProperty('--fill-min', `${natural}px`);
  return () => Math.max(natural, Math.floor(container.clientHeight));
}
let lastWidth = 0;
const redraw = debounce(() => activeCharts.forEach(draw => draw()), 120);
new ResizeObserver(entries => {
  const width = Math.round(entries[0].contentRect.width);
  if (width !== lastWidth) { lastWidth = width; redraw(); }
}).observe(main);

/* ---------- Building blocks ---------- */
function card({ title, subtitle, table, legend, span = 'span-12', cls = '' }) {
  const body = h('div', { class: 'chart' });
  const tableBox = h('div', { class: 'table-wrap', hidden: true });
  const actions = h('div', { class: 'card-actions' });
  const el = h('section', { class: `card ${span} ${cls}`.trim() },
    h('div', { class: 'card-head' },
      h('div', { class: 'card-titles' }, h('h3', { text: title }), subtitle ? h('p', { class: 'subtitle', text: subtitle }) : null),
      actions),
    legend || null, body, tableBox);
  if (table) {
    const button = h('button', { class: 'small-button', type: 'button', 'aria-pressed': 'false', text: 'Table' });
    button.addEventListener('click', () => {
      const on = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', String(on));
      button.textContent = on ? 'Chart' : 'Table';
      body.hidden = on;
      if (legend) legend.hidden = on;
      tableBox.hidden = !on;
      if (on) tableBox.replaceChildren(simpleTable(table()));
    });
    actions.append(button);
  }
  return { el, body, actions };
}
function simpleTable({ columns, rows }) {
  return h('table', {},
    h('thead', {}, h('tr', {}, columns.map(c => h('th', { class: c.num ? 'num' : null, scope: 'col', text: c.label })))),
    h('tbody', {}, rows.map(row => h('tr', {}, row.map((cell, i) => h('td', { class: columns[i].num ? 'num' : null }, cell))))));
}
function kpi(label, value, sub) {
  const wordy = /[a-z]{3}/i.test(value) && value.length > 9;
  return h('div', { class: 'kpi' },
    h('div', { class: 'kpi-label', text: label }),
    h('div', { class: wordy ? 'kpi-value text' : 'kpi-value', text: value, title: value }),
    sub ? h('div', { class: 'kpi-sub', text: sub }) : null);
}
function notice(...children) { return h('p', { class: 'notice span-12' }, ...children); }
function legendBar(color) {
  return h('div', { class: 'legend' },
    h('span', {}, h('span', { class: 'key-rect', style: color ? `background:${color};opacity:.42` : null }), 'Per episode'),
    h('span', {}, h('span', { class: 'key-line', style: color ? `background:${color}` : null }), `${AVG}-episode average`));
}
function seriesLegend(series) {
  return h('div', { class: 'legend' }, series.map(sr => h('span', {}, h('span', { class: 'swatch', style: `background:${sr.color};opacity:${sr.shade || 1}` }), sr.label)));
}
function chipButton(label, count, pressed, onClick, color) {
  return h('button', { class: 'chip', type: 'button', 'aria-pressed': String(pressed), style: color ? `--cat:${color}` : null, on: { click: onClick } },
    color ? h('span', { class: 'dot' }) : null, label, count == null ? null : h('span', { class: 'count', text: fmtInt(count) }));
}
function segmented(label, options, value, onChange) {
  const box = h('div', { class: 'segmented', role: 'group', 'aria-label': label });
  for (const [text, v] of options) {
    box.append(h('button', { type: 'button', 'aria-pressed': String(v === value), text, on: { click: () => {
      for (const b of box.children) b.setAttribute('aria-pressed', String(b.textContent === text));
      onChange(v);
    } } }));
  }
  return box;
}
const itemsTable = (label, items, format) => () => ({
  columns: [{ label }, { label: 'Value', num: true }],
  rows: items.map(it => [it.label, format(it.value)]),
});

/* ---------- Scales ---------- */
function niceTicks(max, count = 4) {
  if (!(max > 0)) return { max: 1, ticks: [0, 1] };
  const raw = max / count, mag = 10 ** Math.floor(Math.log10(raw)), norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const top = Math.ceil(max / step - 1e-9) * step;
  const ticks = [];
  for (let v = 0; v <= top + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
  return { max: top, ticks };
}
function episodeTicks(eps, step) {
  const every = [1, 2, 5, 10, 20, 25, 50, 100].find(k => k * step >= 36) || 100;
  const ticks = [];
  eps.forEach((e, i) => { if (e.n % every === 0) ticks.push(i); });
  return ticks.length ? ticks : [0];
}
function rolling(values, size) {
  const before = Math.floor(size / 2), after = size - before - 1;
  return values.map((_, i) => {
    let total = 0, count = 0;
    for (let j = i - before; j <= i + after; j++) {
      const v = values[j];
      if (v != null && Number.isFinite(v)) { total += v; count++; }
    }
    return count ? total / count : null;
  });
}
function columnPath(x, y, width, height, radius) {
  if (!(height > 0)) return '';
  const r = Math.min(radius, height, width / 2);
  if (r < 0.75) return `M${r2(x)},${r2(y + height)}V${r2(y)}H${r2(x + width)}V${r2(y + height)}Z`;
  return `M${r2(x)},${r2(y + height)}V${r2(y + r)}Q${r2(x)},${r2(y)} ${r2(x + r)},${r2(y)}H${r2(x + width - r)}Q${r2(x + width)},${r2(y)} ${r2(x + width)},${r2(y + r)}V${r2(y + height)}Z`;
}
function linePath(points) {
  let d = '', pen = false;
  for (const p of points) {
    if (!p) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${r2(p[0])},${r2(p[1])}`;
    pen = true;
  }
  return d;
}
function arcPath(c, r0, r1, a0, a1) {
  const pt = (r, a) => `${r2(c + r * Math.sin(a))},${r2(c - r * Math.cos(a))}`;
  if (a1 - a0 >= Math.PI * 2 - 1e-6) {
    return `M${pt(r1, 0)}A${r1},${r1} 0 1 1 ${pt(r1, Math.PI)}A${r1},${r1} 0 1 1 ${pt(r1, 0)}Z`
      + `M${pt(r0, 0)}A${r0},${r0} 0 1 0 ${pt(r0, Math.PI)}A${r0},${r0} 0 1 0 ${pt(r0, 0)}Z`;
  }
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M${pt(r1, a0)}A${r1},${r1} 0 ${large} 1 ${pt(r1, a1)}L${pt(r0, a1)}A${r0},${r0} 0 ${large} 0 ${pt(r0, a0)}Z`;
}
function eras(eps, count = 10) {
  const size = Math.max(1, Math.ceil(eps.length / count));
  const out = [];
  for (let i = 0; i < eps.length; i += size) {
    const chunk = eps.slice(i, i + size);
    out.push({ key: i, label: chunk.length > 1 ? `${chunk[0].n}–${chunk[chunk.length - 1].n}` : `${chunk[0].n}`, from: chunk[0].n, to: chunk[chunk.length - 1].n });
  }
  return out;
}

/* ---------- Sunburst: categories inside, their subcategories outside; click to zoom ---------- */
let glows = 0;
function sunburst(container, { cat, sub, onPick, onBack }) {
  const glow = `sunburst-glow-${++glows}`;
  const focus = cat ? CAT.get(cat) : null;
  const qs = focus ? QUESTIONS.filter(q => q.cat === cat) : QUESTIONS;
  const total = qs.length;
  const subCounts = countBy(qs, q => q.sub);
  const parents = focus ? [] : LIVE_CATS.map(c => ({ key: c.id, cat: c.id, label: c.name, value: CAT_COUNTS.get(c.id), color: c.color, shade: 1 }));
  const children = (focus ? [focus] : LIVE_CATS).flatMap(c => c.subs.filter(sb => subCounts.get(sb.id))
    .map(sb => ({ key: sb.id, cat: c.id, label: sb.name, value: subCounts.get(sb.id), color: sb.tone, shade: 1 })));
  const items = focus ? children : parents;
  const byKey = new Map([...parents, ...children].map(it => [it.key, it]));
  const selected = sub || null;
  const slices = new Map(), rows = new Map();
  let hovered = null, centre = () => {};

  // A category lights up with its subcategories, and a subcategory with its category.
  const related = (k, key) => k === key || catOf(k) === key || (CAT.has(k) && catOf(key) === k);
  function paint() {
    const key = hovered || selected;
    for (const [k, el] of slices) el.classList.toggle('faded', !!key && !related(k, key));
    for (const [k, el] of rows) el.classList.toggle('hot', k === hovered);
    centre(hovered);
  }
  function tip(it) {
    if (SUB.has(it.key)) {
      return [`${catName(it.cat)} › ${it.label}`, [
        { value: fmtInt(it.value), label: 'questions', color: it.color, shade: it.shade },
        { value: fmtShare(it.value / CAT_COUNTS.get(it.cat)), label: `of ${catName(it.cat)}` },
        { value: fmtShare(it.value / QUESTIONS.length), label: 'of all questions' }],
      [SUB.get(it.key).description, focus && selected === it.key ? 'Click to show the whole category' : 'Click to filter by this subcategory']];
    }
    const lead = CAT.get(it.key).subs[0];
    return [it.label, [
      { value: fmtInt(it.value), label: 'questions', color: it.color },
      { value: fmtShare(it.value / total), label: 'of all questions' },
      lead ? { value: fmtInt(SUB_COUNTS.get(lead.id)), label: `in the largest, ${lead.name}` } : null],
    [CAT.get(it.key).description, 'Click to zoom into this category']];
  }
  const pick = it => onPick(it.cat, SUB.has(it.key) ? (focus && selected === it.key ? '' : it.key) : '');
  const hover = key => { if (hovered !== key) { hovered = key; paint(); } };

  const chartBox = h('div', { class: 'donut-chart' });
  const legendBox = h('div', { class: 'donut-legend' },
    h('div', { class: 'legend-head', 'aria-hidden': 'true' }, h('span'), h('span', { text: focus ? 'Subcategory' : 'Category' }), h('span'),
      h('span', { class: 'num', text: 'Questions' }), h('span', { class: 'pct', text: 'Share' })));
  const largest = Math.max(1, ...items.map(it => it.value));
  for (const it of items) {
    const row = h('button', { class: 'legend-row', type: 'button', style: `--cat:${it.color}`, 'aria-pressed': String(selected === it.key) },
      h('span', { class: 'swatch', style: `opacity:${it.shade}` }),
      h('span', { class: 'name', text: it.label }),
      h('span', { class: 'share-track' }, h('span', { class: 'share-bar', style: `width:${r2(it.value / largest * 100)}%` })),
      h('span', { class: 'num', text: fmtInt(it.value) }),
      h('span', { class: 'pct', text: fmtShare(it.value / total) }));
    row.addEventListener('pointerenter', () => hover(it.key));
    row.addEventListener('pointerleave', () => hover(null));
    row.addEventListener('focus', () => hover(it.key));
    row.addEventListener('blur', () => hover(null));
    row.addEventListener('click', () => pick(it));
    rows.set(it.key, row);
    legendBox.append(row);
  }
  container.classList.add('donut-host');
  container.replaceChildren(h('div', { class: 'donut-wrap' }, chartBox, legendBox));

  function draw() {
    chartBox.replaceChildren();
    slices.clear();
    const S = Math.round(Math.max(240, Math.min(420, chartBox.clientWidth || 320)));
    const c = S / 2, TAU = Math.PI * 2;
    const svg = s('svg', { viewBox: `0 0 ${S} ${S}`, width: S, height: S, role: 'img',
      'aria-label': focus ? `${focus.name}: questions by subcategory` : 'Questions by category and subcategory' });
    // Translucent rings over a soft halo of their own colours.
    svg.append(s('defs', {}, s('filter', { id: glow, x: '-25%', y: '-25%', width: '150%', height: '150%', 'color-interpolation-filters': 'sRGB' },
      s('feGaussianBlur', { in: 'SourceGraphic', stdDeviation: r2(S * 0.03), result: 'blur' }),
      s('feComponentTransfer', { in: 'blur', result: 'halo' }, s('feFuncA', { type: 'linear', slope: 0.9 })),
      s('feMerge', {}, s('feMergeNode', { in: 'halo' }), s('feMergeNode', { in: 'SourceGraphic' })))));
    const rings = s('g', { class: 'rings', filter: `url(#${glow})` });
    svg.append(rings);
    const add = (it, r0, r1, a0, a1) => {
      const path = s('path', { class: 'slice', d: arcPath(c, r0, r1, a0, a1), 'fill-rule': 'evenodd', style: `fill:${it.color}` });
      path.addEventListener('pointermove', ev => { hover(it.key); showTip(ev, ...tip(it)); });
      path.addEventListener('pointerleave', () => { hover(null); hideTip(); });
      path.addEventListener('click', () => { hideTip(); pick(it); });
      rings.append(path);
      slices.set(it.key, path);
    };
    let a = 0;
    if (focus) {
      for (const it of children) { const a1 = a + it.value / total * TAU; add(it, S * 0.3, S * 0.48, a, a1); a = a1; }
    } else {
      for (const p of parents) {
        const a1 = a + p.value / total * TAU;
        add(p, S * 0.22, S * 0.345, a, a1);
        let b = a;
        for (const ch of children) {
          if (ch.cat !== p.key) continue;
          const b1 = b + ch.value / total * TAU;
          add(ch, S * 0.355, S * 0.48, b, b1);
          b = b1;
        }
        a = a1;
      }
    }
    const hole = (focus ? 0.3 : 0.22) * S;
    const g = s('g', { class: focus ? 'donut-centre donut-back' : 'donut-centre' });
    const num = s('text', { class: 'donut-center-number', x: c, 'text-anchor': 'middle' });
    const label = s('text', { class: 'donut-center-label', x: c, 'text-anchor': 'middle' });
    const note = s('text', { class: 'donut-center-note', x: c, 'text-anchor': 'middle' });
    g.append(s('circle', { class: 'centre-hit', cx: c, cy: c, r: r2(hole - 4) }), num, label, note);
    if (focus) {
      g.setAttribute('role', 'button');
      g.setAttribute('tabindex', '0');
      g.setAttribute('aria-label', 'Back to all categories');
      g.addEventListener('click', onBack);
      g.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onBack(); } });
    }
    svg.append(g);
    const fit = Math.max(10, Math.floor(hole * 2 / 7.4));
    // Long names take two lines in the centre rather than being cut short.
    function lines(text) {
      if (text.length <= fit) return [text];
      const words = text.split(' ');
      let first = '';
      while (words.length && `${first} ${words[0]}`.trim().length <= fit) first = `${first} ${words.shift()}`.trim();
      return first ? [first, shorten(words.join(' '), fit)] : [shorten(text, fit)];
    }
    function setCentre(value, name, detail) {
      const parts = lines(name), top = c - (parts.length > 1 ? 10 : 2);
      num.textContent = value;
      num.setAttribute('y', r2(top));
      label.replaceChildren(...parts.map((part, i) => s('tspan', { x: c, y: r2(top + 20 + i * 15) }, part)));
      note.textContent = detail;
      note.setAttribute('y', r2(top + 37 + (parts.length - 1) * 15));
    }
    centre = key => {
      const it = byKey.get(key || selected);
      if (it) {
        setCentre(fmtInt(it.value), it.label, SUB.has(it.key) ? `${fmtShare(it.value / CAT_COUNTS.get(it.cat))} of ${focus ? 'the category' : shorten(catName(it.cat), fit - 8)}` : `${fmtShare(it.value / total)} of all`);
      } else {
        setCentre(fmtInt(total), focus ? focus.name : 'questions', focus ? '↩ all categories' : `in ${TOPICS.length} categories`);
      }
    };
    chartBox.append(svg);
    paint();
  }
  registerChart(draw);
}

/* ---------- Stacked columns: each block of episodes split by subject ---------- */
function stackedColumns(container, { qs, series, groupOf, selected, onPick }) {
  let shareMode = state.share;
  const height = fillCard(container, 290);
  function draw() {
    container.replaceChildren();
    const W = Math.max(260, container.clientWidth), H = height();
    const columns = eras(EPISODES, W < 420 ? 5 : W < 600 ? 7 : 10);
    const cells = columns.map(col => {
      const list = qs.filter(q => q.ep >= col.from && q.ep <= col.to);
      return { col, total: list.length, counts: countBy(list, groupOf) };
    });
    const m = { t: 8, r: 4, b: 24, l: 40 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const scale = shareMode ? { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] } : niceTicks(Math.max(1, ...cells.map(cell => cell.total)), 4);
    const Y = v => m.t + ph - v / scale.max * ph;
    const step = pw / columns.length, bw = Math.min(64, step * 0.74);
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': 'Questions by subject in each block of episodes' });
    for (const t of scale.ticks) {
      svg.append(s('line', { class: t === 0 ? 'baseline' : 'gridline', x1: m.l, x2: W - m.r, y1: r2(Y(t)), y2: r2(Y(t)) }));
      svg.append(s('text', { class: 'tick', x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, shareMode ? fmtPct(t) : fmtCompact(t)));
    }
    const segs = [];
    const emphasise = key => segs.forEach(([k, el]) => el.classList.toggle('faded', !!key && k !== key));
    cells.forEach((cell, i) => {
      const x = m.l + i * step + (step - bw) / 2;
      let acc = 0;
      for (const sr of series) {
        const n = cell.counts.get(sr.key) || 0;
        if (!n) continue;
        const v = shareMode ? n / cell.total : n;
        const top = Y(acc + v), bottom = Y(acc);
        const rect = s('rect', { class: 'stack-seg', x: r2(x), y: r2(top), width: r2(bw), height: r2(Math.max(0.5, bottom - top)), style: `fill:${sr.color};fill-opacity:${sr.shade || 1}` });
        rect.addEventListener('pointermove', ev => {
          emphasise(sr.key);
          showTip(ev, `Episodes ${cell.col.label}`, [
            { value: fmtShare(n / cell.total), label: sr.label, color: sr.color, shade: sr.shade },
            { value: fmtInt(n), label: `of ${plural(cell.total, 'question')} in these episodes` }], onPick ? 'Click to filter by this subject' : null);
        });
        rect.addEventListener('pointerleave', () => { emphasise(selected); hideTip(); });
        if (onPick) rect.addEventListener('click', () => { hideTip(); onPick(sr.key); });
        segs.push([sr.key, rect]);
        svg.append(rect);
        acc += v;
      }
      svg.append(s('text', { class: 'tick', x: r2(x + bw / 2), y: H - 6, 'text-anchor': 'middle' }, cell.col.label));
    });
    container.append(svg);
    emphasise(selected);
  }
  registerChart(draw, container);
  return { setShare(on) { shareMode = on; draw(); } };
}

/* ---------- Episode column chart (columns + rolling average, crosshair, click to open) ---------- */
function episodeChart(container, cfg) {
  let setCross = null;
  const height = fillCard(container, cfg.height || 200);
  function draw() {
    if (setCross) hoverBus.delete(setCross);
    container.replaceChildren();
    const eps = cfg.episodes;
    const values = eps.map(e => { const v = cfg.value(e); return v == null || !Number.isFinite(v) ? null : v; });
    const defined = values.filter(v => v != null);
    if (!defined.length) { container.append(h('p', { class: 'muted', text: 'No data to show.' })); return; }
    const W = Math.max(260, container.clientWidth), H = height();
    const m = { t: 8, r: 6, b: 22, l: 42 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const { max, ticks } = niceTicks(Math.max(...defined), 4);
    const n = eps.length, step = pw / n;
    const gap = step >= 8 ? 2 : step >= 3 ? 1 : 0;
    const bw = Math.max(1, Math.min(24, step - gap));
    const X = i => m.l + i * step + step / 2;
    const Y = v => m.t + ph - (v / max) * ph;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `${cfg.label} by episode`,
      style: cfg.color ? `--series-fill:${cfg.color};--series-opacity:.42;--series-line:${cfg.color}` : null });
    for (const t of ticks) {
      svg.append(s('line', { class: t === 0 ? 'baseline' : 'gridline', x1: m.l, x2: W - m.r, y1: r2(Y(t)), y2: r2(Y(t)) }));
      svg.append(s('text', { class: 'tick', x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, (cfg.tick || fmtCompact)(t)));
    }
    for (const i of episodeTicks(eps, step)) svg.append(s('text', { class: 'tick', x: r2(X(i)), y: H - 5, 'text-anchor': 'middle' }, String(eps[i].n)));
    const columns = s('g');
    values.forEach((v, i) => { if (v > 0) columns.append(s('path', { class: 'col', d: columnPath(X(i) - bw / 2, Y(v), bw, Y(0) - Y(v), 4) })); });
    svg.append(columns);
    const average = n >= AVG ? rolling(values, AVG) : null;
    if (average) svg.append(s('path', { class: 'trend', d: linePath(average.map((v, i) => v == null ? null : [X(i), Y(v)])) }));
    const highlight = s('path', { class: 'col-hl', d: '' });
    const cross = s('line', { class: 'crosshair', x1: 0, x2: 0, y1: m.t, y2: m.t + ph, visibility: 'hidden' });
    const hit = s('rect', { class: cfg.onSelect ? 'hit-area clickable' : 'hit-area', x: m.l, y: m.t, width: pw, height: ph });
    svg.append(highlight, cross, hit);
    // While another chart on the page is hovered, this one shows its own figures for that episode beside its crosshair.
    const peek = h('div', { class: 'peek', hidden: true, 'aria-hidden': 'true' });
    container.append(svg, peek);

    const indexAt = ev => {
      const box = svg.getBoundingClientRect();
      const x = (ev.clientX - box.left) * (W / box.width);
      return Math.max(0, Math.min(n - 1, Math.floor((x - m.l) / step)));
    };
    const mark = i => {
      if (i == null || i < 0) { cross.setAttribute('visibility', 'hidden'); highlight.setAttribute('d', ''); return; }
      cross.setAttribute('x1', r2(X(i))); cross.setAttribute('x2', r2(X(i))); cross.setAttribute('visibility', 'visible');
      const v = values[i];
      highlight.setAttribute('d', v > 0 ? columnPath(X(i) - bw / 2, Y(v), bw, Y(0) - Y(v), 4) : '');
    };
    const colKey = cfg.color ? { color: cfg.color, shade: 0.42 } : { color: 'var(--acc-dim)' };
    const avgKey = { color: cfg.color || 'var(--acc-hi)' };
    const rowsAt = i => [{ value: values[i] == null ? '–' : cfg.format(values[i]), label: cfg.label, ...colKey }]
      .concat(average && average[i] != null ? [{ value: cfg.format(average[i]), label: `${AVG}-episode average`, ...avgKey }] : []);
    const showPeek = i => {
      if (i == null || i < 0) { peek.hidden = true; return; }
      peek.replaceChildren(h('div', { class: 'tt-title', text: `Episode ${eps[i].n}` }), ...rowsAt(i).map(row => h('div', { class: 'tt-row' },
        h('span', { class: 'tt-key', style: `background:${row.color};opacity:${row.shade || 1}` }), h('strong', { text: row.value }), h('span', { text: row.label }))));
      peek.hidden = false;
      // Beside the crosshair, on whichever side has room.
      const x = X(i), width = peek.offsetWidth;
      peek.style.left = `${Math.round(x + 10 + width <= W - m.r ? x + 10 : Math.max(0, x - 10 - width))}px`;
      peek.style.top = `${m.t}px`;
    };
    setCross = ep => {
      const i = ep == null ? null : eps.findIndex(e => e.n === ep);
      mark(i);
      showPeek(i);
    };
    hoverBus.add(setCross);
    const broadcast = ep => hoverBus.forEach(fn => { if (fn !== setCross) fn(ep); });
    hit.addEventListener('pointermove', ev => {
      const i = indexAt(ev), e = eps[i];
      mark(i);
      broadcast(e.n);
      showTip(ev, `Episode ${e.n}`, rowsAt(i).concat(cfg.extra ? cfg.extra(e) : []), cfg.onSelect ? 'Click to open this episode' : null);
    });
    hit.addEventListener('click', ev => { if (cfg.onSelect) { hideTip(); cfg.onSelect(eps[indexAt(ev)].n); } });
    hit.addEventListener('pointerleave', () => { mark(null); broadcast(null); hideTip(); });
  }
  registerChart(draw, container);
}
function episodeCard(eps, spec) {
  const table = () => ({
    columns: [{ label: 'Episode' }, { label: spec.label, num: true }],
    rows: eps.map(e => [String(e.n), spec.value(e) == null ? '–' : spec.format(spec.value(e))]),
  });
  const c = card({ title: spec.title, subtitle: spec.subtitle, table, legend: legendBar(spec.color), span: spec.span });
  episodeChart(c.body, {
    episodes: eps, value: spec.value, format: spec.format, label: spec.label, tick: spec.tick, extra: spec.extra,
    height: spec.height, color: spec.color, onSelect: n => openEpisode(n),
  });
  return c.el;
}

/* ---------- Horizontal bars ---------- */
function barList(container, { items, format, valueLabel, onSelect, selected }) {
  if (!items.length) { container.replaceChildren(h('p', { class: 'muted', text: 'Nothing to show for this selection.' })); return; }
  // An item's ref, when given, is a tick on the same scale: the value to compare the bar with.
  const max = Math.max(0, ...items.map(it => Math.max(it.value, it.ref || 0))) || 1;
  const box = h('div', { class: 'bars' });
  for (const it of items) {
    const classes = ['bar-row'];
    if (selected) classes.push(selected === it.key ? 'selected' : 'dimmed');
    const row = h(onSelect ? 'button' : 'div', {
      class: classes.join(' '), type: onSelect ? 'button' : null, style: it.color ? `--cat:${it.color}` : null,
      'aria-pressed': onSelect && selected ? String(selected === it.key) : null, tabindex: onSelect ? null : '0',
    },
    h('span', { class: 'bar-label', title: it.label }, h('span', { class: 'bar-text', text: it.label }), it.lang ? h('span', { class: 'lang', text: it.lang }) : null),
    h('span', { class: 'bar-track' }, h('span', { class: 'bar-fill', style: `width:${(Math.max(0, it.value) / max * 100).toFixed(2)}%` }),
      it.ref != null ? h('span', { class: 'bar-ref', style: `left:${(it.ref / max * 100).toFixed(2)}%` }) : null),
    h('span', { class: 'bar-value', text: format(it.value) }));
    attachTip(row, () => [it.title || it.label, [{ value: format(it.value), label: valueLabel, color: it.color }].concat(it.rows || []), it.note]);
    if (onSelect) row.addEventListener('click', () => { hideTip(); onSelect(it.key); });
    box.append(row);
  }
  container.replaceChildren(box);
}

/* ---------- Ranges: the middle half of each group's values, with the median, on one shared scale ---------- */
function quantile(sorted, p) {
  if (!sorted.length) return null;
  const at = (sorted.length - 1) * p, low = Math.floor(at);
  return sorted[low] + (sorted[Math.min(low + 1, sorted.length - 1)] - sorted[low]) * (at - low);
}
function rangeList(container, { items }) {
  if (!items.length) { container.replaceChildren(h('p', { class: 'muted', text: 'Not enough stated ages for this selection.' })); return; }
  const lo = Math.floor(Math.min(...items.map(it => it.low)) / 5) * 5, hi = Math.max(lo + 5, Math.ceil(Math.max(...items.map(it => it.high)) / 5) * 5);
  const at = v => ((v - lo) / (hi - lo) * 100).toFixed(2);
  const box = h('div', { class: 'bars ranges' });
  for (const it of items) {
    const row = h('div', { class: 'bar-row', tabindex: '0', style: `--cat:${it.color}` },
      h('span', { class: 'bar-label', title: it.label }, h('span', { class: 'bar-text', text: it.label })),
      h('span', { class: 'range-track' },
        h('span', { class: 'range-band', style: `left:${at(it.low)}%;width:${(at(it.high) - at(it.low)).toFixed(2)}%` }),
        h('span', { class: 'range-median', style: `left:${at(it.median)}%` })),
      h('span', { class: 'bar-value' }, h('span', { class: 'range-span', text: `${fmtInt(it.low)}–${fmtInt(it.high)}` }), fmtInt(it.median)));
    attachTip(row, () => [it.label, [
      { value: fmtInt(it.median), label: 'median age', color: it.color },
      { value: `${fmtInt(it.low)}–${fmtInt(it.high)}`, label: 'the middle half of stated ages' },
      { value: fmtInt(it.n), label: 'stated ages' }]]);
    box.append(row);
  }
  // The shared age scale, under the last row.
  const ticks = [];
  for (let t = lo; t <= hi; t += 5) ticks.push(t);
  box.append(h('div', { class: 'range-axis', 'aria-hidden': 'true' }, ticks.map(t => h('span', { style: `left:${at(t)}%`, text: String(t) }))));
  container.replaceChildren(box);
}

/* ---------- Diverging bars: change in share between the first and second half of all episodes ---------- */
function divergingBars(container, { items, onSelect }) {
  if (!items.length) { container.replaceChildren(h('p', { class: 'muted', text: 'Not enough questions to compare.' })); return; }
  const max = Math.max(0.5, ...items.map(it => Math.abs(it.value)));
  const box = h('div', { class: 'diverge' });
  for (const it of items) {
    const row = h(onSelect ? 'button' : 'div', { class: 'div-row', type: onSelect ? 'button' : null, tabindex: onSelect ? null : '0' },
      h('span', { class: 'bar-label', title: it.label }, h('span', { class: 'bar-text', text: it.label })),
      h('span', { class: 'div-track' }, h('span', { class: `div-bar ${it.value >= 0 ? 'up' : 'down'}`, style: `width:${(Math.abs(it.value) / max * 50).toFixed(2)}%` })),
      h('span', { class: 'div-value', text: fmtPoints(it.value) }));
    attachTip(row, () => [it.label, [{ value: fmtPoints(it.value), label: 'change in share of questions', color: it.value >= 0 ? 'var(--rise)' : 'var(--fall)' }, { value: it.note, label: '' }]]);
    if (onSelect) row.addEventListener('click', () => { hideTip(); onSelect(it.key); });
    box.append(row);
  }
  container.replaceChildren(box);
}
function divergingLegend(first, second) {
  return h('div', { class: 'legend' },
    h('span', {}, h('span', { class: 'key-rect', style: 'background:var(--rise)' }), `Bigger share in ${second}`),
    h('span', {}, h('span', { class: 'key-rect', style: 'background:var(--fall)' }), `Smaller share than in ${first}`));
}

/* ---------- Heatmap ---------- */
function heatmap(container, { rows, cols, cell, title }) {
  const grid = h('div', { class: 'heatmap', style: `grid-template-columns:minmax(150px,max-content) repeat(${cols.length},minmax(46px,1fr))`, role: 'group', 'aria-label': title });
  grid.append(h('div'));
  for (const c of cols) grid.append(h('div', { class: 'heat-head', text: c.label }));
  const values = rows.flatMap(r => cols.map(c => cell(r, c).share));
  const max = Math.max(0, ...values) || 1;
  for (const r of rows) {
    grid.append(h('div', { class: 'heat-label', title: r.label, text: r.label }));
    for (const c of cols) {
      const v = cell(r, c);
      const step = v.count ? 1 + Math.min(6, Math.floor(v.share / max * 7)) : 0;
      const el = h('div', { class: `heat-cell s${step}`, tabindex: '0', text: v.count ? fmtPct(v.share) : '', 'aria-label': `${r.label}, episodes ${c.label}: ${fmtPct(v.share, 1)}` });
      attachTip(el, () => [`${r.label} · episodes ${c.label}`, [
        { value: fmtPct(v.share, 1), label: 'of the questions in these episodes' },
        { value: fmtInt(v.count), label: `of ${plural(v.total, 'question')}` }]]);
      grid.append(el);
    }
  }
  const scale = h('div', { class: 'scale' }, h('span', { text: '0%' }),
    h('span', { class: 'scale-steps' }, [1, 2, 3, 4, 5, 6, 7].map(i => h('span', { style: `background:var(--seq-${i})` }))),
    h('span', { text: fmtPct(max) }));
  container.replaceChildren(grid, scale);
}

/* ---------- Sankey: groups of questions flowing from one set of subjects (left) to another (right) ----------
   Nodes are { key, label, color, note, hint, onPick, pinned }; links { from, to, value, color, questions }. Left nodes
   keep their order; right nodes sit by the average height of the questions reaching them, pinned ones last. A band
   with its questions lists them under the chart when clicked; openFlow(from, to) does the same from elsewhere. */
function sankey(container, { left, right, links, heads, selected = null, label }) {
  const byKey = new Map([...left, ...right].map(n => [n.key, { ...n, value: 0, out: [], in: [] }]));
  const flows = links.filter(l => l.value > 0 && byKey.has(l.from) && byKey.has(l.to))
    .map(l => ({ ...l, source: byKey.get(l.from), target: byKey.get(l.to) }));
  if (!flows.length) { container.replaceChildren(h('p', { class: 'muted', text: 'No questions to show for this selection.' })); return { openFlow() {} }; }
  for (const f of flows) { f.source.value += f.value; f.target.value += f.value; f.source.out.push(f); f.target.in.push(f); }
  const lefts = left.map(n => byKey.get(n.key)).filter(n => n.value);
  const rights = right.map(n => byKey.get(n.key)).filter(n => n.value);
  const total = sum(flows.map(f => f.value));
  const questions = n => (n === 1 ? 'question' : 'questions');
  const bands = [], marks = new Map();
  let hovered = null, chosen = null;

  // The chosen band's questions, under the chart; the band stays lit until the list is closed.
  const detail = h('div', { class: 'flow-detail', hidden: true });
  container.after(detail);
  function openFlow(f) {
    if (!f || !f.questions) return;
    if (chosen === f) { closeFlow(); return; }
    chosen = f;
    const list = f.questions.slice().sort(SORTS.newest.compare), box = h('div');
    detail.replaceChildren(h('div', { class: 'flow-head' },
      h('div', {},
        h('h4', {}, h('span', { class: 'dot', style: `--cat:${f.source.color}` }), f.source.label, h('span', { class: 'flow-arrow', text: '→' }),
          h('span', { class: 'dot', style: `--cat:${f.target.color}` }), f.target.label),
        h('p', { class: 'subtitle', text: `${plural(list.length, 'question')} · newest first · click one to play its answer` })),
      h('button', { class: 'small-button', type: 'button', text: 'Close', on: { click: closeFlow } })), box);
    questionList(box, list, 6);
    detail.hidden = false;
    paint();
    detail.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function closeFlow() {
    chosen = null;
    detail.hidden = true;
    detail.replaceChildren();
    paint();
  }

  // A node lights up with its own bands and the nodes at their other ends; a band with its two nodes.
  const touches = (f, key) => f.source.key === key || f.target.key === key;
  function paint() {
    const active = hovered || (chosen ? { flow: chosen } : selected && byKey.has(selected) ? { node: selected } : null);
    const lit = f => !active || (active.flow ? f === active.flow : touches(f, active.node));
    for (const [f, path] of bands) {
      path.classList.toggle('hot', !!active && lit(f));
      path.classList.toggle('faded', !lit(f));
    }
    for (const [key, g] of marks) g.classList.toggle('faded', !!active && active.node !== key && !flows.some(f => lit(f) && touches(f, key)));
  }
  const hover = next => {
    if ((next && next.flow) === (hovered && hovered.flow) && (next && next.node) === (hovered && hovered.node)) return;
    hovered = next;
    paint();
  };
  function nodeTip(n, outgoing) {
    const ends = (outgoing ? n.out : n.in).slice().sort((a, b) => b.value - a.value).slice(0, 3);
    return [n.label, [
      { value: fmtInt(n.value), label: questions(n.value), color: n.color },
      { value: fmtShare(n.value / total), label: `of the ${fmtInt(total)} shown` }]
      .concat(ends.map(f => { const other = outgoing ? f.target : f.source; return { value: fmtInt(f.value), label: `${outgoing ? '→' : '←'} ${other.label}`, color: other.color }; })),
    [n.note, n.onPick ? n.hint : null]];
  }
  const flowTip = f => [`${f.source.label} → ${f.target.label}`, [
    { value: fmtInt(f.value), label: questions(f.value), color: f.color || f.source.color },
    { value: fmtShare(f.value / f.source.value), label: `of ${f.source.label}` },
    { value: fmtShare(f.value / f.target.value), label: `of ${f.target.label}` }],
  f.questions ? (chosen === f ? 'Click to close the list' : `Click to list ${f.value === 1 ? 'this question' : `these ${fmtInt(f.value)} questions`}`) : null];

  function draw() {
    container.replaceChildren();
    bands.length = 0;
    marks.clear();
    const W = Math.max(300, container.clientWidth);
    // Each side keeps a column for its labels, which wrap onto more lines rather than being cut short.
    const side = Math.round(Math.min(230, Math.max(96, W * (W < 520 ? 0.33 : 0.27))));
    const barW = 10, LINE = 15, top = heads ? 28 : 6;
    const chars = Math.max(10, Math.floor((side - 18) / 6.4));
    const x0 = side - barW, x1 = W - side;
    const k = Math.min(6, Math.max(160, Math.min(380, total * 1.2)) / total);
    // The count stays with the last word, and an ampersand with the word before it (no-break spaces).
    for (const n of byKey.values()) { n.count = fmtInt(n.value); n.lines = wrapWords(`${n.label.replace(/ &/g, ' &')} ${n.count}`, chars); }
    // Gaps keep neighbouring labels apart; each column's bars add up to the same total.
    const column = nodes => {
      const gaps = nodes.slice(1).map((n, i) => Math.max(10, (nodes[i].lines.length + n.lines.length) * LINE / 2 + 5 - (nodes[i].value + n.value) * k / 2));
      return { nodes, gaps, height: total * k + sum(gaps) };
    };
    const stack = (col, from) => {
      let y = from;
      col.nodes.forEach((n, i) => { n.y = y; n.h = n.value * k; y += n.h + (col.gaps[i] || 0); });
    };
    const L = column(lefts);
    stack(L, 0);
    const centre = n => n.y + n.h / 2;
    const placed = rights.filter(n => !n.pinned).map(n => [sum(n.in.map(f => f.value * centre(f.source))) / n.value, n]).sort((a, b) => a[0] - b[0]).map(([, n]) => n);
    const R = column(placed.concat(rights.filter(n => n.pinned)));
    const inner = Math.max(L.height, R.height), H = Math.round(top + inner + 8);
    stack(L, top + (inner - L.height) / 2);
    stack(R, top + (inner - R.height) / 2);
    // Bands leave and reach each bar in the order of their other ends, so they cross as little as possible.
    for (const n of L.nodes) { let y = n.y; for (const f of n.out.slice().sort((a, b) => a.target.y - b.target.y)) { f.y0 = y; y += f.value * k; } }
    for (const n of R.nodes) { let y = n.y; for (const f of n.in.slice().sort((a, b) => a.source.y - b.source.y)) { f.y1 = y; y += f.value * k; } }

    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group', 'aria-label': label });
    if (heads) {
      svg.append(s('text', { class: 'sankey-head', x: x0 + barW, y: 12, 'text-anchor': 'end' }, heads[0]),
        s('text', { class: 'sankey-head', x: x1, y: 12 }, heads[1]));
    }
    const xa = x0 + barW, xb = x1, xm = (xa + xb) / 2;
    const linkLayer = s('g'), nodeLayer = s('g');
    for (const f of flows) {
      const w = f.value * k;
      const path = s('path', { class: f.questions ? 'sankey-link clickable' : 'sankey-link', style: `fill:${f.color || f.source.color}`,
        d: `M${r2(xa)},${r2(f.y0)}C${r2(xm)},${r2(f.y0)} ${r2(xm)},${r2(f.y1)} ${r2(xb)},${r2(f.y1)}V${r2(f.y1 + w)}C${r2(xm)},${r2(f.y1 + w)} ${r2(xm)},${r2(f.y0 + w)} ${r2(xa)},${r2(f.y0 + w)}Z` });
      path.addEventListener('pointermove', ev => { hover({ flow: f }); showTip(ev, ...flowTip(f)); });
      path.addEventListener('pointerleave', () => { hover(null); hideTip(); });
      if (f.questions) path.addEventListener('click', () => { hideTip(); openFlow(f); });
      linkLayer.append(path);
      bands.push([f, path]);
    }
    const place = (n, onLeft) => {
      const x = onLeft ? x0 : x1, cy = n.y + n.h / 2;
      const g = s('g', { class: n.onPick ? 'sankey-node clickable' : 'sankey-node' });
      g.append(s('rect', { class: 'sankey-bar', x: r2(x), y: r2(n.y), width: barW, height: r2(Math.max(1.5, n.h)), rx: 2, style: `fill:${n.color}` }));
      // The count follows the name on its last line, in a quieter ink.
      const text = s('text', { class: 'sankey-label', 'text-anchor': onLeft ? 'end' : 'start' });
      const tx = onLeft ? x - 8 : x + barW + 8, first = cy - (n.lines.length - 1) * LINE / 2 + 4;
      n.lines.forEach((line, i) => text.append(s('tspan', { x: r2(tx), y: r2(first + i * LINE) }, i === n.lines.length - 1 ? line.slice(0, line.lastIndexOf(' ') + 1) : line)));
      text.append(s('tspan', { class: 'sankey-count' }, n.count));
      const reach = Math.max(n.h, n.lines.length * LINE + 4);
      const hit = s('rect', { class: 'sankey-hit', x: onLeft ? 0 : x, y: r2(cy - reach / 2), width: onLeft ? x + barW : W - x, height: r2(reach),
        tabindex: '0', role: n.onPick ? 'button' : null, 'aria-label': `${n.label}: ${fmtInt(n.value)} ${questions(n.value)}` });
      const tip = () => nodeTip(n, onLeft);
      hit.addEventListener('pointermove', ev => { hover({ node: n.key }); showTip(ev, ...tip()); });
      hit.addEventListener('pointerleave', () => { hover(null); hideTip(); });
      hit.addEventListener('focus', () => { hover({ node: n.key }); showTip(pointOf(hit), ...tip()); });
      hit.addEventListener('blur', () => { hover(null); hideTip(); });
      if (n.onPick) {
        hit.addEventListener('click', () => { hideTip(); n.onPick(); });
        hit.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); hideTip(); n.onPick(); } });
      }
      g.append(text, hit);
      nodeLayer.append(g);
      marks.set(n.key, g);
    };
    L.nodes.forEach(n => place(n, true));
    R.nodes.forEach(n => place(n, false));
    svg.append(linkLayer, nodeLayer);
    container.append(svg);
    paint();
  }
  registerChart(draw);
  return { openFlow: (from, to) => openFlow(flows.find(f => f.from === from && f.to === to)) };
}

/* ---------- Strip plot: one dot per question, a tick at the median ---------- */
function stripPlot(container, { rows, onPick }) {
  function draw() {
    container.replaceChildren();
    if (!rows.length) { container.append(h('p', { class: 'muted', text: 'Not enough timed answers for this selection.' })); return; }
    const W = Math.max(300, container.clientWidth), rowH = 30;
    const m = { t: 6, r: 16, b: 26, l: Math.round(Math.min(230, Math.max(120, W * 0.24))) };
    const H = m.t + rows.length * rowH + m.b, pw = W - m.l - m.r;
    const { max, ticks } = niceTicks(Math.max(...rows.flatMap(r => r.items.map(it => it.value))), 6);
    const X = v => m.l + Math.min(v, max) / max * pw;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': 'Answer length of every question, grouped' });
    for (const t of ticks) {
      svg.append(s('line', { class: t === 0 ? 'baseline' : 'gridline', x1: r2(X(t)), x2: r2(X(t)), y1: m.t, y2: H - m.b }));
      svg.append(s('text', { class: 'tick', x: r2(X(t)), y: H - 8, 'text-anchor': 'middle' }, t === 0 ? '0' : `${t} min`));
    }
    const maxChars = Math.max(10, Math.floor((m.l - 14) / 6.6));
    const hot = s('circle', { class: 'strip-dot hot', r: 5, cx: -20, cy: -20, visibility: 'hidden' });
    rows.forEach((row, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      const group = s('g', { style: `--cat:${row.color || 'var(--acc)'}` });
      group.append(s('text', { class: 'strip-label', x: m.l - 10, y: r2(cy + 4), 'text-anchor': 'end' }, shorten(row.label, maxChars)));
      row.items.forEach((it, j) => {
        it.cx = X(it.value);
        it.cy = cy + ((((j + 1) * 2654435761) % 1000) / 1000 - 0.5) * 16;
        group.append(s('circle', { class: 'strip-dot', cx: r2(it.cx), cy: r2(it.cy), r: 3.5 }));
      });
      const med = median(row.items.map(it => it.value));
      group.append(s('line', { class: 'median-tick', x1: r2(X(med)), x2: r2(X(med)), y1: r2(cy - 11), y2: r2(cy + 11) }));
      svg.append(group);
      const hit = s('rect', { class: onPick ? 'hit-area clickable' : 'hit-area', x: m.l - 6, y: r2(cy - rowH / 2), width: pw + 12, height: rowH });
      const nearest = ev => {
        const box = svg.getBoundingClientRect();
        const x = (ev.clientX - box.left) * (W / box.width);
        return row.items.reduce((best, it) => !best || Math.abs(it.cx - x) < Math.abs(best.cx - x) ? it : best, null);
      };
      hit.addEventListener('pointermove', ev => {
        const it = nearest(ev);
        hot.style.fill = row.color || 'var(--acc)';
        hot.setAttribute('cx', r2(it.cx)); hot.setAttribute('cy', r2(it.cy)); hot.setAttribute('visibility', 'visible');
        showTip(ev, it.q.title, [
          { value: fmtDuration(it.q.length), label: 'until the next question', color: row.color },
          { value: `Ep ${it.q.ep} · Q${it.q.order}`, label: it.q.subName },
          { value: fmtMinutes(med), label: `median for ${row.label}` }], onPick ? 'Click to play this answer' : null);
      });
      hit.addEventListener('pointerleave', () => { hot.setAttribute('visibility', 'hidden'); hideTip(); });
      if (onPick) hit.addEventListener('click', ev => { hideTip(); onPick(nearest(ev).q); });
      svg.append(hit);
    });
    svg.append(hot);
    container.append(svg);
  }
  registerChart(draw);
}

/* ---------- Columns for a handful of ordered groups (ages, positions) ---------- */
function ordinalColumns(container, { items, format, label, height = 220 }) {
  const fit = fillCard(container, height);
  function draw() {
    container.replaceChildren();
    if (!items.some(it => it.value > 0)) { container.append(h('p', { class: 'muted', text: 'Nothing to show for this selection.' })); return; }
    const W = Math.max(240, container.clientWidth), H = fit();
    const m = { t: 20, r: 6, b: 24, l: 34 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const { max, ticks } = niceTicks(Math.max(0, ...items.map(it => it.value)), 4);
    const step = pw / items.length, bw = Math.min(44, step * 0.62);
    const Y = v => m.t + ph - (v / max) * ph;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': label });
    for (const t of ticks) {
      svg.append(s('line', { class: t === 0 ? 'baseline' : 'gridline', x1: m.l, x2: W - m.r, y1: r2(Y(t)), y2: r2(Y(t)) }));
      svg.append(s('text', { class: 'tick', x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, fmtCompact(t)));
    }
    items.forEach((it, i) => {
      const x = m.l + i * step + (step - bw) / 2;
      if (it.value > 0) svg.append(s('path', { class: 'col solid', d: columnPath(x, Y(it.value), bw, Y(0) - Y(it.value), 4) }));
      svg.append(s('text', { class: 'col-value', x: r2(x + bw / 2), y: r2(Y(it.value) - 6), 'text-anchor': 'middle' }, it.value > 0 ? format(it.value) : ''));
      svg.append(s('text', { class: 'col-label', x: r2(x + bw / 2), y: H - 7, 'text-anchor': 'middle' }, it.label));
      const hit = s('rect', { class: 'hit-area', x: r2(m.l + i * step), y: m.t, width: r2(step), height: ph, tabindex: '0' });
      attachTip(hit, () => [it.title || it.label, [{ value: format(it.value), label, color: 'var(--acc)' }].concat(it.rows || [])]);
      svg.append(hit);
    });
    container.append(svg);
  }
  registerChart(draw, container);
}

/* ---------- Sparkline: share of questions in each block of episodes ---------- */
function sparkline(values, labels, title) {
  const n = values.length, max = Math.max(...values) || 1, w = 100 / n;
  const svg = s('svg', { class: 'spark', viewBox: '0 0 100 30', preserveAspectRatio: 'none', role: 'img', 'aria-label': title });
  values.forEach((v, i) => {
    const height = Math.max(1, v / max * 28);
    svg.append(s('rect', { class: i === n - 1 ? 'last' : null, x: r2(i * w + w * 0.15), y: r2(30 - height), width: r2(w * 0.7), height: r2(height) },
      s('title', {}, `Episodes ${labels[i]}: ${fmtPct(v, 1)}`)));
  });
  return svg;
}

/* ---------- Sortable, paged table ---------- */
function dataTable(container, { columns, rows, sortKey, sortDir = 'asc', pageSize = 50, empty = 'Nothing matches.', cls = null }) {
  let key = sortKey, dir = sortDir, shown = pageSize;
  function compare(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    return typeof a === 'string' ? a.localeCompare(b) : a - b;
  }
  function draw() {
    const col = columns.find(c => c.key === key);
    const sorted = col ? rows.slice().sort((a, b) => {
      const va = col.sort(a), vb = col.sort(b);
      if (va == null || vb == null) return compare(va, vb);
      return compare(va, vb) * (dir === 'asc' ? 1 : -1);
    }) : rows;
    const head = h('tr', {}, columns.map(c => {
      const active = c.key === key;
      const th = h('th', { scope: 'col', class: c.num ? 'num' : null, 'aria-sort': active ? (dir === 'asc' ? 'ascending' : 'descending') : null });
      if (c.sort) {
        th.append(h('button', { class: 'sort-button', type: 'button', on: { click: () => {
          if (key === c.key) dir = dir === 'asc' ? 'desc' : 'asc';
          else { key = c.key; dir = c.firstDir || (c.num ? 'desc' : 'asc'); }
          draw();
        } } }, c.label, h('span', { class: 'arrow', text: active ? (dir === 'asc' ? '▲' : '▼') : '↕' })));
      } else th.textContent = c.label;
      return th;
    }));
    // Each cell carries its column's name, for layouts that stack a row's cells as labelled figures.
    const body = h('tbody', {}, sorted.slice(0, shown).map(row => h('tr', {}, columns.map(c => h('td', { class: c.num ? 'num' : null, 'data-label': c.label }, c.render ? c.render(row) : c.sort(row))))));
    if (!rows.length) body.append(h('tr', {}, h('td', { colspan: String(columns.length), class: 'muted', text: empty })));
    const footer = h('div', { class: 'table-footer' }, h('span', { text: rows.length ? `Showing ${fmtInt(Math.min(shown, rows.length))} of ${fmtInt(rows.length)}` : '' }));
    if (shown < rows.length) {
      footer.append(h('button', { class: 'small-button', type: 'button', text: `Show ${fmtInt(Math.min(pageSize, rows.length - shown))} more`, on: { click: () => { shown += pageSize; draw(); } } }));
    }
    // Set column widths keep the columns steady while sorting and paging.
    const widths = columns.some(c => c.width) ? h('colgroup', {}, columns.map(c => h('col', { style: c.width ? `width:${c.width}` : null }))) : null;
    container.replaceChildren(h('div', { class: 'table-wrap' }, h('table', { class: cls }, widths, h('thead', {}, head), body)), footer);
  }
  draw();
}

/* ---------- Question cards ---------- */
function questionCard(q) {
  const facts = [episodeLink(q.ep), ` · Q${q.order}`];
  if (q.length != null) facts.push(` · ${fmtDuration(q.length)} answer`);
  if (q.age) facts.push(` · age ${q.age}`);
  if (q.places.length) facts.push(` · ${q.places.map(i => PLACES[i].name).join(', ')}`);
  const yt = youtubeLink(q.ep, q.start, 'YouTube ↗');
  const el = h('article', { class: 'q-card', style: catStyle(q.cat) },
    h('div', { class: 'q-head' }, h('h4', { class: 'q-title', text: q.title }), h('div', { class: 'q-actions' }, playButton(q))),
    h('div', { class: 'q-meta' }, subTag(q), q.also.map(code => h('span', { class: 'tag', title: 'Also about', text: subName(code) }))),
    h('div', { class: 'q-meta' }, facts, yt ? [' · ', yt] : null),
    state.openings && excerptOf(q) ? h('p', { class: 'q-excerpt', text: excerptOf(q) }) : null);
  // A click anywhere on the card plays the answer, like its ▶ button; its own links keep their jobs, and selecting text does nothing.
  el.addEventListener('click', ev => {
    if (ev.target.closest('a, button') || String(window.getSelection())) return;
    openQuestion(q);
  });
  return el;
}
function questionList(container, list, pageSize = 24) {
  let shown = 0;
  const box = h('div', { class: 'q-list' });
  const count = h('span');
  const more = h('button', { class: 'small-button', type: 'button' });
  const showMore = () => {
    for (const q of list.slice(shown, shown + pageSize)) box.append(questionCard(q));
    shown = Math.min(list.length, shown + pageSize);
    count.textContent = list.length ? `Showing ${fmtInt(shown)} of ${plural(list.length, 'question')}` : '';
    more.textContent = `Show ${fmtInt(Math.min(pageSize, list.length - shown))} more`;
    more.hidden = shown >= list.length;
  };
  more.addEventListener('click', showMore);
  container.replaceChildren(list.length ? box : h('p', { class: 'notice' }, 'No questions in this selection. Clear the filter to see them all.'), h('div', { class: 'list-footer' }, count, more));
  showMore();
}

/* ---------- Question analytics shared by several tabs ---------- */
function categoryItems(qs) {
  const counts = countBy(qs, q => q.cat), total = qs.length || 1;
  return LIVE_CATS.filter(c => counts.get(c.id)).map(c => ({
    key: c.id, label: c.name, value: counts.get(c.id), note: c.description, color: c.color,
    rows: [{ value: fmtShare(counts.get(c.id) / total), label: 'of these questions' }],
  })).sort((a, b) => (a.key === 'other') - (b.key === 'other') || b.value - a.value);
}
function subItems(qs, cat) {
  const counts = countBy(qs, q => q.sub), total = qs.length || 1;
  const subs = cat ? CAT.get(cat).subs : LIVE_CATS.flatMap(c => c.subs);
  return subs.filter(sb => counts.get(sb.id)).map(sb => ({
    key: sb.id, label: sb.name, value: counts.get(sb.id), note: sb.description, color: sb.color,
    rows: [{ value: fmtShare(counts.get(sb.id) / total), label: 'of these questions' }].concat(cat ? [] : [{ value: catName(sb.cat), label: '' }]),
  })).sort((a, b) => b.value - a.value);
}
function pairItems(qs, focus) {
  const counts = new Map();
  for (const q of qs) {
    for (const other of q.alsoCats) {
      if (focus && q.cat !== focus && other !== focus) continue;
      const pair = focus ? (q.cat === focus ? other : q.cat) : [q.cat, other].sort().join('+');
      counts.set(pair, (counts.get(pair) || 0) + 1);
    }
  }
  return [...counts.entries()].map(([key, value]) => ({
    key, value, color: focus ? colorOf(key) : null,
    label: focus ? catName(key) : key.split('+').map(catName).join(' + '),
  })).sort((a, b) => b.value - a.value);
}
function cityItems(qs) {
  const counts = new Map();
  for (const q of qs) for (const i of q.cities) counts.set(i, (counts.get(i) || 0) + 1);
  return [...counts.entries()].map(([i, value]) => ({ key: i, label: CITIES[i].name, value, country: CITIES[i].country })).sort((a, b) => b.value - a.value);
}
function regionItems(qs) {
  const counts = new Map();
  for (const q of qs) for (const region of new Set(q.places.map(i => PLACES[i].region))) counts.set(region, (counts.get(region) || 0) + 1);
  return [...counts.entries()].map(([key, value]) => ({ key, label: key, value })).sort((a, b) => b.value - a.value);
}
function wordItems(qs) {
  const counts = new Map();
  for (const q of qs) for (const w of q.words) counts.set(w, (counts.get(w) || 0) + 1);
  return [...counts.entries()].filter(([, v]) => v > 1).map(([key, value]) => ({ key, label: key, value })).sort((a, b) => b.value - a.value);
}
function halves(eps) {
  const mid = Math.ceil(eps.length / 2);
  const first = eps.slice(0, mid), second = eps.slice(mid);
  const label = part => part.length ? `episodes ${part[0].n}–${part[part.length - 1].n}` : '';
  return { first: new Set(first.map(e => e.n)), firstLabel: label(first), secondLabel: label(second) };
}
function shiftItems(qs, keyOf, keys, labelOf) {
  const { first } = halves(EPISODES);
  const a = qs.filter(q => first.has(q.ep)), b = qs.filter(q => !first.has(q.ep));
  if (!a.length || !b.length) return [];
  const ca = countBy(a, keyOf), cb = countBy(b, keyOf);
  return keys.map(key => {
    const pa = (ca.get(key) || 0) / a.length, pb = (cb.get(key) || 0) / b.length;
    return { key, label: labelOf(key), value: (pb - pa) * 100, a: pa, b: pb, n: (ca.get(key) || 0) + (cb.get(key) || 0),
      note: `${fmtPct(pa, 1)} → ${fmtPct(pb, 1)} of questions` };
  });
}
// Rising and falling subjects: categories overall, or the subcategories of the selected category.
function shiftsFor(minimum) {
  const scoped = state.cat ? QUESTIONS.filter(q => q.cat === state.cat) : QUESTIONS;
  const keys = state.cat ? CAT.get(state.cat).subs.map(sb => sb.id) : TOPICS.map(c => c.id);
  return shiftItems(scoped, state.cat ? q => q.sub : q => q.cat, keys, state.cat ? subName : catName)
    .filter(it => it.n >= minimum).sort((a, b) => b.value - a.value);
}
const AGE_BINS = [[13, 17, 'Under 18'], [18, 21, '18–21'], [22, 25, '22–25'], [26, 29, '26–29'], [30, 34, '30–34'], [35, 39, '35–39'], [40, 99, '40+']];
function ageItems(qs) {
  const ages = qs.map(q => q.age).filter(Boolean);
  return AGE_BINS.map(([lo, hi, label]) => {
    const n = ages.filter(a => a >= lo && a <= hi).length;
    return { key: label, label, value: n, title: `Age ${label}`, rows: [{ value: fmtPct(n / (ages.length || 1)), label: 'of stated ages' }] };
  });
}
function positionItems(qs) {
  const groups = [1, 2, 3, 4, 5, 6, 7, 8].map(p => ({ label: `Q${p}`, test: q => q.order === p })).concat([{ label: 'Q9+', test: q => q.order >= 9 }]);
  return groups.map(g => {
    const lengths = qs.filter(q => g.test(q) && q.length != null).map(q => q.length / 60);
    return { key: g.label, label: g.label, value: median(lengths) || 0, title: `Question ${g.label.slice(1)} in an episode`,
      rows: [{ value: fmtInt(lengths.length), label: 'timed answers' }] };
  });
}
/* ---------- Answer words: what stands out in the English translation of a subject's answers ---------- */
const ANSWER_GROUPS = (DATA.answerWords || {}).groups || {};
function answerItems(key) {
  const group = ANSWER_GROUPS[key];
  return group ? group.words.map(([word, inside, outside, uses]) => ({
    key: word, label: word, value: inside / group.answers, ref: outside / group.versus, color: colorOf(key),
    rows: [{ value: fmtPct(outside / group.versus), label: 'of all other answers', color: 'var(--ink-soft)' },
      { value: fmtInt(uses), label: `uses in ${plural(inside, 'answer')}` }],
  })) : [];
}
function answerCard(key, span) {
  const group = ANSWER_GROUPS[key], items = answerItems(key);
  const c = card({ title: 'What the answers talk about', subtitle: 'Words that set these answers apart, in the English translation · share of answers using each', span,
    legend: items.length ? h('div', { class: 'legend' },
      h('span', {}, h('span', { class: 'key-rect', style: `background:${colorOf(key)}` }), `These ${plural(group.answers, 'answer')}`),
      h('span', {}, h('span', { class: 'key-tick' }), 'All other answers')) : null,
    table: items.length ? () => ({ columns: [{ label: 'Word' }, { label: 'These answers', num: true }, { label: 'Other answers', num: true }, { label: 'Uses', num: true }],
      rows: group.words.map(([word, inside, outside, uses]) => [word, fmtPct(inside / group.answers), fmtPct(outside / group.versus), fmtInt(uses)]) }) : null });
  if (items.length) barList(c.body, { items: items.slice(0, 10), format: v => fmtPct(v), valueLabel: 'of these answers' });
  else c.body.append(h('p', { class: 'muted', text: group ? 'No word stands out clearly in these answers.' : 'Too few answers here to compare.' }));
  return c.el;
}

function findings(qs) {
  const items = [], total = qs.length;
  if (!state.cat) {
    const top = categoryItems(qs)[0];
    if (top) {
      const lead = subItems(qs.filter(q => q.cat === top.key), top.key)[0];
      items.push(['The biggest subject is ', strong(top.label), `, with ${plural(top.value, 'question')} (${fmtPct(top.value / total)})`,
        lead ? [', led by ', strong(lead.label), ` (${fmtInt(lead.value)})`] : '', '.']);
    }
  } else if (!state.sub) {
    const subs = subItems(qs, state.cat);
    if (subs.length) items.push(['Within ', strong(catName(state.cat)), ', the most common subject is ', strong(subs[0].label), ` (${plural(subs[0].value, 'question')}, ${fmtPct(subs[0].value / total)}).`]);
  } else {
    items.push([strong(subName(state.sub)), ` makes up ${fmtPct(total / CAT_COUNTS.get(state.cat))} of ${catName(state.cat)} questions and ${fmtShare(total / QUESTIONS.length)} of all questions.`]);
  }
  const standout = ANSWER_GROUPS[state.sub || state.cat];
  if (standout && standout.words.length >= 3) {
    const [first, second, third] = standout.words.map(([word]) => word);
    items.push(['The words that most set ', strong(scopeName()), ' answers apart are ', strong(first), ', ', strong(second), ' and ', strong(third), ', going by the English translation.']);
  }
  const shifts = shiftsFor(5);
  const { firstLabel, secondLabel } = halves(EPISODES);
  if (shifts.length >= 2 && shifts[0].value > 0) {
    const up = shifts[0], down = shifts[shifts.length - 1];
    items.push(['Comparing ', firstLabel, ' with ', secondLabel, ', ', strong(up.label), ` grew the most (${fmtPct(up.a)} → ${fmtPct(up.b)} of questions)`,
      down.value < 0 ? [' and ', strong(down.label), ` shrank the most (${fmtPct(down.a)} → ${fmtPct(down.b)})`] : '', '.']);
  }
  if (!state.sub) {
    const groups = (state.cat ? subItems(qs, state.cat) : categoryItems(qs).filter(c => c.key !== 'other')).map(it => {
      const lengths = qs.filter(q => (state.cat ? q.sub : q.cat) === it.key && q.length != null).map(q => q.length);
      return { label: it.label, n: lengths.length, med: median(lengths) };
    }).filter(g => g.n >= 5).sort((a, b) => b.med - a.med);
    if (groups.length >= 2) {
      items.push([strong(groups[0].label), ` questions get the longest answers (median ${fmtDuration(groups[0].med)}); `, strong(groups[groups.length - 1].label), ` the shortest (${fmtDuration(groups[groups.length - 1].med)}).`]);
    }
  }
  const ages = qs.map(q => q.age).filter(Boolean);
  if (ages.length >= 10) {
    items.push([`${plural(ages.length, 'asker')} state their age: the median is `, strong(String(median(ages))), `, and ${fmtPct(ages.filter(a => a < 30).length / ages.length)} are under 30.`]);
  }
  // Cities rather than countries: the cities in Pakistan, then the ones abroad.
  const cities = cityItems(qs);
  if (cities.length) {
    const named = list => list.map((c, i) => [i ? (i === list.length - 1 ? ' and ' : ', ') : '', strong(c.label), ` (${fmtInt(c.value)})`]);
    const home = cities.filter(c => c.country === 'Pakistan').slice(0, 3), away = cities.filter(c => c.country !== 'Pakistan').slice(0, 3);
    const first = home.length ? home : away;
    const abroad = qs.filter(q => q.places.some(i => PLACES[i].region !== 'Pakistan')).length;
    items.push([`The most mentioned ${first.length > 1 ? 'cities are' : 'city is'} `, named(first),
      home.length && away.length ? ['; abroad, it is ', named(away)] : '',
      `. ${fmtPct(abroad / total)} of these questions mention somewhere outside Pakistan.`]);
  }
  const multi = qs.filter(q => q.alsoCats.length).length;
  const pairs = pairItems(qs, state.cat);
  if (multi && pairs.length) {
    items.push([`${fmtPct(multi / total)} of these questions touch a second subject; the most common pairing is `,
      strong(state.cat ? `${catName(state.cat)} + ${pairs[0].label}` : pairs[0].label), ` (${fmtInt(pairs[0].value)}).`]);
  }
  const answered = qs.filter(q => q.length != null);
  if (answered.length) {
    const top = answered.reduce((a, b) => b.length > a.length ? b : a);
    items.push(['The longest single answer: ', h('a', { href: `#tab=episode&ep=${top.ep}`, on: { click: ev => { ev.preventDefault(); openQuestion(top); } } }, `“${top.title}”`),
      ` (episode ${top.ep}), ${fmtDuration(top.length)}.`]);
  }
  return h('ul', { class: 'findings' }, items.map(parts => h('li', {}, parts)));
}

/* ---------- Sidebar: sections with the category tree, theme and the phone drawer ---------- */
const SECTIONS = {
  overview: { label: 'Overview', icon: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z' },
  categories: { label: 'Categories', icon: 'M11 5a8 8 0 1 0 8 8h-8zM13 3a8 8 0 0 1 8 8h-8z' },
  questions: { label: 'Questions', icon: 'M4 5h16v11H9l-5 4zM8 9h8M8 12h5' },
  insights: { label: 'Insights', icon: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2v.2h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z' },
  episodes: { label: 'Episodes', icon: 'M4 20v-9M9.3 20V5M14.6 20v-6M20 20V8' },
  episode: { label: 'Episode explorer', icon: 'M3 5h18v14H3zM10 9v6l5-3z' },
  about: { label: 'About', icon: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8v.01' },
};
const navBox = document.getElementById('nav');
const navItems = new Map();
// The category tree hangs under its section, right below the Overview: categories, each with its
// subcategories below it.
const treeBody = h('div', { class: 'tree-body', id: 'tree' });
const treeToggle = h('button', { class: 'nav-expand', type: 'button', 'aria-controls': 'tree', 'aria-label': 'Show or hide the categories' },
  h('span', { class: 'chevron', 'aria-hidden': 'true' }));
for (const tab of TABS) {
  const item = h('button', { class: 'nav-item', type: 'button', 'data-tab': tab, on: { click: () => go(tab) } }, icon(SECTIONS[tab].icon), h('span', { text: SECTIONS[tab].label }));
  navItems.set(tab, item);
  navBox.append(tab === 'categories' ? h('div', { class: 'nav-group' }, h('div', { class: 'nav-row' }, item, treeToggle), treeBody) : item);
}
const openCats = new Set();
let treeCat = '';
function setTreeOpen(open) {
  treeToggle.setAttribute('aria-expanded', String(open));
  treeBody.hidden = !open;
}
treeToggle.addEventListener('click', () => {
  const open = treeToggle.getAttribute('aria-expanded') !== 'true';
  setTreeOpen(open);
  try { localStorage.setItem('ganji-tree', open ? 'open' : 'closed'); } catch (error) { /* storage unavailable */ }
});
try { setTreeOpen(localStorage.getItem('ganji-tree') !== 'closed'); } catch (error) { setTreeOpen(true); }
function renderTree() {
  if (state.cat && state.cat !== treeCat) openCats.add(state.cat);
  treeCat = state.cat;
  const filtering = FILTER_TABS.has(state.tab);
  const all = h('button', { class: 'tree-row tree-all', type: 'button', style: '--cat:var(--ink-soft)', 'aria-current': filtering && !state.cat ? 'true' : null,
    on: { click: () => pickCategory('') } },
  h('span', { class: 'dot' }), h('span', { class: 'name', text: 'All questions' }), h('span', { class: 'count', text: fmtInt(QUESTIONS.length) }));
  const items = LIVE_CATS.map(c => {
    const open = openCats.has(c.id);
    const toggle = h('button', { class: 'tree-toggle', type: 'button', 'aria-expanded': String(open), 'aria-label': `${open ? 'Hide' : 'Show'} subcategories of ${c.name}` },
      h('span', { class: 'chevron', 'aria-hidden': 'true' }));
    toggle.addEventListener('click', () => {
      if (openCats.has(c.id)) openCats.delete(c.id); else openCats.add(c.id);
      renderTree();
    });
    const row = h('button', { class: 'tree-row', type: 'button', style: `--cat:${c.color}`, title: c.description,
      'aria-current': filtering && state.cat === c.id && !state.sub ? 'true' : null, on: { click: () => pickCategory(c.id) } },
    h('span', { class: 'dot' }), h('span', { class: 'name', text: c.name }), h('span', { class: 'count', text: fmtInt(CAT_COUNTS.get(c.id)) }));
    const subs = open ? h('div', { class: 'tree-subs' }, c.subs.map(sb => h('button', { class: 'tree-row', type: 'button', title: sb.description,
      'aria-current': filtering && state.sub === sb.id ? 'true' : null, on: { click: () => pickCategory(c.id, sb.id) } },
    h('span', { class: 'name', text: sb.name }), h('span', { class: 'count', text: fmtInt(SUB_COUNTS.get(sb.id)) })))) : null;
    return h('div', { class: 'tree-item' }, toggle, row, subs);
  });
  treeBody.replaceChildren(all, ...items);
}

const themeBox = document.getElementById('theme-switch');
const THEMES = [['auto', 'Auto'], ['light', 'Light'], ['dark', 'Dark']];
function applyTheme(theme) {
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  for (const b of themeBox.children) b.setAttribute('aria-pressed', String(b.dataset.theme === theme));
  try { localStorage.setItem('ganji-theme', theme); } catch (error) { /* storage unavailable */ }
}
for (const [theme, label] of THEMES) themeBox.append(h('button', { type: 'button', 'data-theme': theme, text: label, on: { click: () => applyTheme(theme) } }));
let savedTheme = 'auto';
try { savedTheme = localStorage.getItem('ganji-theme') || 'auto'; } catch (error) { /* storage unavailable */ }
applyTheme(THEMES.some(([t]) => t === savedTheme) ? savedTheme : 'auto');

const rail = document.getElementById('rail');
const scrim = document.getElementById('scrim');
const menuButton = document.getElementById('menu-button');
function openRail() {
  rail.classList.add('open');
  scrim.hidden = false;
  menuButton.setAttribute('aria-expanded', 'true');
  const current = navBox.querySelector('[aria-current="page"]');
  if (current) current.focus();
}
function closeRail() {
  if (!rail.classList.contains('open')) return;
  rail.classList.remove('open');
  scrim.hidden = true;
  menuButton.setAttribute('aria-expanded', 'false');
}
menuButton.addEventListener('click', () => rail.classList.contains('open') ? closeRail() : openRail());
scrim.addEventListener('click', closeRail);
document.getElementById('rail-close').addEventListener('click', () => { closeRail(); menuButton.focus(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') { hideTip(); closeRail(); } });
document.getElementById('playlist-link').href = DATA.meta.playlist;

/* ---------- Top bar: page title and active filter ---------- */
const pageTitle = document.getElementById('page-title');
const pageSub = document.getElementById('page-sub');
const chipBox = document.getElementById('filter-chip');
const SUBTITLES = {
  overview: () => `${fmtInt(QUESTIONS.length)} viewer questions from ${fmtInt(EPISODES.length)} episodes, in ${TOPICS.length} categories and ${SUBTOPIC_COUNT} subcategories`,
  categories: () => state.cat ? CAT.get(state.cat).description : 'How the questions are grouped, and how each subject changed over the years',
  questions: () => 'Every question, by category, with its answer one click away',
  insights: () => 'Answer lengths, ages, places, words and the subjects on the rise',
  episodes: () => 'Length, pace and questions for every episode',
  episode: () => {
    const e = BY_EP.get(state.ep);
    return e ? `Episode ${e.n} · ${fmtDuration(e.duration)} · ${plural(e.questions, 'question')}` : '';
  },
  about: () => 'What this app shows, how to use it, and how the data was made',
};
function updateChrome() {
  for (const [tab, b] of navItems) {
    if (tab === state.tab) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  }
  const title = state.tab === 'categories' && state.cat ? catName(state.cat) : SECTIONS[state.tab].label;
  pageTitle.textContent = title;
  pageSub.textContent = SUBTITLES[state.tab]();
  document.title = `${title} · Ask Ganji Swag Analytics`;
  chipBox.replaceChildren();
  if (FILTER_TABS.has(state.tab) && state.cat && state.tab !== 'categories') {
    chipBox.append(h('span', { class: 'filter-chip', style: catStyle(state.cat) },
      h('span', { class: 'dot' }), h('span', { text: state.sub ? `${catName(state.cat)} › ${subName(state.sub)}` : catName(state.cat) }),
      h('button', { type: 'button', 'aria-label': 'Clear the category filter', title: 'Clear filter', text: '×', on: { click: () => setFilter('', '') } })));
  }
  renderTree();
}

/* ---------- Overview ---------- */
function renderOverview(panel) {
  const qs = scopedQuestions();
  const cat = state.cat ? CAT.get(state.cat) : null;
  const scope = scopeName();
  const ages = qs.map(q => q.age).filter(Boolean);

  const donutRows = () => ({
    columns: [{ label: 'Category' }, { label: 'Subcategory' }, { label: 'Questions', num: true }, { label: 'Share', num: true }],
    rows: (cat ? [cat] : LIVE_CATS).flatMap(c => c.subs.map((sb, i) => [i ? '' : c.name, sb.name, fmtInt(SUB_COUNTS.get(sb.id)), fmtShare(SUB_COUNTS.get(sb.id) / (cat ? CAT_COUNTS.get(c.id) : QUESTIONS.length))])),
  });
  const donut = card({ title: cat ? `Inside ${cat.name}` : 'What viewers ask about',
    subtitle: cat ? 'Subcategories by number of questions · click one to filter, or the centre to go back' : 'Categories in the inner ring, their subcategories outside · click a slice or a row to zoom in',
    table: donutRows });
  if (cat) donut.actions.prepend(h('button', { class: 'small-button', type: 'button', text: '← All categories', on: { click: () => setFilter('', '') } }));
  sunburst(donut.body, { cat: state.cat, sub: state.sub, onPick: (c, sb) => setFilter(c, sb), onBack: () => setFilter('', '') });
  panel.append(donut.el);

  const series = cat ? cat.subs.map(sb => ({ key: sb.id, label: sb.name, color: sb.tone, shade: 1 }))
    : LIVE_CATS.map(c => ({ key: c.id, label: c.name, color: c.color, shade: 1 }));
  const blocks = eras(EPISODES);
  const pool = cat ? QUESTIONS.filter(q => q.cat === cat.id) : QUESTIONS;
  const groupOf = cat ? q => q.sub : q => q.cat;
  const trend = card({ title: cat ? `${cat.name} over time` : 'Subjects over time',
    subtitle: `Questions in each block of ${Math.ceil(EPISODES.length / blocks.length)} episodes · click a band to filter`, span: 'span-7', legend: seriesLegend(series),
    table: () => ({
      columns: [{ label: 'Episodes' }].concat(series.map(sr => ({ label: sr.label, num: true }))),
      rows: blocks.map(b => { const list = pool.filter(q => q.ep >= b.from && q.ep <= b.to), counts = countBy(list, groupOf); return [b.label].concat(series.map(sr => fmtInt(counts.get(sr.key) || 0))); }),
    }) });
  const stacked = stackedColumns(trend.body, { qs: pool, series, groupOf, selected: state.sub || null,
    onPick: key => cat ? setFilter(cat.id, state.sub === key ? '' : key) : setFilter(key, '') });
  trend.actions.prepend(segmented('Measure', [['Share', true], ['Count', false]], state.share, on => { state.share = on; stacked.setShare(on); }));
  const summary = card({ title: 'Key findings', subtitle: scope ? `For questions about ${scope}` : 'Across all episodes', span: 'span-5' });
  summary.body.append(findings(qs));
  panel.append(trend.el, summary.el);

  const counts = countBy(qs, q => q.ep);
  panel.append(episodeCard(EPISODES, {
    title: scope ? `${scope}: questions per episode` : 'Questions per episode', subtitle: 'Index entries in each episode · click a column to open it',
    label: 'Questions', value: e => counts.get(e.n) || 0, format: fmtInt, color: cat ? cat.color : null, span: 'span-12', height: 300,
    extra: e => (QS_BY_EP.get(e.n) || []).filter(inScope).slice(0, 3).map(q => ({ value: `Q${q.order}`, label: shorten(q.title, 60) })),
  }));

  const top = cat ? null : subItems(qs).slice(0, 10);
  const second = cat
    ? card({ title: 'Often comes with', subtitle: 'Other categories tagged on the same questions · click to switch', span: 'span-4', table: itemsTable('Category', pairItems(qs, cat.id), fmtInt) })
    : card({ title: 'Most common subcategories', subtitle: 'Across every category · click to filter', span: 'span-4', table: itemsTable('Subcategory', subItems(qs), fmtInt) });
  if (cat) barList(second.body, { items: pairItems(qs, cat.id).slice(0, 10), format: fmtInt, valueLabel: 'questions in both', onSelect: key => setFilter(key, '') });
  else barList(second.body, { items: top, format: fmtInt, valueLabel: 'questions', onSelect: key => setFilter(SUB.get(key).cat, key) });

  const shifts = shiftsFor(3);
  const movers = shifts.length > 12 ? shifts.slice(0, 6).concat(shifts.slice(-6)) : shifts;
  const { firstLabel, secondLabel } = halves(EPISODES);
  const change = card({ title: 'Rising and falling', subtitle: `Change in share of ${cat ? `${cat.name} questions` : 'questions'}, ${firstLabel} vs ${secondLabel}`, span: 'span-4',
    legend: divergingLegend(firstLabel, secondLabel),
    table: () => ({ columns: [{ label: 'Subject' }, { label: 'First half', num: true }, { label: 'Second half', num: true }, { label: 'Change', num: true }], rows: shifts.map(it => [it.label, fmtPct(it.a, 1), fmtPct(it.b, 1), fmtPoints(it.value)]) }) });
  divergingBars(change.body, { items: movers, onSelect: key => cat ? setFilter(cat.id, key) : setFilter(key, '') });

  const ageList = ageItems(qs);
  const agesCard = card({ title: 'How old are the askers?', subtitle: ages.length ? `${plural(ages.length, 'question')} state an age · median ${median(ages)}` : 'No ages stated in these questions', span: 'span-4', table: itemsTable('Age', ageList, fmtInt) });
  ordinalColumns(agesCard.body, { items: ageList, format: fmtInt, label: 'questions', height: 250 });
  panel.append(second.el, change.el, agesCard.el);
}

/* ---------- Categories ---------- */
// Questions grouped by the band they make in a Sankey: pairOf(q) names its two ends as "from>to".
function bandsOf(qs, pairOf) {
  const groups = new Map();
  for (const q of qs) {
    for (const pair of [].concat(pairOf(q))) {
      if (!groups.has(pair)) groups.set(pair, []);
      groups.get(pair).push(q);
    }
  }
  return [...groups.entries()].map(([pair, questions]) => ({ pair: pair.split('>'), value: questions.length, questions })).sort((a, b) => b.value - a.value);
}
// In a Sankey's table, a band's count lists its questions under the chart, as clicking the band does.
const bandButton = (chart, l) => h('button', { class: 'link-button', type: 'button', text: fmtInt(l.value), title: 'List these questions under the chart',
  on: { click: () => chart.openFlow(l.from, l.to) } });
// The questions that also touch a second category, from their main category to that one.
function connectionsCard() {
  const links = bandsOf(QUESTIONS, q => q.alsoCats.map(other => `${q.cat}>${other}`)).map(l => ({ ...l, from: `from:${l.pair[0]}`, to: `to:${l.pair[1]}` }));
  const total = sum(links.map(l => l.value));
  const node = (end, c) => ({ key: `${end}:${c.id}`, label: c.name, color: c.color, note: c.description, hint: 'Click to open this category',
    onPick: () => go('categories', { cat: c.id, sub: '' }) });
  const flows = card({ title: 'How subjects connect', subtitle: `The ${plural(total, 'question')} that also touch a second category, from their main category to the other · click a band to list its questions, or a category to open it`,
    table: () => ({ columns: [{ label: 'Main category' }, { label: 'Also about' }, { label: 'Questions', num: true }, { label: 'Of its questions', num: true }],
      rows: links.map(l => [catName(l.pair[0]), catName(l.pair[1]), bandButton(chart, l), fmtShare(l.value / CAT_COUNTS.get(l.pair[0]))]) }) });
  const chart = sankey(flows.body, { left: LIVE_CATS.map(c => node('from', c)), right: LIVE_CATS.map(c => node('to', c)), links,
    heads: ['Main category', 'Also about'], label: 'Questions by main category and the second category they touch' });
  return flows.el;
}
// A category's questions, from their subcategory to the second subject they are tagged with, if any.
function secondSubjectsCard(cat, inCat) {
  const links = bandsOf(inCat, q => `${q.sub}>${q.alsoCats[0] || (q.also.length ? 'same' : 'none')}`)
    .map(l => ({ ...l, from: l.pair[0], to: l.pair[1], color: l.pair[1] === 'none' ? 'var(--muted)' : null }));
  const left = cat.subs.map(sb => ({ key: sb.id, label: sb.name, color: sb.tone, note: sb.description,
    hint: state.sub === sb.id ? 'Click to show the whole category' : 'Click to narrow this page to it', onPick: () => setFilter(cat.id, state.sub === sb.id ? '' : sb.id) }));
  const right = LIVE_CATS.filter(c => c.id !== cat.id).map(c => ({ key: c.id, label: c.name, color: c.color, note: c.description,
    hint: 'Click to open this category', onPick: () => go('categories', { cat: c.id, sub: '' }) }))
    .concat([{ key: 'same', label: `Another ${cat.name} subject`, color: cat.color, note: `Tagged with a second subcategory of ${cat.name}`, pinned: true },
      { key: 'none', label: 'No second subject', color: 'var(--muted)', note: 'Questions about this subject alone', pinned: true }]);
  const toName = key => right.find(n => n.key === key).label;
  const flows = card({ title: 'Subcategories and second subjects', subtitle: 'Each band is a group of questions, from their subcategory to the other subject they also touch · click a band to list its questions, or either side to go there',
    table: () => ({ columns: [{ label: 'Subcategory' }, { label: 'Also about' }, { label: 'Questions', num: true }, { label: 'Of the subcategory', num: true }],
      rows: links.map(l => [subName(l.from), toName(l.to), bandButton(chart, l), fmtShare(l.value / SUB_COUNTS.get(l.from))]) }) });
  const chart = sankey(flows.body, { left, right, links, heads: ['Subcategory', 'Also about'], selected: state.sub || null, label: `${cat.name} questions by subcategory and second subject` });
  return flows.el;
}
function categoryCard(cat, eraList) {
  const inCat = QUESTIONS.filter(q => q.cat === cat.id);
  const answered = inCat.filter(q => q.length != null).map(q => q.length);
  const shares = eraList.map(era => {
    const inEra = QUESTIONS.filter(q => q.ep >= era.from && q.ep <= era.to);
    return inEra.length ? inEra.filter(q => q.cat === cat.id).length / inEra.length : 0;
  });
  return h('a', { class: 'cat-card', href: `#tab=categories&cat=${cat.id}`, style: `--cat:${cat.color}`,
    on: { click: ev => { ev.preventDefault(); go('categories', { cat: cat.id, sub: '' }); } } },
  h('div', { class: 'cat-card-top' },
    h('h3', {}, h('span', { class: 'dot' }), cat.name),
    h('div', {}, h('div', { class: 'cat-count', text: fmtInt(inCat.length) }), h('div', { class: 'cat-share', text: `${fmtShare(inCat.length / QUESTIONS.length)} of all` }))),
  h('p', { class: 'cat-desc', text: cat.description }),
  sparkline(shares, eraList.map(e => e.label), `${cat.name}: share of questions in each block of episodes`),
  h('div', { class: 'cat-subs' }, subItems(inCat, cat.id).slice(0, 4).map(it => h('div', { class: 'cat-sub' }, h('span', { text: it.label }), h('span', { text: fmtInt(it.value) })))),
  h('div', { class: 'cat-foot' }, h('span', { text: `${plural(cat.subs.length, 'subcategory', 'subcategories')} · median answer ${fmtDuration(median(answered))}` }), h('span', { text: 'Explore →' })));
}
function renderCategories(panel) {
  if (state.cat) { renderCategoryDetail(panel); return; }
  const eraList = eras(EPISODES);
  panel.append(connectionsCard());
  panel.append(h('div', { class: 'cat-grid' }, LIVE_CATS.map(c => categoryCard(c, eraList))));
}
function renderCategoryDetail(panel) {
  const cat = CAT.get(state.cat);
  const inCat = QUESTIONS.filter(q => q.cat === cat.id), qs = inCat.filter(inScope);
  const sub = state.sub ? SUB.get(state.sub) : null;
  const crumb = (label, onClick) => h('a', { href: '#', on: { click: ev => { ev.preventDefault(); onClick(); } } }, label);
  const answered = qs.filter(q => q.length != null).map(q => q.length);
  const ages = qs.map(q => q.age).filter(Boolean);
  const facts = [plural(qs.length, 'question'),
    sub ? `${fmtPct(qs.length / inCat.length)} of ${cat.name}` : `${fmtShare(qs.length / QUESTIONS.length)} of all questions`,
    `in ${fmtInt(new Set(qs.map(q => q.ep)).size)} of ${plural(EPISODES.length, 'episode')}`,
    answered.length ? `median answer ${fmtDuration(median(answered))}` : null];
  panel.append(h('div', { class: 'detail span-12' },
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' },
      crumb('All categories', () => setFilter('', '')), h('span', { 'aria-hidden': 'true', text: '›' }),
      sub ? [crumb(cat.name, () => setFilter(cat.id, '')), h('span', { 'aria-hidden': 'true', text: '›' }), h('span', { text: sub.name })] : h('span', { text: cat.name })),
    h('div', { class: 'detail-head', style: `--cat:${cat.color}` }, h('span', { class: 'dot' }),
      h('div', {}, h('h2', { text: sub ? sub.name : cat.name }), h('p', { text: sub ? sub.description : cat.description }),
        h('p', { class: 'detail-facts', text: facts.filter(Boolean).join(' · ') })))));

  const subsCard = card({ title: 'Subcategories', subtitle: 'Click one to narrow this page', span: 'span-5', table: itemsTable('Subcategory', subItems(inCat, cat.id), fmtInt) });
  barList(subsCard.body, { items: subItems(inCat, cat.id), format: fmtInt, valueLabel: 'questions', selected: state.sub, onSelect: key => setFilter(cat.id, state.sub === key ? '' : key) });
  const counts = countBy(qs, q => q.ep);
  panel.append(subsCard.el, episodeCard(EPISODES, {
    title: 'Over time', subtitle: `${sub ? sub.name : cat.name} questions per episode · click to open an episode`, label: 'Questions',
    value: e => counts.get(e.n) || 0, format: fmtInt, color: cat.color, span: 'span-7', height: 260,
    extra: e => (QS_BY_EP.get(e.n) || []).filter(inScope).slice(0, 3).map(q => ({ value: `Q${q.order}`, label: shorten(q.title, 60) })),
  }));

  if (!sub && cat.subs.length > 1) {
    const cols = eras(EPISODES);
    const rows = subItems(inCat, cat.id).map(it => ({ key: it.key, label: it.label }));
    const lists = new Map(cols.map(c => [c.key, inCat.filter(q => q.ep >= c.from && q.ep <= c.to)]));
    const cell = (r, c) => {
      const list = lists.get(c.key), count = list.filter(q => q.sub === r.key).length;
      return { count, total: list.length, share: list.length ? count / list.length : 0 };
    };
    const heat = card({ title: `What ${cat.name} questions were about, over time`, subtitle: 'Share of the category’s questions in each block of episodes',
      table: () => ({ columns: [{ label: 'Subcategory' }].concat(cols.map(c => ({ label: `Ep ${c.label}`, num: true }))), rows: rows.map(r => [r.label].concat(cols.map(c => fmtPct(cell(r, c).share, 1)))) }) });
    heatmap(heat.body, { rows, cols, cell, title: 'Share of the category’s questions by block of episodes' });
    panel.append(heat.el);
  }
  panel.append(secondSubjectsCard(cat, inCat));

  // With the English translation, what the answers talk about; the flows above already show the second subjects.
  let pairCard;
  if (DATA.answerWords) pairCard = { el: answerCard(sub ? sub.id : cat.id, 'span-4') };
  else {
    const pairs = pairItems(qs, cat.id);
    pairCard = card({ title: 'Often comes with', subtitle: 'Other categories tagged on the same questions', span: 'span-4', table: itemsTable('Category', pairs, fmtInt) });
    barList(pairCard.body, { items: pairs.slice(0, 8), format: fmtInt, valueLabel: 'questions in both', onSelect: key => go('categories', { cat: key, sub: '' }) });
  }
  const words = wordItems(qs);
  const wordCard = card({ title: 'Words in these questions', subtitle: 'Most frequent words in the question titles', span: 'span-4', table: itemsTable('Word', words.slice(0, 30), fmtInt) });
  barList(wordCard.body, { items: words.slice(0, 10), format: fmtInt, valueLabel: 'titles' });
  const ageList = ageItems(qs);
  const agesCard = card({ title: 'Asker ages', subtitle: ages.length ? `${plural(ages.length, 'question')} state an age` : 'No ages stated', span: 'span-4', table: itemsTable('Age', ageList, fmtInt) });
  ordinalColumns(agesCard.body, { items: ageList, format: fmtInt, label: 'questions', height: 250 });
  panel.append(pairCard.el, wordCard.el, agesCard.el);

  const list = card({ title: plural(qs.length, 'question'), subtitle: 'Newest first · ▶ plays the answer with its transcript' });
  questionList(list.body, qs.slice().sort(SORTS.newest.compare), 16);
  panel.append(list.el);
}

/* ---------- Questions explorer ---------- */
function renderQuestions(panel) {
  const inCat = state.cat ? QUESTIONS.filter(q => q.cat === state.cat) : QUESTIONS;
  const controls = card({ title: 'Browse questions', subtitle: 'Choose a category and an order · ▶ plays an answer in the episode explorer' });
  const sort = h('select', { class: 'select', 'aria-label': 'Sort questions' }, Object.entries(SORTS).map(([key, it]) => h('option', { value: key, text: it.label })));
  sort.value = state.sort;
  const openings = h('input', { type: 'checkbox', checked: state.openings });
  // The openings in Roman Urdu or the English translation, the same choice as the episode transcript.
  const language = SCRIPTS.length > 1 ? segmented('Language of the openings', SCRIPTS.map(script => [SCRIPT_NAMES[script], script]), state.script, script => { setScript(script); update(); }) : null;
  // Each row of chips has its label in a column of its own, so chips that wrap line up under the first.
  const chipRow = (label, ...chips) => h('div', { class: 'chip-row' }, h('span', { class: 'chips-label', text: label }), h('div', { class: 'chips' }, chips));
  append(controls.body, [
    h('div', { class: 'controls' }, sort, h('label', { class: 'checkbox' }, openings, 'Show openings'), language),
    chipRow('Category', chipButton('All', QUESTIONS.length, !state.cat, () => setFilter('', '')),
      categoryItems(QUESTIONS).map(c => chipButton(c.label, c.value, state.cat === c.key, () => setFilter(c.key, ''), c.color))),
    state.cat ? chipRow('Subcategory', chipButton(`All of ${catName(state.cat)}`, inCat.length, !state.sub, () => setFilter(state.cat, '')),
      subItems(inCat, state.cat).map(sb => chipButton(sb.label, sb.value, state.sub === sb.key, () => setFilter(state.cat, sb.key)))) : null]);
  panel.append(controls.el);
  const results = h('div', { class: 'span-12' });
  panel.append(results);
  const update = () => {
    const list = inCat.filter(q => !state.sub || q.sub === state.sub).sort(SORTS[state.sort].compare);
    questionList(results, list, 24);
  };
  sort.addEventListener('change', () => { state.sort = sort.value; writeHash(); update(); });
  openings.addEventListener('change', () => { state.openings = openings.checked; update(); });
  update();
}

/* ---------- Insights ---------- */
function renderInsights(panel) {
  const qs = scopedQuestions();
  if (!qs.length) { panel.append(notice('No questions match this filter.')); return; }

  const groups = state.cat
    ? CAT.get(state.cat).subs.map(sb => ({ label: sb.name, color: sb.color, test: q => q.sub === sb.id }))
    : LIVE_CATS.map(c => ({ label: c.name, color: c.color, test: q => q.cat === c.id }));
  const rows = groups.map(g => ({ label: g.label, color: g.color, items: qs.filter(q => g.test(q) && q.length != null).map(q => ({ value: q.length / 60, q })) }))
    .filter(r => r.items.length >= 3).sort((a, b) => median(b.items.map(it => it.value)) - median(a.items.map(it => it.value)));
  const strip = card({ title: 'How long each subject is discussed', subtitle: 'One dot per question: minutes until the next question · the line marks the median · click a dot to play it',
    table: () => ({ columns: [{ label: 'Subject' }, { label: 'Timed answers', num: true }, { label: 'Median', num: true }, { label: 'Longest', num: true }],
      rows: rows.map(r => [r.label, fmtInt(r.items.length), fmtMinutes(median(r.items.map(it => it.value))), fmtMinutes(Math.max(...r.items.map(it => it.value)))]) }) });
  stripPlot(strip.body, { rows, onPick: openQuestion });
  panel.append(strip.el);

  // Rows of two cards of about the same height: time and age, then subjects, then places.
  const positions = positionItems(qs);
  const position = card({ title: 'Does the first question get the most time?', subtitle: 'Median minutes per answer by the question’s position in its episode', span: 'span-6', table: itemsTable('Position', positions, fmtMinutes) });
  ordinalColumns(position.body, { items: positions, format: v => fmt1(v), label: 'median minutes', height: 240 });
  const ageList = ageItems(qs), ages = qs.map(q => q.age).filter(Boolean);
  const agesCard = card({ title: 'How old are the askers?', subtitle: ages.length ? `${plural(ages.length, 'question')} state an age · median ${median(ages)}` : 'No ages stated in these questions', span: 'span-6', table: itemsTable('Age', ageList, fmtInt) });
  ordinalColumns(agesCard.body, { items: ageList, format: fmtInt, label: 'questions', height: 240 });
  panel.append(position.el, agesCard.el);

  // Medians alone differ by a few years, so each subject shows the middle half of its stated ages too.
  const ageRanges = (state.cat ? subItems(qs, state.cat) : categoryItems(qs).filter(it => it.key !== 'other')).map(it => {
    const list = qs.filter(q => (state.cat ? q.sub : q.cat) === it.key).map(q => q.age).filter(Boolean).sort((a, b) => a - b);
    return { key: it.key, label: it.label, color: it.color, n: list.length, median: median(list), low: quantile(list, 0.25), high: quantile(list, 0.75) };
  }).filter(it => it.n >= 4).sort((a, b) => b.median - a.median);
  const ageGroups = card({ title: 'Ages by subject', subtitle: 'The middle half of stated ages in each subject, and its median · subjects with at least four ages', span: 'span-6',
    legend: h('div', { class: 'legend' }, h('span', {}, h('span', { class: 'key-band' }), 'Middle half of the ages'), h('span', {}, h('span', { class: 'key-tick' }), 'Median')),
    table: () => ({ columns: [{ label: 'Subject' }, { label: 'Stated ages', num: true }, { label: 'Median', num: true }, { label: 'Middle half', num: true }],
      rows: ageRanges.map(it => [it.label, fmtInt(it.n), fmtInt(it.median), `${fmtInt(it.low)}–${fmtInt(it.high)}`]) }) });
  rangeList(ageGroups.body, { items: ageRanges });
  const pairs = pairItems(qs, state.cat);
  const pairCard = card({ title: state.cat ? 'Often comes with' : 'Subjects that come together', subtitle: 'Questions tagged with both categories', span: 'span-6', table: itemsTable('Pair', pairs, fmtInt) });
  barList(pairCard.body, { items: pairs.slice(0, Math.max(4, ageRanges.length)), format: fmtInt, valueLabel: 'questions' });
  panel.append(ageGroups.el, pairCard.el);

  // Cities rather than whole countries; the regions sum the countries and cities up.
  const cities = cityItems(qs).map(c => ({ ...c, note: c.country })), regions = regionItems(qs);
  const cityCard = card({ title: 'Cities mentioned', subtitle: 'Named in the title or the first 45 seconds, in Roman Urdu or the English translation', span: 'span-6', table: itemsTable('City', cities, fmtInt) });
  barList(cityCard.body, { items: cities.slice(0, Math.max(6, regions.length)), format: fmtInt, valueLabel: 'questions' });
  const regionCard = card({ title: 'By region', subtitle: 'Questions naming at least one place in each region', span: 'span-6', table: itemsTable('Region', regions, fmtInt) });
  barList(regionCard.body, { items: regions, format: fmtInt, valueLabel: 'questions' });
  panel.append(cityCard.el, regionCard.el);

  // What each subject's answers talk about: categories, or the subcategories of the chosen one.
  const subjects = (state.cat ? CAT.get(state.cat).subs.map(sb => ({ key: sb.id, label: sb.name, color: sb.color, cat: state.cat, sub: sb.id }))
    : TOPICS.map(c => ({ key: c.id, label: c.name, color: c.color, cat: c.id, sub: '' }))).filter(g => answerItems(g.key).length);
  if (subjects.length) {
    const map = card({ title: 'What the answers talk about', subtitle: 'The words that most set each subject’s answers apart, in the English translation · click a subject for the full list',
      table: () => ({ columns: [{ label: 'Subject' }, { label: 'Answers', num: true }, { label: 'Words that stand out' }],
        rows: subjects.map(g => [g.label, fmtInt(ANSWER_GROUPS[g.key].answers), ANSWER_GROUPS[g.key].words.map(([word]) => word).join(', ')]) }) });
    map.body.append(h('div', { class: 'word-map' }, subjects.map(g => h('div', { class: 'word-row', style: `--cat:${g.color}` },
      h('a', { class: 'word-subject', href: `#tab=categories&cat=${g.cat}${g.sub ? `&sub=${g.sub}` : ''}`, on: { click: ev => { ev.preventDefault(); go('categories', { cat: g.cat, sub: g.sub }); } } },
        h('span', { class: 'dot' }), g.label),
      h('div', { class: 'chips' }, answerItems(g.key).slice(0, 8).map(it => h('span', { class: 'tag', text: it.label,
        title: `Used in ${fmtPct(it.value)} of these answers and ${fmtPct(it.ref)} of all others` })))))));
    panel.append(map.el);
  }

  const keys = state.cat ? CAT.get(state.cat).subs.map(sb => sb.id) : TOPICS.flatMap(c => c.subs.map(sb => sb.id));
  const shifts = shiftItems(state.cat ? QUESTIONS.filter(q => q.cat === state.cat) : QUESTIONS, q => q.sub, keys, subName).filter(it => it.n >= 6).sort((a, b) => b.value - a.value);
  const movers = shifts.filter(it => it.value > 0).slice(0, 7).concat(shifts.filter(it => it.value < 0).slice(-7));
  // As many title words as there are movers beside them, so the two cards end level.
  const words = wordItems(qs);
  const wordCard = card({ title: 'Words in question titles', subtitle: 'The most frequent words, leaving out common English and Urdu ones', span: 'span-6', table: itemsTable('Word', words.slice(0, 40), fmtInt) });
  barList(wordCard.body, { items: words.slice(0, Math.max(6, movers.length)), format: fmtInt, valueLabel: 'titles' });
  const { firstLabel, secondLabel } = halves(EPISODES);
  const moverCard = card({ title: 'Rising and falling subcategories', subtitle: `Change in share of questions, ${firstLabel} vs ${secondLabel}`, span: 'span-6', legend: divergingLegend(firstLabel, secondLabel),
    table: () => ({ columns: [{ label: 'Subcategory' }, { label: 'First half', num: true }, { label: 'Second half', num: true }, { label: 'Change', num: true }], rows: shifts.map(it => [it.label, fmtPct(it.a, 1), fmtPct(it.b, 1), fmtPoints(it.value)]) }) });
  divergingBars(moverCard.body, { items: movers, onSelect: key => go('questions', { cat: SUB.get(key).cat, sub: key }) });
  panel.append(wordCard.el, moverCard.el);
}

/* ---------- Episodes ---------- */
function renderEpisodes(panel) {
  const qs = scopedQuestions(), counts = countBy(qs, q => q.ep), scope = scopeName();
  const color = state.cat ? colorOf(state.cat) : null;
  panel.append(
    episodeCard(EPISODES, { title: scope ? `${scope}: questions per episode` : 'Questions per episode', subtitle: 'Index entries per episode · click a column to open the episode', label: 'Questions',
      value: e => counts.get(e.n) || 0, format: fmtInt, color, span: 'span-6',
      extra: e => (QS_BY_EP.get(e.n) || []).filter(inScope).slice(0, 3).map(q => ({ value: `Q${q.order}`, label: shorten(q.title, 60) })) }),
    episodeCard(EPISODES, { title: 'Time per question', subtitle: 'Average minutes from one question to the next', label: 'Minutes per question', value: e => e.perQuestion, format: fmtMinutes, span: 'span-6' }),
    episodeCard(EPISODES, { title: 'Intro before the first question', subtitle: 'Minutes until the first indexed question', label: 'Intro', value: e => e.intro, format: fmtMinutes, span: 'span-6' }),
    episodeCard(EPISODES, { title: 'Episode length', subtitle: 'Minutes per episode', label: 'Length', value: e => e.lengthMin, format: fmtMinutes, span: 'span-6' }));
  const table = card({ title: 'All episodes', subtitle: 'Sort by any column · subjects are the categories of each episode’s questions' });
  dataTable(table.body, {
    rows: EPISODES, sortKey: 'n', sortDir: 'desc', pageSize: 50, cls: 'episode-table',
    columns: [
      { key: 'n', label: 'Ep', num: true, width: '62px', sort: e => e.n, firstDir: 'desc', render: e => episodeLink(e.n, String(e.n)) },
      { key: 'len', label: 'Length', num: true, width: '92px', sort: e => e.duration, render: e => fmtClock(e.duration) },
      { key: 'q', label: scope ? 'Matching' : 'Questions', num: true, width: '112px', sort: e => scope ? counts.get(e.n) || 0 : e.questions, render: e => fmtInt(scope ? counts.get(e.n) || 0 : e.questions) },
      { key: 'subjects', label: 'Subjects', width: '30%', sort: null, render: e => h('div', { class: 'tag-list' }, [...countBy(e.qs, q => q.cat).entries()].sort((a, b) => b[1] - a[1]).slice(0, 4)
        .map(([c, n]) => h('span', { class: 'tag', style: catStyle(c) }, h('span', { class: 'dot' }), `${catName(c)}${n > 1 ? ` ×${n}` : ''}`))) },
      { key: 'pq', label: 'Min / question', num: true, width: '108px', sort: e => e.perQuestion, render: e => e.perQuestion == null ? '–' : fmt1(e.perQuestion) },
      { key: 'intro', label: 'Intro', num: true, width: '82px', sort: e => e.firstQuestion, render: e => e.firstQuestion == null ? '–' : fmtClock(e.firstQuestion) },
      { key: 'sig', label: 'Signature words', sort: null, render: e => h('span', { class: 'sig-words', text: e.signature.join(', ') }) },
      { key: 'watch', label: 'Watch', num: true, width: '96px', sort: null, render: e => h('button', { class: 'q-play', type: 'button', text: '▶ Play', on: { click: () => openEpisode(e.n, { play: true }) } }) },
    ],
  });
  panel.append(table.el);
}

/* ---------- Transcripts: data/transcripts(-english)/episode_NNN.js call GANJI_TRANSCRIPT ----------
   Roman Urdu always; English when the build found it (DATA.meta.scripts). */
const SCRIPT_NAMES = { roman: 'Roman Urdu', english: 'English' };
const SCRIPTS = (DATA.meta.scripts || ['roman']).filter(s => SCRIPT_NAMES[s]);
const transcriptCache = new Map();
const transcriptWaiting = new Map();
window.GANJI_TRANSCRIPT = (n, cues, script = 'roman') => {
  const resolve = transcriptWaiting.get(`${script}:${n}`);
  transcriptWaiting.delete(`${script}:${n}`);
  if (resolve) resolve({ cues: cues.map(([start, text]) => ({ start, text })) });
};
function loadTranscript(n, script = 'roman') {
  const id = `${script}:${n}`;
  if (!transcriptCache.has(id)) {
    const promise = new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      tag.src = `data/${script === 'roman' ? 'transcripts' : `transcripts-${script}`}/episode_${String(n).padStart(3, '0')}.js`;
      transcriptWaiting.set(id, resolve);
      tag.onload = () => {
        tag.remove();
        if (transcriptWaiting.delete(id)) reject(new Error(`${tag.src} did not contain a transcript`));
      };
      tag.onerror = () => {
        tag.remove();
        transcriptWaiting.delete(id);
        reject(new Error(`could not load ${tag.src}`));
      };
      document.head.append(tag);
    });
    promise.catch(() => transcriptCache.delete(id));
    transcriptCache.set(id, promise);
  }
  return transcriptCache.get(id);
}
function cueText(text) {
  return text.split(/(\[[a-z]+\])/i).filter(Boolean).map(part => /^\[[a-z]+\]$/i.test(part) ? h('span', { class: 'sound', text: part }) : part);
}

/* ---------- YouTube player: the IFrame API, loaded once on demand ---------- */
let youtubeApi = null;
function loadYouTubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
  if (!youtubeApi) {
    youtubeApi = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('The YouTube player did not load.')), 20000);
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        clearTimeout(timer);
        if (typeof previous === 'function') previous();
        resolve(window.YT);
      };
      const script = h('script', { src: 'https://www.youtube.com/iframe_api', async: true });
      script.onerror = () => { clearTimeout(timer); reject(new Error('The YouTube player could not be reached.')); };
      document.head.append(script);
    });
    youtubeApi.catch(() => { youtubeApi = null; });
  }
  return youtubeApi;
}
// YouTube refuses to embed into pages opened from disk (error 153), so the player needs http(s).
const canEmbed = () => /^https?:$/.test(location.protocol);
function playerError(code) {
  if (code === 100) return 'This video is private or no longer on YouTube.';
  if (code === 101 || code === 150) return 'The video’s owner does not allow it to play on other sites.';
  if (code === 153) return 'YouTube needs this page to be served over http(s) to play here.';
  return 'The video could not be played here.';
}

/* ---------- Episode explorer: player, live transcript and timeline ---------- */
let session = null;
function endSession() {
  if (!session) return;
  clearInterval(session.timer);
  try { if (session.player && session.player.destroy) session.player.destroy(); } catch (error) { /* already gone */ }
  session = null;
}
function questionIndex(timed, t) {
  let i = -1;
  while (i + 1 < timed.length && timed[i + 1].start <= t + 0.5) i++;
  return i;
}
function iconButton(label, d) {
  return h('button', { class: 'icon-button', type: 'button', 'aria-label': label, title: label }, icon(d));
}
function nowPlaying(e, timed, seek, getTime) {
  const badge = h('span', { class: 'now-badge' });
  const title = h('span', { class: 'now-title' });
  const meta = h('div', { class: 'now-meta' });
  const clock = h('span', { class: 'now-time' });
  const fill = h('span');
  const prev = iconButton('Previous question', 'M6 6v12M18 6l-9 6 9 6z');
  const next = iconButton('Next question', 'M18 6v12M6 6l9 6-9 6z');
  const el = h('div', { class: 'now-playing' },
    h('div', { class: 'now-main' },
      h('div', { class: 'now-line' }, badge, title),
      h('div', { class: 'now-sub' }, meta, clock),
      h('div', { class: 'now-progress' }, fill)),
    h('div', { class: 'now-nav' }, prev, next));
  let shown;
  function update(t) {
    const i = questionIndex(timed, t), q = i >= 0 ? timed[i] : null;
    if (q !== shown || shown === undefined) {
      shown = q;
      badge.textContent = q ? `Q${q.order} of ${e.qs.length}` : timed.length ? 'Intro' : `Episode ${e.n}`;
      title.textContent = q ? q.title : timed.length ? `First question at ${fmtClock(timed[0].start)}` : 'No timed questions in this episode';
      meta.replaceChildren(q ? subTag(q) : '');
    }
    const from = q ? q.start : 0;
    const to = q ? (q.length != null ? q.start + q.length : e.duration) : (timed.length ? timed[0].start : e.duration);
    fill.style.width = `${Math.max(0, Math.min(100, (t - from) / Math.max(1, to - from) * 100)).toFixed(1)}%`;
    clock.textContent = `${fmtClock(t)} / ${fmtClock(e.duration)}`;
    prev.disabled = !q;
    next.disabled = i >= timed.length - 1;
  }
  prev.addEventListener('click', () => {
    const t = getTime(), i = questionIndex(timed, t), q = timed[i];
    const target = q && t - q.start > 4 ? q : timed[i - 1];
    seek(target ? target.start : 0, { q: target || null });
  });
  next.addEventListener('click', () => {
    const target = timed[questionIndex(timed, getTime()) + 1];
    if (target) seek(target.start, { q: target });
  });
  return { el, update };
}
function segmentChart(container, e, timed, onPick) {
  let playhead = null, W = 0, at = 0, current = null;
  const segments = new Map();
  function setTime(t) {
    at = t;
    if (playhead) {
      const x = r2(Math.max(1, Math.min(W - 1, t / e.duration * W)));
      playhead.setAttribute('x1', x);
      playhead.setAttribute('x2', x);
    }
    const q = timed[questionIndex(timed, t)] || null;
    if (q !== current) {
      if (segments.get(current)) segments.get(current).classList.remove('current');
      current = q;
      if (segments.get(q)) segments.get(q).classList.add('current');
    }
  }
  function draw() {
    container.replaceChildren();
    segments.clear();
    W = Math.max(260, container.clientWidth);
    const H = 52, top = 4, height = 26;
    const X = t => Math.max(0, Math.min(W, t / e.duration * W));
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `Timeline of episode ${e.n}` });
    const add = (start, end, style, label, tip, q) => {
      const x = X(start) + 1, w = Math.max(1, X(end) - X(start) - 2);
      const rect = s('rect', { class: q ? 'seg' : 'seg intro', x: r2(x), y: top, width: r2(w), height, rx: 3, style, tabindex: '0' });
      attachTip(rect, tip);
      rect.addEventListener('click', () => { hideTip(); onPick(q, start); });
      rect.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onPick(q, start); } });
      svg.append(rect);
      if (q) segments.set(q, rect);
      if (w > 26 && label) svg.append(s('text', { class: 'seg-label', x: r2(x + w / 2), y: top + height + 16, 'text-anchor': 'middle' }, label));
    };
    if (timed.length && timed[0].start > 0) add(0, timed[0].start, null, 'Intro', () => ['Intro before the first question', [{ value: fmtDuration(timed[0].start), label: 'from the start' }], 'Click to play from the start'], null);
    for (const q of timed) {
      const end = q.length != null ? q.start + q.length : e.duration;
      add(q.start, end, `fill:${colorOf(q.cat)}`, `Q${q.order}`, () => [`Q${q.order} · ${q.title}`, [
        { value: fmtClock(q.start), label: 'starts', color: colorOf(q.cat) },
        { value: q.length == null ? '–' : fmtDuration(q.length), label: 'until the next question' },
        { value: `${q.catName} › ${q.subName}`, label: '' }], 'Click to play this answer'], q);
    }
    if (!timed.length) add(0, e.duration, null, 'No timed questions', () => [`Episode ${e.n}`, [{ value: fmtDuration(e.duration), label: 'long' }]], null);
    playhead = s('line', { class: 'playhead', x1: 0, x2: 0, y1: 0, y2: top + height + 4 });
    svg.append(playhead);
    container.append(svg);
    current = null;
    setTime(at);
  }
  registerChart(draw);
  return { setTime };
}
function paceChart(container, e, timed, onSeek) {
  let playhead = null, X = null, at = 0;
  function setTime(t) {
    at = t;
    if (playhead && X) {
      const x = r2(X(Math.min(e.minutes.length - 1, t / 60)));
      playhead.setAttribute('x1', x);
      playhead.setAttribute('x2', x);
    }
  }
  function draw() {
    container.replaceChildren();
    const values = e.minutes;
    const W = Math.max(260, container.clientWidth), H = 190;
    const m = { t: 18, r: 8, b: 22, l: 42 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b;
    const n = values.length;
    const { max, ticks } = niceTicks(Math.max(...values), 4);
    X = i => m.l + (n > 1 ? i / (n - 1) * pw : pw / 2);
    const Y = v => m.t + ph - (v / max) * ph;
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': `Words per minute across episode ${e.n}` });
    for (const t of ticks) {
      svg.append(s('line', { class: t === 0 ? 'baseline' : 'gridline', x1: m.l, x2: W - m.r, y1: r2(Y(t)), y2: r2(Y(t)) }));
      svg.append(s('text', { class: 'tick', x: m.l - 6, y: Y(t) + 4, 'text-anchor': 'end' }, fmtInt(t)));
    }
    const every = [1, 2, 5, 10, 15, 30, 60].find(k => k / Math.max(1, n - 1) * pw >= 44) || 60;
    for (let i = 0; i < n; i += every) svg.append(s('text', { class: 'tick', x: r2(X(i)), y: H - 5, 'text-anchor': 'middle' }, fmtClock(i * 60).replace(/:00$/, '')));
    for (const q of timed) {
      const x = X(q.start / 60);
      svg.append(s('line', { class: 'marker-line', x1: r2(x), x2: r2(x), y1: m.t - 4, y2: m.t + ph }));
      if (timed.length <= 14) svg.append(s('text', { class: 'marker-label', x: r2(x + 3), y: m.t - 6 }, `Q${q.order}`));
    }
    const points = values.map((v, i) => [X(i), Y(v)]);
    svg.append(s('path', { class: 'area', d: `${linePath(points)}L${r2(X(n - 1))},${r2(Y(0))}L${r2(X(0))},${r2(Y(0))}Z` }));
    svg.append(s('path', { class: 'trend', d: linePath(points) }));
    const cross = s('line', { class: 'crosshair', x1: 0, x2: 0, y1: m.t, y2: m.t + ph, visibility: 'hidden' });
    const dot = s('circle', { class: 'end-dot', r: 4, cx: -10, cy: -10, visibility: 'hidden' });
    playhead = s('line', { class: 'playhead', x1: 0, x2: 0, y1: m.t - 2, y2: m.t + ph });
    const hit = s('rect', { class: 'hit-area clickable', x: m.l, y: 0, width: pw, height: m.t + ph });
    svg.append(playhead, cross, dot, hit);
    container.append(svg);
    const minuteAt = ev => {
      const box = svg.getBoundingClientRect();
      const x = (ev.clientX - box.left) * (W / box.width);
      return Math.max(0, Math.min(n - 1, Math.round((x - m.l) / pw * (n - 1))));
    };
    hit.addEventListener('pointermove', ev => {
      const i = minuteAt(ev);
      cross.setAttribute('x1', r2(X(i))); cross.setAttribute('x2', r2(X(i))); cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', r2(X(i))); dot.setAttribute('cy', r2(Y(values[i]))); dot.setAttribute('visibility', 'visible');
      const current = timed[questionIndex(timed, i * 60 + 30)];
      showTip(ev, `Minute ${fmtClock(i * 60)}–${fmtClock(i * 60 + 60)}`, [{ value: fmtInt(values[i]), label: 'words', color: 'var(--acc-hi)' }],
        [current ? `Q${current.order}: ${current.title}` : 'Before the first question', 'Click to play from here']);
    });
    hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); hideTip(); });
    hit.addEventListener('click', ev => { hideTip(); onSeek(minuteAt(ev) * 60); });
    setTime(at);
  }
  registerChart(draw);
  return { setTime };
}
async function mountTranscript(box, sess, timed, seek, script = 'roman') {
  const e = sess.e;
  box.replaceChildren(h('p', { class: 'muted', text: 'Loading transcript…' }));
  let t;
  try { t = await loadTranscript(e.n, script); } catch (error) {
    box.replaceChildren(h('p', { class: 'notice' }, h('strong', { text: `The ${SCRIPT_NAMES[script]} transcript of this episode is not in data/. ` }),
      'Run ', h('code', { text: 'bash app/run.sh' }), ' to generate it, then reload this page.'));
    return null;
  }
  if (session !== sess) return null;
  const list = h('div', { class: `transcript ${script}`, tabindex: '0', 'aria-label': `Transcript of episode ${e.n}`,
    lang: script === 'english' ? 'en' : null });
  const rows = [], starts = [], headers = new Map();
  let qi = 0;
  for (const c of t.cues) {
    while (qi < timed.length && c.start >= timed[qi].start - 0.5) {
      const q = timed[qi];
      const header = h('div', { class: 'cue-question', style: catStyle(q.cat) }, h('span', { class: 'dot' }), h('span', { text: `Q${q.order} · ${q.title}` }));
      headers.set(q, header);
      list.append(header);
      qi++;
    }
    const time = h('button', { class: 'cue-time', type: 'button', text: fmtClock(c.start), title: sess.live ? 'Play from this line' : 'Open YouTube at this line',
      on: { click: () => seek(Math.max(0, c.start - (sess.live ? 0.3 : 2)), { external: true }) } });
    const row = h('div', { class: 'cue' }, time, h('span', { class: 'cue-text' }, cueText(c.text)));
    rows.push(row);
    starts.push(c.start);
    list.append(row);
  }
  const followButton = h('button', { class: 'primary-button follow-button', type: 'button', hidden: true, text: '↓ Follow the video' });
  box.replaceChildren(list, followButton);

  let current = -1, following = true, jump = true;
  function keepInView(row, instant) {
    const top = row.offsetTop, view = list.clientHeight, at = list.scrollTop;
    if (!instant && top >= at + view * 0.12 && top + row.offsetHeight <= at + view * 0.62) return;
    list.scrollTo({ top: Math.max(0, top - view * 0.3), behavior: instant ? 'auto' : 'smooth' });
  }
  function update(time) {
    let lo = 0, hi = starts.length - 1, idx = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (starts[mid] <= time + 0.2) { idx = mid; lo = mid + 1; } else hi = mid - 1;
    }
    if (idx !== current) {
      if (current >= 0) rows[current].classList.remove('current');
      current = idx;
      if (idx >= 0) rows[idx].classList.add('current');
    }
    if (idx >= 0 && following && sess.live) { keepInView(rows[idx], jump); jump = false; }
  }
  const stopFollowing = () => {
    if (!following || !sess.live) return;
    following = false;
    followButton.hidden = false;
  };
  list.addEventListener('wheel', stopFollowing, { passive: true });
  list.addEventListener('touchmove', stopFollowing, { passive: true });
  list.addEventListener('keydown', ev => { if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(ev.key)) stopFollowing(); });
  list.addEventListener('pointerdown', ev => { if (ev.target === list) stopFollowing(); });
  followButton.addEventListener('click', () => {
    following = true;
    jump = true;
    followButton.hidden = true;
    update(sess.time);
  });

  sess.followers.push(update);
  update(sess.time);
  return {
    detach() { sess.followers = sess.followers.filter(fn => fn !== update); },
    follow() { following = true; jump = true; followButton.hidden = true; },
    showQuestion(q) {
      const header = headers.get(q);
      if (!header) return;
      const anchor = header.nextElementSibling || header;
      // Headers are sticky, so measure from the first line after the header instead.
      list.scrollTop = Math.max(0, anchor.offsetTop - header.offsetHeight - 2);
      header.classList.add('flash');
      setTimeout(() => header.classList.remove('flash'), 1200);
    },
  };
}
function playerFallback(frame, sess, message, now) {
  const e = sess.e;
  sess.live = false;
  sess.ready = false;
  clearInterval(sess.timer);
  try { if (sess.player && sess.player.destroy) sess.player.destroy(); } catch (error) { /* already gone */ }
  sess.player = null;
  if (now) now.el.hidden = true;
  const url = watchUrl(e.n, sess.time || null);
  frame.replaceChildren(h('div', { class: 'player-fallback', style: e.video ? `background-image:linear-gradient(rgba(0,0,0,.7),rgba(0,0,0,.85)),url(https://i.ytimg.com/vi/${encodeURIComponent(e.video)}/hqdefault.jpg)` : null },
    h('strong', { text: `Episode ${e.n}` }),
    h('span', { text: message }),
    url ? h('a', { class: 'primary-button', href: url, target: '_blank', rel: 'noopener', text: 'Watch on YouTube ↗' }) : null));
}
function mountPlayer(frame, sess, startAt, autoplay, now, tick) {
  const target = h('div');
  frame.replaceChildren(target);
  loadYouTubeApi().then(YT => {
    if (session !== sess) return;
    sess.player = new YT.Player(target, {
      host: 'https://www.youtube-nocookie.com',
      videoId: sess.e.video,
      width: '100%',
      height: '100%',
      playerVars: { playsinline: 1, rel: 0, modestbranding: 1, start: Math.floor(startAt), autoplay: autoplay ? 1 : 0, origin: location.origin },
      events: {
        onReady: () => {
          if (session !== sess) return;
          sess.ready = true;
          if (sess.pending != null) { sess.player.seekTo(sess.pending, true); sess.player.playVideo(); sess.pending = null; }
          else if (autoplay) sess.player.playVideo();
        },
        onStateChange: ev => {
          if (session !== sess) return;
          if (ev.data === YT.PlayerState.PAUSED || ev.data === YT.PlayerState.ENDED) { state.t = Math.floor(sess.time); writeHash(); }
        },
        onError: ev => { if (session === sess) playerFallback(frame, sess, `${playerError(ev.data)} You can still read the transcript here.`, now); },
      },
    });
    // The IFrame API has no time events, so poll the playhead four times a second.
    sess.timer = setInterval(() => {
      if (session !== sess || !sess.ready) return;
      let t;
      try { t = sess.player.getCurrentTime(); } catch (error) { return; }
      if (Number.isFinite(t) && Math.abs(t - sess.time) > 0.05) tick(t);
    }, 250);
  }).catch(error => { if (session === sess) playerFallback(frame, sess, `${error.message} Times in the transcript open YouTube instead.`, now); });
}
function renderEpisode(panel) {
  const e = BY_EP.get(state.ep) || EPISODES[EPISODES.length - 1];
  state.ep = e.n;
  const index = EPISODES.indexOf(e);
  const timed = e.qs.filter(q => q.start != null).sort((a, b) => a.start - b.start);
  const focusQ = state.focus ? e.qs.find(q => q.order === state.focus) : null;
  const startAt = state.t != null ? state.t : focusQ && focusQ.start != null ? focusQ.start : 0;
  const autoplay = state.play;
  state.focus = 0;
  state.play = false;
  const sess = session = { e, live: !!e.video && canEmbed(), player: null, ready: false, timer: 0, time: startAt, pending: null, followers: [] };
  const tick = t => { sess.time = t; for (const fn of sess.followers) fn(t); };
  let transcript = null;
  function seek(t, { q = null, external = false } = {}) {
    if (sess.live) {
      if (transcript) transcript.follow();
      if (sess.ready) { sess.player.seekTo(t, true); sess.player.playVideo(); } else sess.pending = t;
      tick(t);
    } else if (q && transcript && !external) transcript.showQuestion(q);
    else if (watchUrl(e.n, t)) window.open(watchUrl(e.n, t), '_blank', 'noopener');
  }

  const select = h('select', { class: 'select', 'aria-label': 'Choose an episode' },
    EPISODES.slice().reverse().map(x => h('option', { value: x.n, text: `Episode ${x.n} · ${fmtDuration(x.duration)} · ${plural(x.questions, 'question')}` })));
  select.value = String(e.n);
  select.addEventListener('change', () => openEpisode(Number(select.value)));
  const step = d => h('button', { class: 'ghost-button', type: 'button', disabled: !EPISODES[index + d], text: d < 0 ? '← Previous' : 'Next →', on: { click: () => openEpisode(EPISODES[index + d].n) } });
  panel.append(h('div', { class: 'episode-picker' }, step(-1), select, step(1), youtubeLink(e.n, null, 'Open on YouTube ↗', 'ghost-button')));

  const frame = h('div', { class: 'player-frame' });
  const now = nowPlaying(e, timed, seek, () => sess.time);
  const timelineBox = h('div', { class: 'chart' });
  const playerCard = h('section', { class: 'card player-card' }, frame, now.el,
    h('div', { class: 'card-head' }, h('div', { class: 'card-titles' }, h('h3', { text: 'Timeline' }),
      h('p', { class: 'subtitle', text: 'The intro, then each question until the next one, coloured by category · click a block to play it' }))),
    timelineBox);
  const timeline = segmentChart(timelineBox, e, timed, (q, start) => seek(q ? q.start : start, { q }));
  sess.followers.push(now.update, timeline.setTime);

  const qCard = card({ title: plural(e.qs.length, 'question'), subtitle: e.qs.length ? 'Click a question to play its answer · tags list similar questions' : 'This episode has no index entries' });
  const qRows = new Map(), openingLines = [];
  qCard.body.append(h('div', { class: 'question-list' }, e.qs.map(q => {
    // The opening follows the transcript language, so it is kept to update when that changes.
    const opening = excerptOf(q) ? h('div', { class: 'excerpt', text: excerptOf(q) }) : null;
    if (opening) openingLines.push([q, opening]);
    const row = h('div', { class: 'question-item', style: catStyle(q.cat) },
      h('span', { class: 'question-number', text: `Q${q.order}` }),
      h('div', {},
        h('div', { class: 'question-title' }, h('button', { type: 'button', text: q.title, on: { click: () => seek(q.start, { q }) } })),
        h('div', { class: 'q-meta' }, subTag(q), q.also.map(code => h('span', { class: 'tag', text: subName(code) })),
          q.age ? h('span', { class: 'tag', text: `age ${q.age}` }) : null, q.places.map(i => h('span', { class: 'tag', text: PLACES[i].name }))),
        opening),
      h('div', { class: 'num' },
        q.start == null ? h('span', { class: 'muted', text: 'No time' })
          : h('button', { class: 'q-play', type: 'button', text: `▶ ${fmtClock(q.start)}`, on: { click: () => seek(q.start, { q, external: true }) } }),
        h('div', { class: 'muted', text: q.length == null ? '' : fmtDuration(q.length) })));
    qRows.set(q, row);
    return row;
  })));
  let activeQ = null;
  sess.followers.push(t => {
    const q = timed[questionIndex(timed, t)] || null;
    if (q === activeQ) return;
    if (qRows.get(activeQ)) qRows.get(activeQ).classList.remove('active');
    activeQ = q;
    if (qRows.get(q)) qRows.get(q).classList.add('active');
  });

  const facts = card({ title: 'Episode facts' });
  facts.body.append(h('div', { class: 'mini-kpis' },
    kpi('Length', fmtDuration(e.duration), `${fmtInt(e.cues)} subtitle lines`),
    kpi('Questions', fmtInt(e.questions), e.firstQuestion != null ? `first at ${fmtClock(e.firstQuestion)}` : 'no timestamps'),
    kpi('Per question', fmtMinutes(e.perQuestion), 'on average'),
    kpi('Words', fmtCompact(e.words), `${fmtInt(e.pace)} per spoken minute`),
    e.englishShare != null ? kpi('English', fmtPct(e.englishShare), `${fmtPct(1 - e.englishShare)} Urdu`) : null,
    kpi('Laughter', fmtInt(e.laughs), `${fmt1(e.laughRate)} per hour`)));
  const pace = card({ title: 'Words per minute', subtitle: 'How densely it is spoken, minute by minute · lines mark questions · click to play from there' });
  const paceView = paceChart(pace.body, e, timed, t => seek(t, { external: true }));
  sess.followers.push(paceView.setTime);

  const words = card({ title: 'Words', subtitle: 'Signature words are unusually frequent in this episode' });
  words.body.append(h('div', { class: 'chips' }, e.signature.length
    ? e.signature.map(w => h('span', { class: 'tag', text: w }))
    : h('span', { class: 'muted', text: 'None found' })));
  const commonBox = h('div');
  words.body.append(h('h4', { class: 'section-label', text: 'Most used content words' }), commonBox);
  barList(commonBox, { items: e.topList.slice(0, 10).map(([i, c]) => ({ key: i, label: VOCAB[i], value: c, lang: VOCAB_LANG ? (VOCAB_LANG[i] === 'e' ? 'EN' : 'UR') : null })), format: fmtInt, valueLabel: 'uses' });

  const box = h('div', { class: 'transcript-box' });
  const transcriptActions = h('div', { class: 'card-actions' });
  const transcriptCard = h('section', { class: 'card transcript-card' },
    h('div', { class: 'card-head' }, h('div', { class: 'card-titles' }, h('h3', { text: 'Transcript' }),
      h('p', { class: 'subtitle', text: sess.live ? 'Follows the video as it plays · click a time to jump there' : 'Subtitles · times open YouTube' })),
    transcriptActions),
    box);
  // Roman Urdu or English: the choice is kept for the next episode and in the link.
  const showScript = script => {
    if (transcript) transcript.detach();
    transcript = null;
    mountTranscript(box, sess, timed, seek, script).then(view => { if (session === sess && state.script === script) transcript = view; });
  };
  if (SCRIPTS.length > 1) {
    transcriptActions.append(segmented('Transcript language', SCRIPTS.map(s => [SCRIPT_NAMES[s], s]), state.script, script => {
      setScript(script);
      writeHash();
      showScript(script);
      for (const [q, line] of openingLines) line.textContent = excerptOf(q);
    }));
  }
  panel.append(h('div', { class: 'stack span-7' }, playerCard, qCard.el, facts.el, pace.el, words.el), h('div', { class: 'side span-5' }, transcriptCard));

  if (sess.live) mountPlayer(frame, sess, startAt, autoplay, now, tick);
  else playerFallback(frame, sess, e.video ? 'The built-in player works when the app is served over http(s): on the published site, or locally with bash app/run.sh --serve.' : 'No video is linked to this episode.', now);
  tick(startAt);
  mountTranscript(box, sess, timed, seek, state.script).then(view => {
    transcript = view;
    if (view && focusQ && !sess.live) view.showQuestion(focusQ);
  });
}

/* ---------- About ---------- */
// A card whose body stays folded away until asked for: reference tables that would crowd the page.
function foldCard({ title, subtitle }, content) {
  const c = card({ title, subtitle });
  c.body.hidden = true;
  const button = h('button', { class: 'small-button', type: 'button', 'aria-expanded': 'false', text: 'Show' });
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? 'Hide' : 'Show';
    if (open && !c.body.childElementCount) c.body.append(content());
    c.body.hidden = !open;
  });
  c.actions.append(button);
  return c.el;
}
function renderAbout(panel) {
  const meta = DATA.meta, quality = DATA.quality;
  const english = SCRIPTS.includes('english');
  const sorted = QUESTIONS.filter(x => !x.sub.endsWith('.auto')).length;
  const intro = card({ title: 'About this app' });
  intro.body.append(
    h('p', { class: 'about-lead' }, 'An unofficial, fan-made analysis of the ', strong(`${fmtInt(meta.questions)} viewer questions`),
      ` answered on Ask Ganji Swag across ${fmtInt(meta.episodes)} episodes (${fmt1(meta.seconds / 3600)} hours). See what viewers ask about, how that changed over the years and what was said in reply, with every answer one click away from its moment in the video.`),
    h('p', { class: 'about-credit' }, 'Made by ', strong('Reeyan-Afzal-Khan'), ' and not affiliated with the show. All episode content belongs to its creators; videos play from YouTube, and this site hosts no video or audio. ',
      h('a', { href: meta.playlist, target: '_blank', rel: 'noopener', text: 'Full playlist on YouTube ↗' })));

  // A tile for each section, in sidebar order, then the moves that work everywhere.
  const tiles = [
    ['overview', 'The big picture: what viewers ask about, how subjects changed over the years, and the key findings.'],
    ['categories', 'Every category and its subcategories, how subjects connect, and what their answers talk about.'],
    ['questions', `All ${fmtInt(meta.questions)} questions by subject, each with its opening${english ? ' in Roman Urdu or English' : ''} and ▶ to play the answer.`],
    ['insights', 'How long answers run, who asks (ages and cities), and the words that set each subject apart.'],
    ['episodes', `Length, pace and subjects of all ${fmtInt(meta.episodes)} episodes, as charts and a sortable table.`],
    ['episode', `An episode’s video with a transcript${english ? ' in Roman Urdu or English' : ''} that follows along, and its questions.`],
  ];
  const guide = card({ title: 'How to use this app', subtitle: 'Six sections, listed in the sidebar · pick a tile to open one' });
  guide.body.append(
    h('div', { class: 'guide-grid' }, tiles.map(([tab, text]) => h('button', { class: 'guide-tile', type: 'button', on: { click: () => go(tab) } },
      h('span', { class: 'guide-icon' }, icon(SECTIONS[tab].icon)), h('span', { class: 'guide-name', text: SECTIONS[tab].label }), h('span', { class: 'guide-text', text })))),
    h('h4', { class: 'section-label', text: 'Tips' }),
    h('ul', { class: 'tips' },
      h('li', {}, strong('Focus on a subject'), ': pick a category or subcategory under Categories in the sidebar; Overview, Questions, Insights and Episodes follow it.'),
      h('li', {}, strong('Click the charts'), ': slices, bars and columns filter the page or open the question or episode behind them.'),
      h('li', {}, strong('See exact numbers'), ': every chart has a Table button.'),
      h('li', {}, strong('Play any moment'), ': a ▶ time opens the episode explorer and plays from that point.'),
      h('li', {}, strong('Share a view'), ': the address keeps the page, the filter and the playback time.'),
      h('li', {}, strong('Light or dark'), ': switch the theme at the bottom of the sidebar.')));
  panel.append(intro.el, guide.el);

  const made = card({ title: 'How the data was made', span: 'span-6' });
  made.body.append(h('ol', { class: 'steps' },
    h('li', {}, h('span', {}, strong('Questions'), ': a hand-made episode index lists every question with a link to its moment in the video.')),
    h('li', {}, h('span', {}, strong('Transcripts'), ': CrisperWhisper speech recognition, converted word by word to Roman Urdu with English kept as spoken.')),
    english ? h('li', {}, h('span', {}, strong('English'), ': CrisperWhisper also translated every episode into English, straight from the audio.')) : null,
    h('li', {}, h('span', {}, strong('Categories'), `: each question has one hand-checked subcategory, plus a second subject when it clearly covers one; ${TOPICS.length} categories hold ${SUBTOPIC_COUNT} subcategories.`))));
  const limits = card({ title: 'Keep in mind', span: 'span-6' });
  limits.body.append(h('ul', { class: 'notes' },
    h('li', { text: 'Transcripts are machine-made: names and rare words can be misheard or spelled two ways (shaadi, shadi).' }),
    english ? h('li', { text: 'The English is a machine translation that can drop or invent a phrase, so figures drawn from it are close rather than exact.' }) : null,
    h('li', { text: 'Categories are one reader’s judgement of short titles and openings; many questions could sit in two places.' }),
    h('li', { text: 'Transcripts follow the video by their subtitle timings, which can drift by a second or two.' })));
  panel.append(made.el, limits.el);

  const terms = [
    ['Answer length', 'Time from a question to the next one, or to the end of the episode, including reading the question out.'],
    ['Asker age', `An age stated in the title or the first 90 seconds${english ? ', or said in the first person (“I am 24”) in the English translation' : ''}.`],
    ['Places', `Cities and countries named in the title or the first 45 seconds${english ? ', in Roman Urdu or English' : ''}. Comment segments are left out of ages and places.`],
    ['Second subject', 'The extra tag a question carries when it clearly covers a second subject. The flows on the Categories pages follow it.'],
    english ? ['Answer words', 'The words that most set a subject’s answers apart from all others in the English translation. Bars show the share of its answers using a word; ticks, the share of other answers.'] : null,
    ['Rising and falling', 'A subject’s share of questions in the second half of all episodes minus its share in the first half, in percentage points.'],
    ['Signature words', 'Words unusually frequent in one episode’s transcript compared with the others (TF-IDF).'],
    ['English share', 'Words the recogniser wrote in Latin script. Loanwords it wrote in Urdu script count as Urdu.'],
  ].filter(Boolean);
  const measures = card({ title: 'What the measures mean' });
  measures.body.append(h('dl', { class: 'terms' }, terms.map(([term, text]) => h('div', {}, h('dt', { text: term }), h('dd', { text })))));
  panel.append(measures.el);

  // Reference tables, folded away until asked for.
  panel.append(foldCard({ title: 'Categories and subcategories', subtitle: 'Every subcategory, with what it covers and its number of questions' }, () => h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Category', 'Subcategory', 'What it covers'].map(label => h('th', { scope: 'col', text: label })), h('th', { scope: 'col', class: 'num', text: 'Questions' }), h('th', { scope: 'col', class: 'num', text: 'Share of category' }))),
    h('tbody', {}, LIVE_CATS.flatMap(c => c.subs.map((sb, i) => h('tr', {},
      h('td', {}, i ? '' : h('span', { class: 'tax-cat', style: `--cat:${c.color}` }, h('span', { class: 'dot' }), c.name)),
      h('td', {}, h('a', { href: `#tab=questions&cat=${c.id}&sub=${sb.id}`, on: { click: ev => { ev.preventDefault(); go('questions', { cat: c.id, sub: sb.id }); } } }, sb.name)),
      h('td', { class: 'muted', text: sb.description }),
      h('td', { class: 'num', text: fmtInt(SUB_COUNTS.get(sb.id)) }),
      h('td', { class: 'num', text: fmtShare(SUB_COUNTS.get(sb.id) / CAT_COUNTS.get(c.id)) })))))))));

  const missingStart = QUESTIONS.filter(x => x.start == null);
  const replacement = EPISODES.filter(e => e.replacement);
  panel.append(foldCard({ title: 'Data checks', subtitle: 'Checks on the inputs behind these numbers' }, () => h('div', { class: 'table-wrap' }, simpleTable({ columns: [{ label: 'Check' }, { label: 'Result' }], rows: [
    ['Episodes with transcripts', fmtInt(EPISODES.length)],
    ['Questions categorised by hand', `${fmtInt(sorted)} of ${fmtInt(QUESTIONS.length)}`],
    ['Episodes placed by keywords (add to question_labels.json)', quality.unlabelled.length ? quality.unlabelled.join(', ') : 'None'],
    ['Index episodes without a transcript', quality.missingTranscripts.length ? quality.missingTranscripts.join(', ') : 'None'],
    ['Transcribed episodes missing from the index', quality.unindexed.length ? quality.unindexed.join(', ') : 'None'],
    ['Questions without a timestamp', missingStart.length ? missingStart.map(x => `Ep ${x.ep} Q${x.order}`).join(', ') : 'None'],
    ['Episodes with unreadable characters (�)', replacement.length ? `${replacement.length}: ${replacement.map(x => `${x.n} (${x.replacement})`).join(', ')}` : 'None'],
    ['Questions in “Other”', fmtInt(QUESTIONS.filter(x => x.cat === 'other').length)],
  ] }))));
}

/* ---------- Render loop ---------- */
const RENDERERS = { overview: renderOverview, categories: renderCategories, questions: renderQuestions, insights: renderInsights, episodes: renderEpisodes, episode: renderEpisode, about: renderAbout };
function render(push = false) {
  endSession();
  writeHash(push);
  updateChrome();
  hideTip();
  activeCharts = [];
  hoverBus.clear();
  for (const panel of document.querySelectorAll('[data-panel]')) {
    const active = panel.dataset.panel === state.tab;
    panel.hidden = !active;
    if (!active) panel.replaceChildren();
  }
  const panel = document.querySelector(`[data-panel="${state.tab}"]`);
  panel.replaceChildren();
  RENDERERS[state.tab](panel);
}
function onHistory() {
  if (location.hash === lastHash) return;
  readHash();
  render();
}
window.addEventListener('popstate', onHistory);
window.addEventListener('hashchange', onHistory);
readHash();
render();
})();
