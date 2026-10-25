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
const escapeRegex = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
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
  q.search = `${q.title} ${q.excerpt} ${q.catName} ${q.subName} ${q.also.map(subName).join(' ')}`.toLowerCase();
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
   first, then greys. In part-to-whole charts a category's subcategories alternate lighter and darker
   tones of its hue (largest first), so neighbours stay apart and still read as one family. */
const CAT_COUNTS = countBy(QUESTIONS, q => q.cat);
const SUB_COUNTS = countBy(QUESTIONS, q => q.sub);
const CAT_ORDER = CATEGORIES.slice().sort((a, b) => (a.id === 'other') - (b.id === 'other') || (CAT_COUNTS.get(b.id) || 0) - (CAT_COUNTS.get(a.id) || 0));
const SLOTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'tail-1', 'tail-2', 'tail-3'];
const spread = (count, lo, hi, k) => count > 1 ? lo + (hi - lo) * k / (count - 1) : (lo + hi) / 2;
CAT_ORDER.forEach((c, i) => {
  c.color = `var(--${SLOTS[Math.min(i, SLOTS.length - 1)]})`;
  c.subs = c.subcategories.map(sb => SUB.get(sb.id)).filter(sb => SUB_COUNTS.get(sb.id))
    .sort((a, b) => SUB_COUNTS.get(b.id) - SUB_COUNTS.get(a.id));
  const tints = Math.ceil((c.subs.length - 1) / 2), shades = Math.floor((c.subs.length - 1) / 2);
  c.subs.forEach((sb, j) => {
    sb.color = c.color;
    sb.tone = j === 0 ? c.color
      : j % 2 ? `color-mix(in oklab, ${c.color} ${Math.round(100 - spread(tints, 30, 76, (j - 1) / 2))}%, var(--surface))`
      : `color-mix(in oklab, ${c.color} ${Math.round(100 - spread(shades, 24, 52, j / 2 - 1))}%, var(--ink))`;
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
  tab: 'overview', cat: '', sub: '', q: '', sort: 'episode', openings: true, share: true,
  ep: EPISODES[EPISODES.length - 1].n, focus: 0, t: null, play: false, find: '',
};
let lastHash = '';

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  let tab = p.get('tab');
  // Links to the old transcript search tab land on the question search instead.
  if (tab === 'search') { tab = 'questions'; if (p.get('search')) p.set('q', p.get('search')); }
  state.tab = TABS.includes(tab) ? tab : 'overview';
  state.sub = SUB.has(p.get('sub')) ? p.get('sub') : '';
  state.cat = CAT.has(p.get('cat')) ? p.get('cat') : (state.sub ? SUB.get(state.sub).cat : '');
  if (state.sub && SUB.get(state.sub).cat !== state.cat) state.sub = '';
  state.q = p.get('q') || '';
  state.sort = SORTS[p.get('sort')] ? p.get('sort') : 'episode';
  state.ep = BY_EP.has(Number(p.get('ep'))) ? Number(p.get('ep')) : state.ep;
  const t = Number(p.get('t'));
  state.t = p.has('t') && Number.isFinite(t) && t >= 0 ? t : null;
  state.find = p.get('find') || '';
  state.focus = 0;
  state.play = false;
}
function writeHash(push = false) {
  const p = new URLSearchParams({ tab: state.tab });
  if (FILTER_TABS.has(state.tab)) { if (state.cat) p.set('cat', state.cat); if (state.sub) p.set('sub', state.sub); }
  if (state.tab === 'questions') { if (state.q) p.set('q', state.q); if (state.sort !== 'episode') p.set('sort', state.sort); }
  if (state.tab === 'episode') { p.set('ep', state.ep); if (state.t) p.set('t', Math.floor(state.t)); if (state.find) p.set('find', state.find); }
  const hash = `#${p}`;
  if (location.hash !== hash) history[push ? 'pushState' : 'replaceState'](null, '', hash);
  lastHash = location.hash;
}
const inScope = q => (!state.cat || q.cat === state.cat) && (!state.sub || q.sub === state.sub);
const scopedQuestions = () => QUESTIONS.filter(inScope);
const scopeName = () => state.sub ? subName(state.sub) : state.cat ? catName(state.cat) : '';

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
function openEpisode(n, { order = 0, t = null, play = false, find = '' } = {}) {
  go('episode', { ep: n, focus: order, t, play, find });
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
    on: { click: ev => { ev.preventDefault(); go('questions', { cat: q.cat, sub: q.sub, q: '' }); } } },
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
function registerChart(draw) {
  activeCharts.push(draw);
  // Charts measure their container, so draw after the current render has attached the card.
  queueMicrotask(() => { if (activeCharts.includes(draw)) draw(); });
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
function kpi(label, value, sub, { span = 'span-2', accent = false } = {}) {
  const wordy = /[a-z]{3}/i.test(value) && value.length > 9;
  return h('div', { class: `kpi ${span}${accent ? ' accent' : ''}` },
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
function sunburst(container, { cat, sub, onPick, onBack }) {
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
  const legendBox = h('div', { class: 'donut-legend' });
  for (const it of items) {
    const row = h('button', { class: 'legend-row', type: 'button', style: `--cat:${it.color}`, 'aria-pressed': String(selected === it.key) },
      h('span', { class: 'swatch', style: `opacity:${it.shade}` }),
      h('span', { class: 'name', text: it.label }),
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
  container.replaceChildren(h('div', { class: 'donut-wrap' }, chartBox, legendBox));

  function draw() {
    chartBox.replaceChildren();
    slices.clear();
    const S = Math.round(Math.max(220, Math.min(400, chartBox.clientWidth || 320)));
    const c = S / 2, TAU = Math.PI * 2;
    const svg = s('svg', { viewBox: `0 0 ${S} ${S}`, width: S, height: S, role: 'img',
      'aria-label': focus ? `${focus.name}: questions by subcategory` : 'Questions by category and subcategory' });
    const add = (it, r0, r1, a0, a1) => {
      const path = s('path', { class: 'slice', d: arcPath(c, r0, r1, a0, a1), 'fill-rule': 'evenodd', style: `fill:${it.color};fill-opacity:${it.shade}` });
      path.addEventListener('pointermove', ev => { hover(it.key); showTip(ev, ...tip(it)); });
      path.addEventListener('pointerleave', () => { hover(null); hideTip(); });
      path.addEventListener('click', () => { hideTip(); pick(it); });
      svg.append(path);
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
    const num = s('text', { class: 'donut-center-number', x: c, y: r2(c - 2), 'text-anchor': 'middle' });
    const label = s('text', { class: 'donut-center-label', x: c, y: r2(c + 18), 'text-anchor': 'middle' });
    const note = s('text', { class: 'donut-center-note', x: c, y: r2(c + 35), 'text-anchor': 'middle' });
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
    centre = key => {
      const it = byKey.get(key || selected);
      if (it) {
        num.textContent = fmtInt(it.value);
        label.textContent = shorten(it.label, fit);
        note.textContent = SUB.has(it.key) ? `${fmtShare(it.value / CAT_COUNTS.get(it.cat))} of ${focus ? 'category' : shorten(catName(it.cat), fit - 8)}` : `${fmtShare(it.value / total)} of all`;
      } else {
        num.textContent = fmtInt(total);
        label.textContent = focus ? shorten(focus.name, fit) : 'questions';
        note.textContent = focus ? '↩ all categories' : `in ${TOPICS.length} categories`;
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
  function draw() {
    container.replaceChildren();
    const W = Math.max(260, container.clientWidth), H = 290;
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
  registerChart(draw);
  return { setShare(on) { shareMode = on; draw(); } };
}

/* ---------- Episode column chart (columns + rolling average, crosshair, click to open) ---------- */
function episodeChart(container, cfg) {
  let setCross = null;
  function draw() {
    if (setCross) hoverBus.delete(setCross);
    container.replaceChildren();
    const eps = cfg.episodes;
    const values = eps.map(e => { const v = cfg.value(e); return v == null || !Number.isFinite(v) ? null : v; });
    const defined = values.filter(v => v != null);
    if (!defined.length) { container.append(h('p', { class: 'muted', text: 'No data to show.' })); return; }
    const W = Math.max(260, container.clientWidth), H = cfg.height || 200;
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
    container.append(svg);

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
    setCross = ep => mark(ep == null ? null : eps.findIndex(e => e.n === ep));
    hoverBus.add(setCross);
    const broadcast = ep => hoverBus.forEach(fn => { if (fn !== setCross) fn(ep); });
    const colKey = cfg.color ? { color: cfg.color, shade: 0.42 } : { color: 'var(--acc-dim)' };
    const avgKey = { color: cfg.color || 'var(--acc-hi)' };
    hit.addEventListener('pointermove', ev => {
      const i = indexAt(ev), e = eps[i];
      mark(i);
      broadcast(e.n);
      const rows = [{ value: values[i] == null ? '–' : cfg.format(values[i]), label: cfg.label, ...colKey }];
      if (average && average[i] != null) rows.push({ value: cfg.format(average[i]), label: `${AVG}-episode average`, ...avgKey });
      showTip(ev, `Episode ${e.n}`, rows.concat(cfg.extra ? cfg.extra(e) : []), cfg.onSelect ? 'Click to open this episode' : null);
    });
    hit.addEventListener('click', ev => { if (cfg.onSelect) { hideTip(); cfg.onSelect(eps[indexAt(ev)].n); } });
    hit.addEventListener('pointerleave', () => { mark(null); broadcast(null); hideTip(); });
  }
  registerChart(draw);
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
  const max = Math.max(0, ...items.map(it => it.value)) || 1;
  const box = h('div', { class: 'bars' });
  for (const it of items) {
    const classes = ['bar-row'];
    if (selected) classes.push(selected === it.key ? 'selected' : 'dimmed');
    const row = h(onSelect ? 'button' : 'div', {
      class: classes.join(' '), type: onSelect ? 'button' : null, style: it.color ? `--cat:${it.color}` : null,
      'aria-pressed': onSelect && selected ? String(selected === it.key) : null, tabindex: onSelect ? null : '0',
    },
    h('span', { class: 'bar-label', title: it.label }, h('span', { class: 'bar-text', text: it.label }), it.lang ? h('span', { class: 'lang', text: it.lang }) : null),
    h('span', { class: 'bar-track' }, h('span', { class: 'bar-fill', style: `width:${(Math.max(0, it.value) / max * 100).toFixed(2)}%` })),
    h('span', { class: 'bar-value', text: format(it.value) }));
    attachTip(row, () => [it.title || it.label, [{ value: format(it.value), label: valueLabel, color: it.color }].concat(it.rows || []), it.note]);
    if (onSelect) row.addEventListener('click', () => { hideTip(); onSelect(it.key); });
    box.append(row);
  }
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
  function draw() {
    container.replaceChildren();
    if (!items.some(it => it.value > 0)) { container.append(h('p', { class: 'muted', text: 'Nothing to show for this selection.' })); return; }
    const W = Math.max(240, container.clientWidth), H = height;
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
  registerChart(draw);
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
function dataTable(container, { columns, rows, sortKey, sortDir = 'asc', pageSize = 50, empty = 'Nothing matches.' }) {
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
    const body = h('tbody', {}, sorted.slice(0, shown).map(row => h('tr', {}, columns.map(c => h('td', { class: c.num ? 'num' : null }, c.render ? c.render(row) : c.sort(row))))));
    if (!rows.length) body.append(h('tr', {}, h('td', { colspan: String(columns.length), class: 'muted', text: empty })));
    const footer = h('div', { class: 'table-footer' }, h('span', { text: rows.length ? `Showing ${fmtInt(Math.min(shown, rows.length))} of ${fmtInt(rows.length)}` : '' }));
    if (shown < rows.length) {
      footer.append(h('button', { class: 'small-button', type: 'button', text: `Show ${fmtInt(Math.min(pageSize, rows.length - shown))} more`, on: { click: () => { shown += pageSize; draw(); } } }));
    }
    container.replaceChildren(h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, head), body)), footer);
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
  return h('article', { class: 'q-card', style: catStyle(q.cat) },
    h('div', { class: 'q-head' }, h('h4', { class: 'q-title', text: q.title }), h('div', { class: 'q-actions' }, playButton(q))),
    h('div', { class: 'q-meta' }, subTag(q), q.also.map(code => h('span', { class: 'tag', title: 'Also about', text: subName(code) }))),
    h('div', { class: 'q-meta' }, facts, yt ? [' · ', yt] : null),
    state.openings && q.excerpt ? h('p', { class: 'q-excerpt', text: q.excerpt }) : null);
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
  container.replaceChildren(list.length ? box : h('p', { class: 'notice' }, 'No questions match. Try another search or clear the filter.'), h('div', { class: 'list-footer' }, count, more));
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
function placeItems(qs) {
  const counts = new Map();
  for (const q of qs) for (const i of q.places) counts.set(i, (counts.get(i) || 0) + 1);
  return [...counts.entries()].map(([i, value]) => ({ key: i, label: PLACES[i].name, value, note: PLACES[i].region })).sort((a, b) => b.value - a.value);
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
  const places = placeItems(qs);
  if (places.length) {
    const abroad = qs.filter(q => q.places.some(i => PLACES[i].region !== 'Pakistan')).length;
    items.push(['The most mentioned place is ', strong(places[0].label), ` (${plural(places[0].value, 'question')}); ${fmtPct(abroad / total)} of these questions mention somewhere outside Pakistan.`]);
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

/* ---------- Sidebar: sections, category tree, theme and the phone drawer ---------- */
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
for (const tab of TABS) {
  navBox.append(h('button', { class: 'nav-item', type: 'button', 'data-tab': tab, on: { click: () => go(tab) } }, icon(SECTIONS[tab].icon), h('span', { text: SECTIONS[tab].label })));
}

const treeBody = document.getElementById('tree');
const treeToggle = document.getElementById('tree-toggle');
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

/* ---------- Top bar: page title, active filter and quick search ---------- */
const pageTitle = document.getElementById('page-title');
const pageSub = document.getElementById('page-sub');
const chipBox = document.getElementById('filter-chip');
const quickForm = document.getElementById('quick-search');
const quickInput = document.getElementById('quick-search-input');
quickForm.addEventListener('submit', ev => {
  ev.preventDefault();
  go('questions', { q: quickInput.value.trim(), cat: '', sub: '' });
});
const SUBTITLES = {
  overview: () => `${fmtInt(QUESTIONS.length)} viewer questions from ${fmtInt(EPISODES.length)} episodes, in ${TOPICS.length} categories and ${SUBTOPIC_COUNT} subcategories`,
  categories: () => state.cat ? CAT.get(state.cat).description : 'How the questions are grouped, and how each subject changed over the years',
  questions: () => 'Search, filter and play every question',
  insights: () => 'Answer lengths, ages, places, words and the subjects on the rise',
  episodes: () => 'Length, pace and questions for every episode',
  episode: () => {
    const e = BY_EP.get(state.ep);
    return e ? `Episode ${e.n} · ${fmtDuration(e.duration)} · ${plural(e.questions, 'question')}` : '';
  },
  about: () => 'How the data was made, what the measures mean, and their limits',
};
function updateChrome() {
  for (const b of navBox.children) {
    if (b.dataset.tab === state.tab) b.setAttribute('aria-current', 'page');
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
  if (document.activeElement !== quickInput) quickInput.value = state.tab === 'questions' ? state.q : '';
  renderTree();
}

/* ---------- Overview ---------- */
function renderOverview(panel) {
  const qs = scopedQuestions();
  const cat = state.cat ? CAT.get(state.cat) : null;
  const scope = scopeName();
  const answered = qs.filter(q => q.length != null).map(q => q.length);
  const ages = qs.map(q => q.age).filter(Boolean);
  const places = placeItems(qs);
  const episodesWith = new Set(qs.map(q => q.ep)).size;
  const leadSub = cat && !state.sub ? subItems(qs, cat.id)[0] : null;
  panel.append(
    kpi(scope ? `${scope}` : 'Questions', fmtInt(qs.length), scope ? (state.sub ? `${fmtPct(qs.length / CAT_COUNTS.get(cat.id))} of ${cat.name}` : `${fmtPct(qs.length / QUESTIONS.length)} of all questions`) : `from ${plural(EPISODES.length, 'episode')}`, { accent: true }),
    cat ? kpi('Episodes', fmtInt(episodesWith), `of ${fmtInt(EPISODES.length)} include one`)
      : kpi('Categories', String(TOPICS.length), `split into ${SUBTOPIC_COUNT} subcategories`),
    leadSub ? kpi('Top subcategory', leadSub.label, `${plural(leadSub.value, 'question')}, ${fmtPct(leadSub.value / qs.length)}`)
      : state.sub ? kpi('Share of all', fmtShare(qs.length / QUESTIONS.length), 'of every question asked')
      : kpi('Per episode', fmt1(qs.length / EPISODES.length), 'questions on average'),
    kpi('Median answer', fmtDuration(median(answered)), answered.length ? `${fmtDuration(sum(answered))} of answers in all` : 'No timed answers'),
    kpi('Asker age', ages.length ? String(median(ages)) : '–', ages.length ? `median of ${plural(ages.length, 'stated age')}` : 'No ages stated'),
    kpi('Top place', places.length ? places[0].label : '–', places.length ? `named in ${plural(places[0].value, 'question')}` : 'No places named'));

  const donutRows = () => ({
    columns: [{ label: 'Category' }, { label: 'Subcategory' }, { label: 'Questions', num: true }, { label: 'Share', num: true }],
    rows: (cat ? [cat] : LIVE_CATS).flatMap(c => c.subs.map((sb, i) => [i ? '' : c.name, sb.name, fmtInt(SUB_COUNTS.get(sb.id)), fmtShare(SUB_COUNTS.get(sb.id) / (cat ? CAT_COUNTS.get(c.id) : QUESTIONS.length))])),
  });
  const donut = card({ title: cat ? `Inside ${cat.name}` : 'What viewers ask about',
    subtitle: cat ? 'Subcategories by number of questions · click one to filter, or the centre to go back' : 'Categories in the inner ring, their subcategories outside · click a slice to zoom in',
    span: 'span-7', table: donutRows });
  if (cat) donut.actions.prepend(h('button', { class: 'small-button', type: 'button', text: '← All categories', on: { click: () => setFilter('', '') } }));
  sunburst(donut.body, { cat: state.cat, sub: state.sub, onPick: (c, sb) => setFilter(c, sb), onBack: () => setFilter('', '') });

  const series = cat ? cat.subs.map(sb => ({ key: sb.id, label: sb.name, color: sb.tone, shade: 1 }))
    : LIVE_CATS.map(c => ({ key: c.id, label: c.name, color: c.color, shade: 1 }));
  const blocks = eras(EPISODES);
  const pool = cat ? QUESTIONS.filter(q => q.cat === cat.id) : QUESTIONS;
  const groupOf = cat ? q => q.sub : q => q.cat;
  const trend = card({ title: cat ? `${cat.name} over time` : 'Subjects over time',
    subtitle: `Questions in each block of ${Math.ceil(EPISODES.length / blocks.length)} episodes · click a band to filter`, span: 'span-5', legend: seriesLegend(series),
    table: () => ({
      columns: [{ label: 'Episodes' }].concat(series.map(sr => ({ label: sr.label, num: true }))),
      rows: blocks.map(b => { const list = pool.filter(q => q.ep >= b.from && q.ep <= b.to), counts = countBy(list, groupOf); return [b.label].concat(series.map(sr => fmtInt(counts.get(sr.key) || 0))); }),
    }) });
  const stacked = stackedColumns(trend.body, { qs: pool, series, groupOf, selected: state.sub || null,
    onPick: key => cat ? setFilter(cat.id, state.sub === key ? '' : key) : setFilter(key, '') });
  trend.actions.prepend(segmented('Measure', [['Share', true], ['Count', false]], state.share, on => { state.share = on; stacked.setShare(on); }));
  panel.append(donut.el, trend.el);

  const counts = countBy(qs, q => q.ep);
  panel.append(episodeCard(EPISODES, {
    title: scope ? `${scope}: questions per episode` : 'Questions per episode', subtitle: 'Index entries in each episode · click a column to open it',
    label: 'Questions', value: e => counts.get(e.n) || 0, format: fmtInt, color: cat ? cat.color : null, span: 'span-8', height: 320,
    extra: e => (QS_BY_EP.get(e.n) || []).filter(inScope).slice(0, 3).map(q => ({ value: `Q${q.order}`, label: shorten(q.title, 60) })),
  }));
  const summary = card({ title: 'Key findings', subtitle: scope ? `For questions about ${scope}` : 'Across all episodes', span: 'span-4' });
  summary.body.append(findings(qs));
  panel.append(summary.el);

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

  const longest = qs.filter(q => q.length != null).sort((a, b) => b.length - a.length).slice(0, 8);
  const longCard = card({ title: 'Longest answers', subtitle: 'Minutes from the question to the next one · click to play', span: 'span-6' });
  barList(longCard.body, { items: longest.map(q => ({ key: q, label: q.title, value: q.length / 60, color: colorOf(q.cat), rows: [{ value: `Episode ${q.ep} · Q${q.order}`, label: q.subName }], note: 'Click to play this answer' })),
    format: fmtMinutes, valueLabel: 'until the next question', onSelect: q => openQuestion(q) });
  const spotCard = card({ title: 'Question spotlight', subtitle: 'A random question from this selection', span: 'span-6' });
  const spot = h('div');
  // Comment round-ups are not questions, so the spotlight skips them unless they are the selection.
  const letters = qs.filter(q => q.sub !== 'show.comments');
  const spotPool = letters.length ? letters : qs;
  const show = () => spot.replaceChildren(questionCard(spotPool[Math.floor(Math.random() * spotPool.length)]));
  spotCard.actions.append(h('button', { class: 'small-button', type: 'button', text: 'Show another', on: { click: show } }));
  spotCard.body.append(spot);
  show();
  panel.append(longCard.el, spotCard.el);
}

/* ---------- Categories ---------- */
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
  const multi = QUESTIONS.filter(q => q.alsoCats.length).length;
  panel.append(h('p', { class: 'lead span-12' },
    `Each of the ${fmtInt(QUESTIONS.length)} questions has one main subcategory, checked by hand from its title and opening; ${fmtPct(multi / QUESTIONS.length)} also carry a second subject as an extra tag. `,
    'Broad subjects are split into finer subcategories under their category. The small columns show each category’s share of questions across blocks of episodes, newest on the right.'));
  panel.append(h('div', { class: 'cat-grid' }, LIVE_CATS.map(c => categoryCard(c, eraList))));
}
function renderCategoryDetail(panel) {
  const cat = CAT.get(state.cat);
  const inCat = QUESTIONS.filter(q => q.cat === cat.id), qs = inCat.filter(inScope);
  const sub = state.sub ? SUB.get(state.sub) : null;
  const crumb = (label, onClick) => h('a', { href: '#', on: { click: ev => { ev.preventDefault(); onClick(); } } }, label);
  panel.append(h('div', { class: 'detail span-12' },
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' },
      crumb('All categories', () => setFilter('', '')), h('span', { 'aria-hidden': 'true', text: '›' }),
      sub ? [crumb(cat.name, () => setFilter(cat.id, '')), h('span', { 'aria-hidden': 'true', text: '›' }), h('span', { text: sub.name })] : h('span', { text: cat.name })),
    h('div', { class: 'detail-head', style: `--cat:${cat.color}` }, h('span', { class: 'dot' }),
      h('div', {}, h('h2', { text: sub ? sub.name : cat.name }), h('p', { text: sub ? sub.description : cat.description })))));
  const answered = qs.filter(q => q.length != null).map(q => q.length);
  const ages = qs.map(q => q.age).filter(Boolean);
  const places = placeItems(qs);
  panel.append(
    kpi('Questions', fmtInt(qs.length), sub ? `${fmtPct(qs.length / inCat.length)} of ${cat.name}` : `${fmtShare(qs.length / QUESTIONS.length)} of all questions`, { accent: true }),
    kpi('Episodes', fmtInt(new Set(qs.map(q => q.ep)).size), `of ${fmtInt(EPISODES.length)} include one`),
    kpi('Median answer', fmtDuration(median(answered)), answered.length ? `longest ${fmtDuration(Math.max(...answered))}` : 'No timed answers'),
    kpi('Asker age', ages.length ? String(median(ages)) : '–', ages.length ? `median of ${plural(ages.length, 'stated age')}` : 'No ages stated'),
    kpi('Top place', places.length ? places[0].label : '–', places.length ? `named in ${plural(places[0].value, 'question')}` : 'No places named'),
    kpi('Two subjects', fmtPct(qs.filter(q => q.alsoCats.length).length / qs.length), 'touch another category'));

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

  const pairs = pairItems(qs, cat.id);
  const pairCard = card({ title: 'Often comes with', subtitle: 'Other categories tagged on the same questions', span: 'span-4', table: itemsTable('Category', pairs, fmtInt) });
  barList(pairCard.body, { items: pairs.slice(0, 8), format: fmtInt, valueLabel: 'questions in both', onSelect: key => go('categories', { cat: key, sub: '' }) });
  const words = wordItems(qs);
  const wordCard = card({ title: 'Words in these questions', subtitle: 'Most frequent title words · click one to search', span: 'span-4', table: itemsTable('Word', words.slice(0, 30), fmtInt) });
  barList(wordCard.body, { items: words.slice(0, 10), format: fmtInt, valueLabel: 'titles', onSelect: word => go('questions', { q: word }) });
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
  const controls = card({ title: 'Find questions', subtitle: 'Search titles and the opening of each answer · ▶ plays an answer in the episode explorer' });
  const input = h('input', { class: 'text-input', type: 'search', placeholder: 'Search, e.g. canada visa, cousin, freelancing', value: state.q, 'aria-label': 'Search questions' });
  const sort = h('select', { class: 'select', 'aria-label': 'Sort questions' }, Object.entries(SORTS).map(([key, it]) => h('option', { value: key, text: it.label })));
  sort.value = state.sort;
  const openings = h('input', { type: 'checkbox', checked: state.openings });
  append(controls.body, [
    h('div', { class: 'controls' }, input, sort, h('label', { class: 'checkbox' }, openings, 'Show openings')),
    h('div', { class: 'chips' }, h('span', { class: 'chips-label', text: 'Category' }),
      chipButton('All', QUESTIONS.length, !state.cat, () => setFilter('', '')),
      categoryItems(QUESTIONS).map(c => chipButton(c.label, c.value, state.cat === c.key, () => setFilter(c.key, ''), c.color))),
    state.cat ? h('div', { class: 'chips' }, h('span', { class: 'chips-label', text: 'Subcategory' }),
      chipButton(`All of ${catName(state.cat)}`, inCat.length, !state.sub, () => setFilter(state.cat, '')),
      subItems(inCat, state.cat).map(sb => chipButton(sb.label, sb.value, state.sub === sb.key, () => setFilter(state.cat, sb.key)))) : null]);
  panel.append(controls.el);
  const results = h('div', { class: 'span-12' });
  panel.append(results);
  const update = () => {
    const words = state.q.toLowerCase().split(/[\s,]+/).filter(Boolean);
    const list = inCat.filter(q => (!state.sub || q.sub === state.sub) && words.every(w => q.search.includes(w))).sort(SORTS[state.sort].compare);
    questionList(results, list, 24);
  };
  input.addEventListener('input', debounce(() => { state.q = input.value.trim(); writeHash(); update(); }, 150));
  sort.addEventListener('change', () => { state.sort = sort.value; writeHash(); update(); });
  openings.addEventListener('change', () => { state.openings = openings.checked; update(); });
  update();
}

/* ---------- Insights ---------- */
function renderInsights(panel) {
  const qs = scopedQuestions();
  if (!qs.length) { panel.append(notice('No questions match this filter.')); return; }
  const scope = scopeName();
  panel.append(h('p', { class: 'lead span-12', text: `Patterns across ${plural(qs.length, 'question')}${scope ? ` about ${scope}` : ''}. Pick a category in the sidebar to focus every chart on it.` }));

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

  const positions = positionItems(qs);
  const position = card({ title: 'Does the first question get the most time?', subtitle: 'Median minutes per answer by the question’s position in its episode', span: 'span-4', table: itemsTable('Position', positions, fmtMinutes) });
  ordinalColumns(position.body, { items: positions, format: v => fmt1(v), label: 'median minutes' });
  const ageList = ageItems(qs), ages = qs.map(q => q.age).filter(Boolean);
  const agesCard = card({ title: 'How old are the askers?', subtitle: ages.length ? `${plural(ages.length, 'question')} state an age · median ${median(ages)}` : 'No ages stated in these questions', span: 'span-4', table: itemsTable('Age', ageList, fmtInt) });
  ordinalColumns(agesCard.body, { items: ageList, format: fmtInt, label: 'questions' });
  const ageByGroup = (state.cat ? subItems(qs, state.cat) : categoryItems(qs)).map(it => {
    const list = qs.filter(q => (state.cat ? q.sub : q.cat) === it.key).map(q => q.age).filter(Boolean);
    return { key: it.key, label: it.label, color: it.color, value: median(list) || 0, rows: [{ value: fmtInt(list.length), label: 'stated ages' }], n: list.length };
  }).filter(it => it.n >= 4).sort((a, b) => b.value - a.value);
  const ageGroups = card({ title: 'Median age by subject', subtitle: 'Subjects with at least four stated ages', span: 'span-4', table: itemsTable('Subject', ageByGroup, fmtInt) });
  barList(ageGroups.body, { items: ageByGroup, format: fmtInt, valueLabel: 'median age' });
  panel.append(position.el, agesCard.el, ageGroups.el);

  const places = placeItems(qs), regions = regionItems(qs);
  const placesCard = card({ title: 'Places mentioned', subtitle: 'Cities and countries named in the title or the first 45 seconds', span: 'span-4', table: itemsTable('Place', places, fmtInt) });
  barList(placesCard.body, { items: places.slice(0, 12), format: fmtInt, valueLabel: 'questions' });
  const regionCard = card({ title: 'By region', subtitle: 'Questions naming at least one place in each region', span: 'span-4', table: itemsTable('Region', regions, fmtInt) });
  barList(regionCard.body, { items: regions, format: fmtInt, valueLabel: 'questions' });
  const pairs = pairItems(qs, state.cat);
  const pairCard = card({ title: state.cat ? 'Often comes with' : 'Subjects that come together', subtitle: 'Questions tagged with both categories', span: 'span-4', table: itemsTable('Pair', pairs, fmtInt) });
  barList(pairCard.body, { items: pairs.slice(0, 10), format: fmtInt, valueLabel: 'questions' });
  panel.append(placesCard.el, regionCard.el, pairCard.el);

  const words = wordItems(qs);
  const wordCard = card({ title: 'Words in question titles', subtitle: 'Click a word to list its questions', span: 'span-6', table: itemsTable('Word', words.slice(0, 40), fmtInt) });
  barList(wordCard.body, { items: words.slice(0, 14), format: fmtInt, valueLabel: 'titles', onSelect: word => go('questions', { q: word }) });
  const keys = state.cat ? CAT.get(state.cat).subs.map(sb => sb.id) : TOPICS.flatMap(c => c.subs.map(sb => sb.id));
  const shifts = shiftItems(state.cat ? QUESTIONS.filter(q => q.cat === state.cat) : QUESTIONS, q => q.sub, keys, subName).filter(it => it.n >= 6).sort((a, b) => b.value - a.value);
  const movers = shifts.filter(it => it.value > 0).slice(0, 7).concat(shifts.filter(it => it.value < 0).slice(-7));
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
    rows: EPISODES, sortKey: 'n', sortDir: 'desc', pageSize: 50,
    columns: [
      { key: 'n', label: 'Ep', num: true, sort: e => e.n, firstDir: 'desc', render: e => episodeLink(e.n, String(e.n)) },
      { key: 'len', label: 'Length', num: true, sort: e => e.duration, render: e => fmtClock(e.duration) },
      { key: 'q', label: scope ? 'Matching' : 'Questions', num: true, sort: e => scope ? counts.get(e.n) || 0 : e.questions, render: e => fmtInt(scope ? counts.get(e.n) || 0 : e.questions) },
      { key: 'subjects', label: 'Subjects', sort: null, render: e => h('div', { class: 'words' }, [...countBy(e.qs, q => q.cat).entries()].sort((a, b) => b[1] - a[1]).slice(0, 4)
        .map(([c, n]) => h('span', { class: 'tag', style: catStyle(c) }, h('span', { class: 'dot' }), `${catName(c)}${n > 1 ? ` ×${n}` : ''}`))) },
      { key: 'pq', label: 'Min / question', num: true, sort: e => e.perQuestion, render: e => e.perQuestion == null ? '–' : fmt1(e.perQuestion) },
      { key: 'intro', label: 'Intro', num: true, sort: e => e.firstQuestion, render: e => e.firstQuestion == null ? '–' : fmtClock(e.firstQuestion) },
      { key: 'sig', label: 'Signature words', sort: null, render: e => h('span', { class: 'words', text: e.signature.join(', ') }) },
      { key: 'watch', label: 'Watch', sort: null, render: e => h('button', { class: 'q-play', type: 'button', text: '▶ Play', on: { click: () => openEpisode(e.n, { play: true }) } }) },
    ],
  });
  panel.append(table.el);
}

/* ---------- Transcripts: data/transcripts/episode_NNN.js call GANJI_TRANSCRIPT ---------- */
const transcriptCache = new Map();
const transcriptWaiting = new Map();
window.GANJI_TRANSCRIPT = (n, cues) => {
  const resolve = transcriptWaiting.get(n);
  transcriptWaiting.delete(n);
  if (resolve) resolve({ cues: cues.map(([start, text]) => ({ start, text })) });
};
function loadTranscript(n) {
  if (!transcriptCache.has(n)) {
    const promise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `data/transcripts/episode_${String(n).padStart(3, '0')}.js`;
      transcriptWaiting.set(n, resolve);
      script.onload = () => {
        script.remove();
        if (transcriptWaiting.delete(n)) reject(new Error(`${script.src} did not contain a transcript`));
      };
      script.onerror = () => {
        script.remove();
        transcriptWaiting.delete(n);
        reject(new Error(`could not load ${script.src}`));
      };
      document.head.append(script);
    });
    promise.catch(() => transcriptCache.delete(n));
    transcriptCache.set(n, promise);
  }
  return transcriptCache.get(n);
}
const stripSounds = text => text.replace(/\[[a-z]+\]/gi, ' ').replace(/\s+/g, ' ').trim();
function highlighted(text, regex) {
  const out = [];
  let last = 0;
  regex.lastIndex = 0;
  for (const m of text.matchAll(regex)) {
    if (!m[0]) continue;
    out.push(text.slice(last, m.index), h('mark', { text: m[0] }));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
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
async function mountTranscript(box, findInput, counter, sess, timed, seek) {
  const e = sess.e;
  box.replaceChildren(h('p', { class: 'muted', text: 'Loading transcript…' }));
  let t;
  try { t = await loadTranscript(e.n); } catch (error) {
    box.replaceChildren(h('p', { class: 'notice' }, h('strong', { text: 'The transcript needs the files in data/transcripts/. ' }),
      'Run ', h('code', { text: 'bash app/run.sh' }), ' to generate them, then reload this page.'));
    findInput.disabled = true;
    return null;
  }
  if (session !== sess) return null;
  const list = h('div', { class: 'transcript', tabindex: '0', 'aria-label': `Transcript of episode ${e.n}` });
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
    const textBox = h('span', { class: 'cue-text' }, cueText(c.text));
    const time = h('button', { class: 'cue-time', type: 'button', text: fmtClock(c.start), title: sess.live ? 'Play from this line' : 'Open YouTube at this line',
      on: { click: () => seek(Math.max(0, c.start - (sess.live ? 0.3 : 2)), { external: true }) } });
    const row = h('div', { class: 'cue' }, time, textBox);
    rows.push({ row, textBox, c, lower: stripSounds(c.text).toLowerCase() });
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
      if (current >= 0) rows[current].row.classList.remove('current');
      current = idx;
      if (idx >= 0) rows[idx].row.classList.add('current');
    }
    if (idx >= 0 && following && !rows[idx].row.hidden && sess.live) { keepInView(rows[idx].row, jump); jump = false; }
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

  const apply = () => {
    const query = findInput.value.trim();
    state.find = query;
    writeHash();
    const lower = query.toLowerCase();
    let matches = 0;
    const regex = query ? new RegExp(escapeRegex(lower).replace(/\s+/g, '\\s+'), 'gi') : null;
    for (const r of rows) {
      const hit = !query || r.lower.includes(lower);
      r.row.hidden = !hit;
      if (hit && query) { matches++; r.textBox.replaceChildren(...highlighted(stripSounds(r.c.text), regex)); r.marked = true; }
      else if (r.marked) { r.textBox.replaceChildren(...cueText(r.c.text)); r.marked = false; }
    }
    for (const header of headers.values()) header.hidden = !!query;
    counter.textContent = query ? `${plural(matches, 'line')} with “${query}”` : `${fmtInt(rows.length)} lines`;
    if (query) stopFollowing();
  };
  findInput.disabled = false;
  findInput.addEventListener('input', debounce(apply, 150));
  apply();
  sess.followers.push(update);
  update(sess.time);
  return {
    follow() { following = true; jump = true; followButton.hidden = true; },
    showQuestion(q) {
      const header = headers.get(q);
      if (!header) return;
      if (findInput.value) { findInput.value = ''; apply(); }
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
  const qRows = new Map();
  qCard.body.append(h('div', { class: 'question-list' }, e.qs.map(q => {
    const row = h('div', { class: 'question-item', style: catStyle(q.cat) },
      h('span', { class: 'question-number', text: `Q${q.order}` }),
      h('div', {},
        h('div', { class: 'question-title' }, h('button', { type: 'button', text: q.title, on: { click: () => seek(q.start, { q }) } })),
        h('div', { class: 'q-meta' }, subTag(q), q.also.map(code => h('span', { class: 'tag', text: subName(code) })),
          q.age ? h('span', { class: 'tag', text: `age ${q.age}` }) : null, q.places.map(i => h('span', { class: 'tag', text: PLACES[i].name }))),
        q.excerpt ? h('div', { class: 'excerpt', text: q.excerpt }) : null),
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
    kpi('Length', fmtDuration(e.duration), `${fmtInt(e.cues)} subtitle lines`, { span: '' }),
    kpi('Questions', fmtInt(e.questions), e.firstQuestion != null ? `first at ${fmtClock(e.firstQuestion)}` : 'no timestamps', { span: '' }),
    kpi('Per question', fmtMinutes(e.perQuestion), 'on average', { span: '' }),
    kpi('Words', fmtCompact(e.words), `${fmtInt(e.pace)} per spoken minute`, { span: '' }),
    e.englishShare != null ? kpi('English', fmtPct(e.englishShare), `${fmtPct(1 - e.englishShare)} Urdu`, { span: '' }) : null,
    kpi('Laughter', fmtInt(e.laughs), `${fmt1(e.laughRate)} per hour`, { span: '' })));
  const pace = card({ title: 'Words per minute', subtitle: 'How densely it is spoken, minute by minute · lines mark questions · click to play from there' });
  const paceView = paceChart(pace.body, e, timed, t => seek(t, { external: true }));
  sess.followers.push(paceView.setTime);

  const find = h('input', { class: 'text-input', type: 'search', placeholder: 'Find in this transcript', value: state.find, 'aria-label': 'Find in transcript', disabled: true });
  const words = card({ title: 'Words', subtitle: 'Signature words are unusually frequent in this episode · click one to find it in the transcript' });
  words.body.append(h('div', { class: 'chips' }, e.signature.length
    ? e.signature.map(w => h('button', { class: 'chip', type: 'button', text: w, on: { click: () => { find.value = w; find.dispatchEvent(new Event('input')); } } }))
    : h('span', { class: 'muted', text: 'None found' })));
  const commonBox = h('div');
  words.body.append(h('h4', { class: 'section-label', text: 'Most used content words' }), commonBox);
  barList(commonBox, { items: e.topList.slice(0, 10).map(([i, c]) => ({ key: i, label: VOCAB[i], value: c, lang: VOCAB_LANG ? (VOCAB_LANG[i] === 'e' ? 'EN' : 'UR') : null })), format: fmtInt, valueLabel: 'uses' });

  const counter = h('span', { class: 'find-count' });
  const box = h('div', { class: 'transcript-box' });
  const transcriptCard = h('section', { class: 'card transcript-card' },
    h('div', { class: 'card-head' }, h('div', { class: 'card-titles' }, h('h3', { text: 'Transcript' }),
      h('p', { class: 'subtitle', text: sess.live ? 'Follows the video as it plays · click a time to jump there' : 'Roman Urdu subtitles · times open YouTube' }))),
    h('div', { class: 'controls' }, find, counter), box);
  panel.append(h('div', { class: 'stack span-7' }, playerCard, qCard.el, facts.el, pace.el, words.el), h('div', { class: 'side span-5' }, transcriptCard));

  if (sess.live) mountPlayer(frame, sess, startAt, autoplay, now, tick);
  else playerFallback(frame, sess, e.video ? 'The built-in player works when the app is served over http(s): on the published site, or locally with bash app/run.sh --serve.' : 'No video is linked to this episode.', now);
  tick(startAt);
  mountTranscript(box, find, counter, sess, timed, seek).then(view => {
    transcript = view;
    if (view && focusQ && !sess.live) view.showQuestion(focusQ);
  });
}

/* ---------- About ---------- */
function renderAbout(panel) {
  const meta = DATA.meta, quality = DATA.quality;
  const sorted = QUESTIONS.filter(x => !x.sub.endsWith('.auto')).length;
  const intro = card({ title: 'About this app', span: 'span-7', cls: 'prose' });
  intro.body.append(
    h('p', {}, 'An unofficial, fan-made way to explore the ', strong(`${fmtInt(meta.questions)} viewer questions`),
      ` answered on Ask Ganji Swag across ${fmtInt(meta.episodes)} episodes (${fmt1(meta.seconds / 3600)} hours). The questions and their timestamps come from a hand-made episode index; the transcripts come from CrisperWhisper speech recognition, converted word by word to Roman Urdu with English kept as spoken.`),
    h('p', {}, 'Every episode plays inside the ', strong('Episode explorer'), ', where the transcript follows the video line by line and the timeline shows which question is being answered. Every chart has a table view, and every question links to the moment it is read out.'));
  const how = card({ title: 'How questions are categorised', span: 'span-5', cls: 'prose' });
  how.body.append(
    h('p', {}, 'Each question has one main subcategory, chosen by reading its title and, where the title was vague, the opening of the answer, which is usually the letter being read out. Questions that clearly cover a second subject carry it as an extra tag.'),
    h('p', {}, `Subcategories sit inside ${TOPICS.length} categories. Where a subject was too broad, such as love and marriage or Pakistani society, it is split into finer subcategories under the same category, ${SUBTOPIC_COUNT} in all.`),
    h('p', {}, 'The labels live in ', h('code', { text: 'app/tools/question_labels.json' }), ' in the source repository and can be corrected there. New episodes that are not in that file yet are placed by keywords and shown as “Not yet sorted”.'));
  const measures = card({ title: 'Measures', span: 'span-7', cls: 'prose' });
  measures.body.append(h('ul', {},
    h('li', {}, strong('Answer length'), ': time from a question’s timestamp to the next question (or the end of the episode). It includes reading the question out and any tangents.'),
    h('li', {}, strong('Asker age'), ': an age stated as “22 years old”, “19 yo”, “I’m 24” or “twenty-four year old” in the title or the first 90 seconds. Occasionally it is someone else’s age in the letter.'),
    h('li', {}, strong('Places'), ': cities and countries named in the title or the first 45 seconds. The YouTube comment segments are left out of ages and places.'),
    h('li', {}, strong('Rising and falling'), ': each subject’s share of questions in the second half of all episodes minus its share in the first half, in percentage points.'),
    h('li', {}, strong('Signature words'), ': terms unusually frequent in one episode’s transcript (TF-IDF), limited to words seen in at least two episodes with reliable spellings.'),
    h('li', {}, strong('English share'), ': words the recogniser wrote in Latin script. Loanwords and place names it wrote in Urdu script count as Urdu.')));
  const caveats = card({ title: 'Caveats', span: 'span-5', cls: 'prose' });
  caveats.body.append(h('ul', {},
    h('li', { text: 'Transcripts are machine-generated: names, vowels and rare words can be wrong or spelled inconsistently (shaadi / shadi).' }),
    h('li', { text: 'The transcript follows the video by its subtitle timings, which can drift by a second or two.' }),
    h('li', { text: 'Categories are one reader’s judgement of short titles and openings. Many questions could reasonably sit in two places; the extra tags show the most obvious second subject.' }),
    h('li', { text: 'Index titles were written by different people over time, so their style varies between early and recent episodes.' })));
  panel.append(intro.el, how.el, measures.el, caveats.el);

  const taxonomy = card({ title: 'Categories and subcategories', subtitle: 'With the number of questions in each, across all episodes' });
  taxonomy.body.append(h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['Category', 'Subcategory', 'What it covers'].map(label => h('th', { scope: 'col', text: label })), h('th', { scope: 'col', class: 'num', text: 'Questions' }), h('th', { scope: 'col', class: 'num', text: 'Share of category' }))),
    h('tbody', {}, LIVE_CATS.flatMap(c => c.subs.map((sb, i) => h('tr', {},
      h('td', {}, i ? '' : h('span', { class: 'tax-cat', style: `--cat:${c.color}` }, h('span', { class: 'dot' }), c.name)),
      h('td', {}, h('a', { href: `#tab=questions&cat=${c.id}&sub=${sb.id}`, on: { click: ev => { ev.preventDefault(); go('questions', { cat: c.id, sub: sb.id, q: '' }); } } }, sb.name)),
      h('td', { class: 'muted', text: sb.description }),
      h('td', { class: 'num', text: fmtInt(SUB_COUNTS.get(sb.id)) }),
      h('td', { class: 'num', text: fmtShare(SUB_COUNTS.get(sb.id) / CAT_COUNTS.get(c.id)) }))))))));
  panel.append(taxonomy.el);

  const missingStart = QUESTIONS.filter(x => x.start == null);
  const replacement = EPISODES.filter(e => e.replacement);
  const checks = card({ title: 'Data quality', subtitle: 'Checks on the inputs behind these numbers', span: 'span-7' });
  checks.body.append(h('div', { class: 'table-wrap' }, simpleTable({ columns: [{ label: 'Check' }, { label: 'Result' }], rows: [
    ['Episodes with transcripts', fmtInt(EPISODES.length)],
    ['Questions categorised by hand', `${fmtInt(sorted)} of ${fmtInt(QUESTIONS.length)}`],
    ['Episodes placed by keywords (add to question_labels.json)', quality.unlabelled.length ? quality.unlabelled.join(', ') : 'None'],
    ['Index episodes without a transcript', quality.missingTranscripts.length ? quality.missingTranscripts.join(', ') : 'None'],
    ['Transcribed episodes missing from the index', quality.unindexed.length ? quality.unindexed.join(', ') : 'None'],
    ['Questions without a timestamp', missingStart.length ? missingStart.map(x => `Ep ${x.ep} Q${x.order}`).join(', ') : 'None'],
    ['Episodes with unreadable characters (�)', replacement.length ? `${replacement.length}: ${replacement.map(x => `${x.n} (${x.replacement})`).join(', ')}` : 'None'],
    ['Questions in “Other”', fmtInt(QUESTIONS.filter(x => x.cat === 'other').length)],
  ] })));
  const sources = card({ title: 'Sources and rights', span: 'span-5', cls: 'prose' });
  sources.body.append(
    h('p', {}, 'Videos play from YouTube in its privacy-enhanced mode and stay on the creators’ channel; this site hosts no video or audio.'),
    h('p', {}, 'All episode content belongs to its creators. This analysis is unofficial and not affiliated with the show.'),
    h('p', {}, h('a', { href: meta.playlist, target: '_blank', rel: 'noopener', text: 'The full playlist on YouTube ↗' })));
  panel.append(checks.el, sources.el);
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
