// Tankōbon — front end. No build step, no framework.

// ================================================================ helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const enc = encodeURIComponent;
const root = document.documentElement;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') for (const [sk, sv] of Object.entries(v)) el.style.setProperty(sk, sv);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  phone: '<rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M10.5 18.5h3"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/>',
  read: '<path d="M2 5.5c3-1.5 6.5-1.5 10 1 3.5-2.5 7-2.5 10-1v14c-3-1.5-6.5-1.5-10 1-3.5-2.5-7-2.5-10-1z"/><path d="M12 6.5v14"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5"/><path d="M4 19h16"/>',
  folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  ext: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  logout: '<path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4M10 8l-4 4 4 4M6 12h10"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  file: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  wifi: '<path d="M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0"/><circle cx="12" cy="19" r="1"/>',
  scroll: '<path d="M7 3h10v18H7z"/><path d="M10 7h4M10 11h4M10 15h4"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
};
function icon(name) {
  return h('span', { class: 'icon', 'aria-hidden': 'true', html: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>` });
}

async function req(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  let j = {};
  try { j = await r.json(); } catch {}
  if (!r.ok) throw Object.assign(new Error(j.error || `${r.status} ${r.statusText}`), { status: r.status });
  return j;
}
const get = (p) => req('GET', p);
const post = (p, b = {}) => req('POST', p, b);

const fmtBytes = (b) => !b ? '0 B' : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(0)} KB` : b < 1073741824 ? `${(b / 1048576).toFixed(1)} MB` : `${(b / 1073741824).toFixed(2)} GB`;
const shortName = (n) => n.replace(/\.cbz$/i, '').split(' - ').pop();  // 'Series - Vol.01.cbz' -> 'Vol.01'
const fmtNum = (n) => n == null ? '—' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(n);
function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
const langNames = new Intl.DisplayNames(['en'], { type: 'language' });
const LANG_FIX = { 'es-la': 'Spanish (LatAm)', 'pt-br': 'Portuguese (BR)', 'zh-hk': 'Chinese (HK)', 'ja-ro': 'Japanese (romaji)', 'ko-ro': 'Korean (romaji)', 'zh-ro': 'Chinese (romaji)' };
function langName(code) { try { return LANG_FIX[code] || langNames.of(code) || code; } catch { return code; } }
function cleanMarkdown(s) {
  return (s || '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_]{2,}([^*_]+)[*_]{2,}/g, '$1')
    .replace(/^\s*-{3,}\s*$/gm, '')
    .replace(/^#+\s*/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
function looksLikeLink(s) { return /mangadex\.org\/(title|chapter|manga)\//i.test(s) || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s.trim()); }
function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem('tk.' + k)); localStorage.setItem('tk.' + k, JSON.stringify(v)); } catch { return null; } }

function toast(msg, kind = '') {
  const el = h('div', { class: `toast ${kind}` }, kind === 'error' ? icon('x') : h('span', { class: 'seal' }, '単'), msg);
  $('#toasts').append(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 420); }, kind === 'error' ? 6500 : 3800);
}

// ================================================================ state
const S = {
  me: { logged_in: false, username: '' },
  outDir: '',
  tasks: new Map(),
  manga: null,
  chapters: [],
  sel: new Set(),
  anchor: null,
  vols: [],
  stragglers: [],
  volBy: new Map(),
  vprog: new Map(),          // volume -> 0..1 while it's being bound
  opts: { lang: 'en', group: '', dataSaver: !!store('dataSaver') },
  speed: [],                 // [{t, bytes}] samples
  accent: [255, 90, 54],
  accentTarget: [255, 90, 54],
};
const DEFAULT_ACCENT = ['#ff5a36', '#3fe0d0'];

// ================================================================ dynamic color: steal the palette from the cover
const colorCache = new Map();
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
  if (mx === mn) return [0, 0, l];
  const d = mx - mn, s = l > .5 ? d / (2 - mx - mn) : d / (mx + mn);
  let hh = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [hh * 60, s, l];
}
function hslToRgb(hh, s, l) {
  const k = (n) => (n + hh / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0) * 255, f(8) * 255, f(4) * 255].map(Math.round);
}
async function coverPalette(url) {
  if (!url) return null;
  if (colorCache.has(url)) return colorCache.get(url);
  const p = (async () => {
    const img = new Image();
    img.src = url;
    await img.decode();
    const c = document.createElement('canvas'); c.width = c.height = 48;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, 48, 48);
    const px = ctx.getImageData(0, 0, 48, 48).data;
    const bins = Array.from({ length: 24 }, () => ({ w: 0, h: 0, s: 0 }));
    let avg = [0, 0, 0], n = 0;
    for (let i = 0; i < px.length; i += 4) {
      const [hh, s, l] = rgbToHsl(px[i], px[i + 1], px[i + 2]);
      avg[0] += px[i]; avg[1] += px[i + 1]; avg[2] += px[i + 2]; n++;
      if (l < .12 || l > .92 || s < .22) continue;
      const w = s * s * (1 - Math.abs(l - .5) * 1.4);
      const b = bins[Math.floor(hh / 15) % 24];
      b.w += w; b.h += hh * w; b.s += s * w;
    }
    const ranked = bins.map((b, i) => ({ ...b, i })).filter((b) => b.w > 0).sort((a, b) => b.w - a.w);
    const total = ranked.reduce((a, b) => a + b.w, 0);
    if (!ranked.length || total < 6) return { a: DEFAULT_ACCENT[0], b: DEFAULT_ACCENT[1], spine: `rgb(${avg.map((v) => Math.round(v / n * .7)).join(',')})`, mono: true };
    const top = ranked[0], hue1 = top.h / top.w;
    const second = ranked.find((b) => { const d = Math.abs(b.h / b.w - hue1); return Math.min(d, 360 - d) > 45 && b.w > total * .06; });
    const hue2 = second ? second.h / second.w : (hue1 + 165) % 360;
    const toCss = (hh, s, l) => `rgb(${hslToRgb(hh, s, l).join(',')})`;
    return {
      a: toCss(hue1, Math.max(.65, Math.min(.95, top.s / top.w + .1)), .62),
      b: toCss(hue2, .7, .64),
      spine: toCss(hue1, Math.min(.75, top.s / top.w), .34),
      rgb: hslToRgb(hue1, .8, .6),
    };
  })().catch(() => null);
  colorCache.set(url, p);
  return p;
}
function setAccent(pal) {
  const a = pal?.a || DEFAULT_ACCENT[0], b = pal?.b || DEFAULT_ACCENT[1];
  root.style.setProperty('--accent', a);
  root.style.setProperty('--accent-2', b);
  S.accentTarget = pal?.rgb || [255, 90, 54];
  $('meta[name=theme-color]').setAttribute('content', '#0c0b10');
}
function setBackdrop(url) {
  const bd = $('#backdrop');
  if (url) { bd.style.backgroundImage = `url("${url}")`; bd.classList.add('on'); }
  else bd.classList.remove('on');
}

// ================================================================ the living screentone
function screentone() {
  const cv = $('#tone'), ctx = cv.getContext('2d');
  let W = 0, H = 0, t = Math.random() * 100, last = 0;
  const mouse = { x: -9999, y: -9999, tx: -9999, ty: -9999 };
  const GAP = 19;
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (reduced) draw();
  }
  addEventListener('resize', resize);
  addEventListener('pointermove', (e) => { mouse.tx = e.clientX; mouse.ty = e.clientY; }, { passive: true });
  function draw() {
    ctx.clearRect(0, 0, W, H);
    for (let k = 0; k < 3; k++) S.accent[k] += (S.accentTarget[k] - S.accent[k]) * .04;
    mouse.x += (mouse.tx - mouse.x) * .12; mouse.y += (mouse.ty - mouse.y) * .12;
    const [r, g, b] = S.accent.map(Math.round);
    ctx.fillStyle = `rgba(${r},${g},${b},.30)`;
    ctx.beginPath();
    let row = 0;
    for (let y = GAP / 2; y < H + GAP; y += GAP, row++) {
      const off = row % 2 ? GAP / 2 : 0;
      const fade = .15 + .85 * Math.pow(y / H, 1.6);
      for (let x = off; x < W + GAP; x += GAP) {
        const n = Math.sin(x * .0062 + t * .55) * Math.cos(y * .0091 - t * .38) + Math.sin((x - y) * .0034 + t * .27);
        let rad = (n + 2) * .62 * fade;
        const dx = x - mouse.x, dy = y - mouse.y, d2 = dx * dx + dy * dy;
        if (d2 < 52000) rad += (1 - Math.sqrt(d2) / 228) * 4.2;
        if (rad < .35) continue;
        ctx.moveTo(x + rad, y);
        ctx.arc(x, y, rad, 0, 6.2832);
      }
    }
    ctx.fill();
  }
  function loop(now) {
    requestAnimationFrame(loop);
    if (document.hidden || now - last < 33) return;
    last = now; t += .02;
    draw();
  }
  resize();
  if (!reduced) requestAnimationFrame(loop);
}

// ================================================================ router
const view = $('#view');
function route() {
  const raw = location.hash.slice(1) || '/';
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  const q = new URLSearchParams(qs || '');
  $$('.nav a').forEach((a) => a.classList.toggle('on', a.dataset.nav === (parts[0] === 'library' ? 'library' : parts[0] ? '' : 'home')));
  closeDrawer();
  if (press.firstChild) togglePress(false);
  let el;
  if (parts[0] === 'manga' && parts[1]) el = viewManga(parts[1], q);
  else if (parts[0] === 'library') el = viewLibrary(q.get('s'));
  else el = viewHome(q.get('q'));
  const swap = () => { view.replaceChildren(el); scrollTo(0, 0); };
  if (document.startViewTransition && !reduced && view.childElementCount) document.startViewTransition(swap);
  else swap();
}
const nav = (hash) => { location.hash = hash; };
// remember where the user clicked so the ink-wipe transition starts there
addEventListener('pointerdown', (e) => { root.style.setProperty('--vx', e.clientX + 'px'); root.style.setProperty('--vy', e.clientY + 'px'); }, { capture: true, passive: true });

async function openTarget(text) {
  text = (text || '').trim();
  if (!text) return;
  if (!looksLikeLink(text)) { nav(`#/?q=${enc(text)}`); return; }
  const form = $('.q-form'); form?.classList.add('busy');
  try {
    const r = await get(`/api/search?q=${enc(text)}`);
    if (r.kind === 'manga') nav(`#/manga/${r.id}` + (r.chapter ? `?ch=${r.chapter}&lang=${r.lang || ''}` : ''));
  } catch (e) { toast(e.message, 'error'); }
  finally { form?.classList.remove('busy'); }
}

// ================================================================ tilt
function tilt(el, max = 10) {
  el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    el.style.setProperty('--ry', `${(x - .5) * max * 2}deg`);
    el.style.setProperty('--rx', `${(.5 - y) * max * 2}deg`);
    el.style.setProperty('--gx', `${x * 100}%`);
    el.style.setProperty('--gy', `${y * 100}%`);
  });
  el.addEventListener('pointerleave', () => { el.style.setProperty('--rx', '0deg'); el.style.setProperty('--ry', '0deg'); });
  return el;
}

// ================================================================ home
const EXAMPLES = ['https://mangadex.org/title/…', 'The Girl From the Other Side', 'Tomo-chan wa Onna no ko', 'a chapter link works too', 'Yotsuba', 'Kaguya-sama'];
function typewriter(el) {
  let i = 0, j = 0, del = false, alive = true, seen = false;
  const caret = h('span', { class: 'caret' }), txt = h('span');
  el.replaceChildren('Try  ', txt, caret);
  (function tick() {
    if (!alive) return;
    if (!el.isConnected) { if (!seen) setTimeout(tick, 120); return; }  // wait until the view is mounted
    seen = true;
    const word = EXAMPLES[i % EXAMPLES.length];
    j += del ? -1 : 1;
    txt.textContent = word.slice(0, j);
    let wait = del ? 28 : 60;
    if (!del && j === word.length) { del = true; wait = 1700; }
    else if (del && j === 0) { del = false; i++; wait = 300; }
    setTimeout(tick, wait);
  })();
  return () => { alive = false; };
}

function mangaCard(m, i = 0) {
  const cover = h('div', { class: 'mcard-cover' },
    m.cover ? h('img', { src: m.cover, alt: '', loading: 'lazy', decoding: 'async' }) : h('div', { class: 'noimg' }, '単'),
    m.contentRating && m.contentRating !== 'safe' ? h('span', { class: 'badge' }, m.contentRating) : null);
  tilt(cover, 9);
  return h('a', { class: 'mcard', href: `#/manga/${m.id}`, style: { '--i': i } },
    cover,
    h('div', { class: 'mcard-title' }, m.title),
    h('div', { class: 'mcard-meta' }, [m.year, m.status, m.reading_status?.replace(/_/g, ' ')].filter(Boolean).join(' · ')),
    m.tags?.length ? h('div', { class: 'mcard-tags' }, m.tags.slice(0, 3).map((t) => h('span', {}, t))) : null);
}
const skelCards = (n) => h('div', { class: 'mgrid' }, Array.from({ length: n }, () => h('div', {}, h('div', { class: 'skel', style: { 'aspect-ratio': '5/7' } }), h('div', { class: 'skel', style: { height: '14px', 'margin-top': '12px', width: '80%' } }))));

function viewHome(query) {
  setAccent(null); setBackdrop(null); S.manga = null; updateBindbar();
  const input = h('input', { class: 'q-input', id: 'q', placeholder: ' ', autocomplete: 'off', spellcheck: 'false', value: query || '', 'aria-label': 'MangaDex link or title' });
  const label = h('label', { class: 'q-label', for: 'q' });
  const results = h('section', { class: 'results' });
  const form = h('form', { class: 'q-form', onsubmit: (e) => { e.preventDefault(); openTarget(input.value); } },
    icon('search'), input, label,
    h('button', { class: 'q-go', type: 'submit' }, h('span', { class: 't' }, 'OPEN'), icon('arrow')));
  input.addEventListener('paste', () => setTimeout(() => { if (looksLikeLink(input.value)) openTarget(input.value); }, 0));
  typewriter(label);

  const el = h('div', { class: 'view home' },
    h('section', { class: 'hero' },
      h('div', { class: 'hero-kicker vertical' }, 'MANGADEX → CBZ ／ 単行本'),
      h('h1', { class: 'hero-title' },
        h('span', { class: 'ln' }, h('span', { style: { '--d': 0 } }, 'Paste a link.')),
        h('span', { class: 'ln' }, h('span', { style: { '--d': 1 } }, 'Get a ', h('em', { class: 'ink' }, 'book'), '.'))),
      h('p', { class: 'hero-sub' }, 'Drop in any MangaDex title or chapter URL, or just type a name. Tankōbon binds each volume into its own .cbz, with its own cover, ready to AirDrop to your comic reader.'),
      form,
      h('div', { class: 'hint' }, h('kbd', {}, '⌘V'), ' anywhere to paste a link', h('span', { style: { opacity: .4 } }, '·'), 'drag one in', h('span', { style: { opacity: .4 } }, '·'), h('kbd', {}, '/'), ' to search')),
    results,
    h('section', { id: 'homeAccount' }),
    h('section', { id: 'homeShelf' }));

  if (query) runSearch(query, results);
  else setTimeout(() => input.focus({ preventScroll: true }), 80);
  loadHomeAccount(el.querySelector('#homeAccount'));
  loadHomeShelf(el.querySelector('#homeShelf'));
  return el;
}

async function runSearch(q, box) {
  box.replaceChildren(h('div', { class: 'sec-head' }, h('h2', {}, 'Searching…')), skelCards(6));
  try {
    const r = await get(`/api/search?q=${enc(q)}`);
    if (r.kind === 'manga') return nav(`#/manga/${r.id}`);
    if (!r.results.length) {
      box.replaceChildren(h('div', { class: 'sec-head' }, h('h2', {}, 'Nothing found')), h('div', { class: 'empty-note' }, h('span', { class: 'seal big' }, '無'), h('div', {}, h('b', {}, `No manga matches “${q}”`), 'Try the romanized title, or paste the MangaDex link directly.')));
      return;
    }
    box.replaceChildren(
      h('div', { class: 'sec-head' }, h('h2', {}, 'Results'), h('span', { class: 'jp' }, '検索'), h('span', { class: 'sub' }, `${r.results.length} matches for “${q}”`)),
      h('div', { class: 'mgrid' }, r.results.map(mangaCard)));
  } catch (e) { box.replaceChildren(h('div', { class: 'empty-note' }, e.message)); }
}

async function loadHomeAccount(box) {
  if (!S.me.logged_in) {
    box.replaceChildren(h('div', { class: 'connect' },
      h('div', { class: 'big-icon' }, icon('user')),
      h('div', {}, h('h3', {}, 'Bring your MangaDex account'), h('p', {}, 'See fresh chapters from everything you follow, your reading lists and custom lists, and bind any of them in one click.')),
      h('button', { class: 'btn solid', onclick: openLogin }, 'Connect', icon('arrow'))));
    return;
  }
  const upd = h('div', { class: 'hscroll' }, Array.from({ length: 4 }, () => h('div', { class: 'upd skel', style: { height: '116px' } })));
  const followBox = h('div', {}, skelCards(6));
  box.replaceChildren(
    h('div', { class: 'sec-head' }, h('h2', {}, 'Fresh off the press'), h('span', { class: 'jp' }, '新着'), h('span', { class: 'sub' }, 'new chapters from series you follow')),
    upd,
    h('div', { class: 'sec-head' }, h('h2', {}, 'Your follows'), h('span', { class: 'jp' }, '本棚')),
    followBox);
  get(`/api/me/updates?lang=${enc(S.opts.lang)}`).then((items) => {
    if (!items.length) { upd.replaceChildren(h('div', { class: 'empty-note' }, 'No new chapters in your follows feed.')); return; }
    upd.replaceChildren(...items.map((c, i) => {
      const card = h('a', { class: 'upd', href: `#/manga/${c.manga.id}?ch=${c.id}&lang=${c.lang}`, style: { '--i': i } },
        c.manga.cover ? h('img', { src: c.manga.cover, alt: '', loading: 'lazy' }) : h('div', { class: 'ph' }),
        h('div', { style: { 'min-width': 0 } },
          h('div', { class: 't' }, c.manga.title),
          h('div', { class: 'c' }, c.volume ? `Vol. ${c.volume} · ${c.label}` : `${c.label} · awaiting volume`),
          h('div', { class: 'm' }, `${ago(c.date)} · ${c.groups[0] || 'no group'}`)));
      return card;
    }));
  }).catch((e) => upd.replaceChildren(h('div', { class: 'empty-note' }, e.message)));

  Promise.all([get('/api/me/follows'), get('/api/me/lists').catch(() => [])]).then(([f, lists]) => {
    const groups = [['all', 'All', f.manga]];
    const order = ['reading', 'plan_to_read', 'on_hold', 're_reading', 'completed', 'dropped'];
    for (const st of order) {
      const items = f.manga.filter((m) => m.reading_status === st);
      if (items.length) groups.push([st, st.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()), items]);
    }
    for (const l of lists) if (l.manga.length) groups.push([`list:${l.id}`, `☰ ${l.name}`, l.manga]);
    let cur = store('followTab') || 'reading';
    if (!groups.find((g) => g[0] === cur)) cur = groups[1]?.[0] || 'all';
    const tabs = h('div', { class: 'tabs' }), grid = h('div');
    const paint = () => {
      tabs.replaceChildren(...groups.map(([k, name, items]) => h('button', { class: `tab ${k === cur ? 'on' : ''}`, onclick: () => { cur = k; store('followTab', k); paint(); } }, name, h('b', {}, items.length))));
      const items = groups.find((g) => g[0] === cur)[2];
      grid.replaceChildren(items.length ? h('div', { class: 'mgrid' }, items.map(mangaCard)) : h('div', { class: 'empty-note' }, 'You aren’t following anything yet.'));
    };
    paint();
    followBox.replaceChildren(tabs, grid);
  }).catch((e) => followBox.replaceChildren(h('div', { class: 'empty-note' }, e.message)));
}

async function loadHomeShelf(box) {
  try {
    const { series } = await get('/api/library');
    if (!series.length) return;
    box.replaceChildren(
      h('div', { class: 'sec-head' }, h('h2', {}, 'On your shelf'), h('span', { class: 'jp' }, '蔵書'), h('span', { class: 'spacer' }), h('a', { class: 'btn sm', href: '#/library' }, 'Open shelf', icon('arrow'))),
      h('div', { class: 'shelf-strip' }, series.slice(0, 12).map((s, i) => bookEl(s, i, () => nav(`#/library?s=${enc(s.dir)}`)))));
  } catch {}
}

// ================================================================ manga page
function burstSvg() {
  let d = '';
  for (let i = 0; i < 90; i++) {
    const a = (i / 90) * Math.PI * 2 + Math.random() * .03, w = .004 + Math.random() * .014, r = 500;
    d += `M0 0L${(Math.cos(a - w) * r).toFixed(1)} ${(Math.sin(a - w) * r).toFixed(1)}L${(Math.cos(a + w) * r).toFixed(1)} ${(Math.sin(a + w) * r).toFixed(1)}Z`;
  }
  return h('div', { class: 'burst', 'aria-hidden': 'true', html: `<svg viewBox="-500 -500 1000 1000" width="100%" height="100%"><path d="${d}" fill="currentColor"/></svg>` });
}

function viewManga(id, q) {
  updateBindbar();
  const el = h('div', { class: 'view manga' },
    h('section', { class: 'mhero' },
      h('div', { class: 'mhero-art' }, h('div', { class: 'skel', style: { 'aspect-ratio': '5/7', 'border-radius': '14px' } })),
      h('div', {}, h('div', { class: 'skel', style: { height: '14px', width: '220px' } }), h('div', { class: 'skel', style: { height: '72px', width: '80%', margin: '22px 0' } }), h('div', { class: 'skel', style: { height: '90px', width: '60%' } }))));
  if (S.manga?.id !== id) { S.sel = new Set(); S.anchor = null; S.chapters = []; S.vols = []; S.stragglers = []; S.groups = []; S.volBy = new Map(); }
  get(`/api/manga/${id}`).then((m) => {
    if (!el.isConnected && view.firstChild !== el) { /* still render: transition may not have swapped yet */ }
    S.manga = m;
    document.title = `${m.title} · Tankōbon`;
    renderMangaHero(el, m);
    coverPalette(m.cover_lg || m.cover).then(setAccent);
    setBackdrop(m.cover_lg || m.cover);
    const want = q.get('lang');
    const pref = store('lang') || 'en';
    S.opts.lang = (want && m.languages.includes(want)) ? want : m.languages.includes(pref) ? pref : m.languages.includes('en') ? 'en' : (m.languages[0] || 'en');
    S.opts.group = '';
    loadChapters(q.get('ch'));
  }).catch((e) => {
    el.replaceChildren(h('div', { class: 'empty-note', style: { 'margin-top': '60px' } }, h('span', { class: 'seal big' }, '無'), h('div', {}, h('b', {}, 'Couldn’t open that manga'), e.message)));
  });
  return el;
}

function renderMangaHero(el, m) {
  const ja = m.altTitles.find((t) => t.lang === 'ja' && /[\u3040-\u30ff\u4e00-\u9fff]/.test(t.title))?.title;
  const romaji = m.altTitles.find((t) => t.lang === 'ja-ro')?.title;
  const cover = h('div', { class: 'cover3d' }, h('img', { src: m.cover_lg || m.cover, alt: `${m.title} cover` }), h('div', { class: 'glare' }));
  tilt(cover, 12);
  const desc = h('p', { class: 'desc clamp' }, cleanMarkdown(m.description) || 'No description.');
  const more = h('button', { class: 'more', onclick: () => { desc.classList.toggle('clamp'); more.textContent = desc.classList.contains('clamp') ? 'Read more' : 'Show less'; } }, 'Read more');
  const stats = [
    m.stats.rating ? ['★ ' + m.stats.rating.toFixed(2), 'rating', 'star'] : null,
    [fmtNum(m.stats.follows), 'follows'],
    ['…', 'volumes', 'chcount'],
    m.lastVolume ? [m.lastVolume, 'final vol.'] : null,
  ].filter(Boolean);
  const warn = new Set(['Gore', 'Sexual Violence']);
  el.replaceChildren(
    h('section', { class: 'mhero' },
      h('div', { class: 'mhero-art' }, burstSvg(), cover),
      h('div', { class: 'mhero-info' },
        h('div', { class: 'eyebrow' }, [m.demographic, m.year, m.status, m.contentRating !== 'safe' ? m.contentRating : null, m.originalLanguage ? `orig. ${m.originalLanguage}` : null].filter(Boolean).map((x) => h('span', {}, String(x)))),
        h('h1', { class: 'mtitle' }, m.title),
        romaji && romaji !== m.title ? h('div', { class: 'alt' }, romaji) : null,
        h('div', { class: 'byline' }, 'by ', h('b', {}, m.authors.join(', ') || 'unknown'), m.artists.length && m.artists.join() !== m.authors.join() ? [' · art ', h('b', {}, m.artists.join(', '))] : null),
        h('div', { class: 'statrow' }, stats.map(([v, l, cls], i) => h('div', { class: `stat ${cls || ''}`, style: { '--i': i } }, h('b', {}, v), h('small', {}, l)))),
        h('div', { class: 'tags' }, m.tags_all.filter((t) => t.group !== 'format' || true).slice(0, 14).map((t) => h('span', { class: `${t.group === 'theme' ? 'theme' : ''} ${warn.has(t.name) ? 'warn' : ''}` }, t.name))),
        desc, m.description.length > 300 ? more : null,
        h('div', { class: 'mactions' },
          h('a', { class: 'btn', href: m.url, target: '_blank', rel: 'noopener' }, 'MangaDex', icon('ext')),
          m.local_dir ? h('a', { class: 'btn', href: `#/library?s=${enc(m.local_dir)}` }, icon('book'), 'On your shelf') : null)),
      ja ? h('div', { class: 'vtitle', 'aria-hidden': 'true' }, ja) : null),
    h('section', { class: 'chapters-sec', id: 'chapters' },
      h('div', { class: 'sec-head' }, h('h2', {}, 'Volumes'), h('span', { class: 'jp' }, '単行本'), h('span', { class: 'sub', id: 'chSub' }, 'loading…')),
      h('div', { class: 'toolbar', id: 'toolbar' }),
      h('div', { id: 'chBody' }, h('div', { class: 'skel', style: { height: '110px', 'margin-top': '40px' } }))));
}

async function loadChapters(focusId) {
  const m = S.manga;
  renderToolbar();
  const body = $('#chBody');
  try {
    const d = await get(`/api/manga/${m.id}/chapters?lang=${enc(S.opts.lang)}&group=${enc(S.opts.group)}`);
    if (S.manga !== m) return;
    S.chapters = d.chapters;
    S.groups = d.groups;
    S.vols = d.volumes;
    S.stragglers = d.stragglers;
    S.chapters.forEach((c, i) => { c.i = i; });
    S.volBy = new Map(S.vols.map((v) => [v.volume, v]));
    for (const v of [...S.sel]) if (!S.volBy.has(v)) S.sel.delete(v);
    renderToolbar();
    const statEl = $('.stat.chcount b'); if (statEl) statEl.textContent = S.vols.length;
    const onShelf = S.vols.filter((v) => v.downloaded).length;
    $('#chSub').textContent = S.chapters.length
      ? `${S.vols.length} volume${S.vols.length === 1 ? '' : 's'} in ${langName(S.opts.lang)} · ${onShelf} on your shelf${S.stragglers.length ? ` · ${S.stragglers.length} chapter${S.stragglers.length === 1 ? '' : 's'} waiting` : ''}`
      : '';
    if (!S.chapters.length) { body.replaceChildren(noChapters(m)); updateBindbar(); return; }
    body.replaceChildren(...[quickBar(), stripEl(), volGrid(), straggleEl()].filter(Boolean));
    paint();
    const focus = focusId && S.chapters.find((x) => x.id === focusId);
    if (focus) {
      const target = focus.volume ? S.volCards.get(focus.volume) : focus._chip;
      if (target) setTimeout(() => { target.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }); target.classList.add('target'); }, 500);
    }
  } catch (e) { body.replaceChildren(h('div', { class: 'empty-note' }, e.message)); }
}

function noChapters(m) {
  const others = m.languages.filter((l) => l !== S.opts.lang);
  return h('div', { class: 'no-chapters' },
    h('span', { class: 'seal big' }, '無'),
    h('div', {},
      h('h3', {}, `No hosted chapters in ${langName(S.opts.lang)}`),
      h('p', {}, 'This usually means the series is licensed and MangaDex only links out to an official reader (MangaPlus, Comikey…), so there are no pages to bind.'),
      others.length ? [h('p', { style: { 'margin-bottom': '8px' } }, 'Other languages that may have pages:'), h('div', { class: 'langs' }, others.map((l) => h('button', { class: 'qchip', onclick: () => { S.opts.lang = l; loadChapters(); } }, langName(l))))] : null));
}

function renderToolbar() {
  const tb = $('#toolbar'); if (!tb) return;
  const m = S.manga;
  const langSel = h('select', { onchange: (e) => { S.opts.lang = e.target.value; store('lang', S.opts.lang); S.opts.group = ''; loadChapters(); } },
    m.languages.slice().sort((a, b) => langName(a).localeCompare(langName(b))).map((l) => h('option', { value: l }, langName(l))));
  langSel.value = S.opts.lang;
  const groupSel = h('select', { onchange: (e) => { S.opts.group = e.target.value; loadChapters(); } },
    h('option', { value: '' }, 'Best mix (auto)'),
    (S.groups || []).slice(0, 40).map((g) => h('option', { value: g.name }, `${g.name} (${g.count})`)));
  groupSel.value = S.opts.group;
  const ds = h('label', { class: 'switch', title: 'Compressed, smaller images' }, h('input', { type: 'checkbox', checked: S.opts.dataSaver, onchange: (e) => { S.opts.dataSaver = e.target.checked; store('dataSaver', S.opts.dataSaver); updateBindbar(); } }), h('i'), 'Data saver');
  tb.replaceChildren(
    h('div', { class: 'field' }, h('span', { class: 'lbl' }, 'Lang'), langSel),
    h('div', { class: 'field', title: 'When several groups translated a chapter, which one to use' }, h('span', { class: 'lbl' }, 'Group'), groupSel),
    ds, h('span', { class: 'grow' }),
    h('button', { class: 'btn sm ghost', title: 'Show the library folder in Finder', onclick: () => post('/api/reveal', { path: '' }) }, icon('folder'), h('span', { class: 'dl-dir' }, S.outDir)));
}

function quickBar() {
  const range = h('input', { class: 'range-in', placeholder: 'volumes, e.g. 1-3, 5', 'aria-label': 'Select volumes by number', onkeydown: (e) => { if (e.key === 'Enter') { selectRanges(range.value); range.blur(); } } });
  const chip = (label, fn) => h('button', { class: 'qchip', onclick: () => { fn(); paint(); } }, label);
  return h('div', { class: 'quick' },
    chip('All volumes', () => S.vols.forEach((v) => S.sel.add(v.volume))),
    chip('Not on shelf', () => { S.sel.clear(); S.vols.filter((v) => !v.downloaded).forEach((v) => S.sel.add(v.volume)); }),
    chip('No gaps', () => { S.sel.clear(); S.vols.filter((v) => !v.gaps.length && !v.downloaded).forEach((v) => S.sel.add(v.volume)); }),
    chip('Newest', () => { S.sel.clear(); if (S.vols.length) S.sel.add(S.vols[S.vols.length - 1].volume); }),
    chip('None', () => S.sel.clear()),
    range,
    h('span', { class: 'tip' }, 'Click covers to pick volumes · shift-click for a run · or drag across the strip'));
}
function selectRanges(spec) {
  const ranges = spec.split(',').map((p) => p.trim()).filter(Boolean).map((p) => {
    if (p.includes('-')) { const [a, b] = p.split('-'); return [a.trim() ? +a : -Infinity, b.trim() ? +b : Infinity]; }
    return [+p, +p];
  }).filter(([a, b]) => !isNaN(a) && !isNaN(b));
  if (!ranges.length) return toast('Use volume numbers like 1-3, 5', 'error');
  S.sel.clear();
  for (const v of S.vols) { const n = parseFloat(v.volume); if (!isNaN(n) && ranges.some(([a, b]) => n >= a && n <= b)) S.sel.add(v.volume); }
  paint();
  if (!S.sel.size) toast('No volumes in that range', 'error');
}

// ---- the barcode strip: one bar per chapter, grouped by volume. Dragging selects every volume it touches.
function stripEl() {
  const strip = h('div', { class: 'strip', role: 'img', 'aria-label': 'Chapters by volume; drag to select volumes' });
  const tip = h('div', { class: 'strip-tip' });
  const maxP = Math.max(1, ...S.chapters.map((c) => c.pages));
  const runs = [];
  S.chapters.forEach((c, i) => {
    const last = runs[runs.length - 1];
    if (last && last.vol === c.volume) last.n++; else runs.push({ vol: c.volume, start: i, n: 1 });
  });
  let r = 0;
  S.chapters.forEach((c, i) => {
    if (runs[r + 1]?.start === i) r++;
    if (runs[r].start === i) {
      const sep = h('div', { class: 'vsep', style: i === 0 ? { width: '0', margin: '0' } : {} });
      if (runs[r].n >= 3) sep.dataset.label = c.volume ? `V${c.volume}` : '…';
      strip.append(sep);
    }
    const bar = h('div', { class: 'bar', style: { '--h': (0.22 + 0.78 * Math.sqrt(c.pages / maxP)).toFixed(3), '--i': Math.min(i, 400) } }, h('i'));
    bar.dataset.i = i;
    c._bar = bar;
    strip.append(bar);
  });

  let drag = null;
  const barAt = (x) => {  // binary search by x — bars are 3px wide, so point-probing misses gaps
    const list = S.chapters;
    if (!list.length || !list[0]._bar?.isConnected) return null;
    let lo = 0, hi = list.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid]._bar.getBoundingClientRect().right < x) lo = mid + 1; else hi = mid;
    }
    return list[lo]._bar;
  };
  const volsIn = (a, b) => { const s = new Set(); for (let i = Math.min(a, b); i <= Math.max(a, b); i++) if (S.chapters[i].volume) s.add(S.chapters[i].volume); return s; };
  const showTip = (bar) => {
    if (!bar) { tip.classList.remove('show'); return; }
    const c = S.chapters[+bar.dataset.i];
    const v = c.volume && S.volBy.get(c.volume);
    tip.replaceChildren(h('b', {}, c.volume ? `Vol. ${c.volume}` : 'No volume yet'), `  ·  ${c.label}  ·  ${c.pages}p`, v?.downloaded ? '  ·  ✓ on shelf' : '',
      h('small', {}, c.volume ? ([c.title, c.groups[0]].filter(Boolean).join(' — ') || 'untitled') : 'waits until MangaDex puts it in a volume'));
    const wr = strip.parentElement.parentElement.getBoundingClientRect(), br = bar.getBoundingClientRect();
    tip.style.left = Math.max(90, Math.min(wr.width - 90, br.left - wr.left + br.width / 2)) + 'px';
    tip.classList.add('show');
  };
  const preview = () => {
    const touched = volsIn(drag.start, drag.end);
    for (const c of S.chapters) {
      const on = !!c.volume && touched.has(c.volume);
      c._bar.classList.toggle('brush', on);
      c._bar.classList.toggle('unbrush', on && drag.mode === 'remove');
    }
  };
  strip.addEventListener('pointerdown', (e) => {
    const bar = barAt(e.clientX); if (!bar) return;
    e.preventDefault();
    try { strip.setPointerCapture(e.pointerId); } catch {}
    const i = +bar.dataset.i, v = S.chapters[i].volume;
    drag = { start: i, end: i, mode: v && S.sel.has(v) ? 'remove' : 'add' };
    preview();
  });
  strip.addEventListener('pointermove', (e) => {
    const bar = barAt(e.clientX);
    showTip(bar);
    if (drag && bar) { drag.end = +bar.dataset.i; preview(); }
  });
  const finish = () => {
    if (!drag) return;
    for (const v of volsIn(drag.start, drag.end)) drag.mode === 'add' ? S.sel.add(v) : S.sel.delete(v);
    S.chapters.forEach((c) => c._bar.classList.remove('brush', 'unbrush'));
    drag = null;
    paint();
  };
  strip.addEventListener('pointerup', finish);
  strip.addEventListener('pointercancel', finish);
  strip.addEventListener('pointerleave', () => { if (!drag) tip.classList.remove('show'); });

  return h('div', { class: 'strip-wrap' },
    h('div', { class: 'strip-scroll' }, strip), tip,
    h('div', { class: 'strip-legend' },
      h('span', {}, h('i', { style: { background: 'rgba(243,239,230,.16)' } }), 'in a volume'),
      h('span', {}, h('i', { class: 'hatch' }), 'waiting for a volume'),
      h('span', {}, h('i', { style: { background: 'color-mix(in srgb, var(--ok) 70%, var(--paper))' } }), 'on your shelf'),
      h('span', {}, h('i', { style: { background: 'var(--accent)' } }), 'selected'),
      h('span', { style: { 'margin-left': 'auto' } }, 'one bar per chapter · height = page count')));
}

// ---- volume covers
function gapText(gaps) {
  const out = [];
  for (let i = 0; i < gaps.length; i++) {
    let j = i;
    while (j + 1 < gaps.length && gaps[j + 1] === gaps[j] + 1) j++;
    out.push(i === j ? `${gaps[i]}` : `${gaps[i]}–${gaps[j]}`);
    i = j;
  }
  return out.join(', ');
}
function volGrid() {
  S.volCards = new Map();
  if (!S.vols.length) {
    return h('div', { class: 'empty-note' }, h('span', { class: 'seal big' }, '待'),
      h('div', {}, h('b', {}, 'No volumes yet'), 'MangaDex hasn’t grouped any of these chapters into volumes. Once it does, they’ll show up here ready to bind.'));
  }
  return h('div', { class: 'vgrid' }, S.vols.map((v, k) => {
    const range = v.first && v.last ? (v.first === v.last ? `Ch. ${v.first}` : `Ch. ${v.first}–${v.last}`) : `${v.count} ch`;
    const cover = h('div', { class: 'vcover' },
      v.cover ? h('img', { src: v.cover, alt: `Volume ${v.volume} cover`, loading: 'lazy', decoding: 'async' }) : h('div', { class: 'vph' }, h('span', {}, 'VOL'), v.volume),
      h('span', { class: 'vstamp' }, icon('check')),
      h('span', { class: 'vribbon' }, '✓ ON SHELF'),
      h('span', { class: 'vbusy' }, h('i')));
    tilt(cover, 8);
    const card = h('button', {
      class: 'vcard', style: { '--i': Math.min(k, 30) }, 'aria-pressed': 'false',
      title: `${v.label} · ${v.count} chapters · ${v.pages} pages${v.groups.length ? '\n' + v.groups.join(', ') : ''}${v.gaps.length ? `\nMissing chapters: ${gapText(v.gaps)}` : ''}`,
      onclick: (e) => clickVol(k, e),
    }, cover,
      h('div', { class: 'vinfo' },
        h('b', {}, `Vol. ${v.volume}`),
        h('small', {}, `${range} · ${v.pages}p`),
        v.gaps.length ? h('span', { class: 'vwarn' }, `missing ch. ${gapText(v.gaps)}`) : null));
    S.volCards.set(v.volume, card);
    return card;
  }));
}
function clickVol(k, e) {
  const v = S.vols[k];
  if (e.shiftKey && S.anchor != null && S.vols[S.anchor]) {
    const on = S.sel.has(S.vols[S.anchor].volume);
    const [a, b] = [Math.min(S.anchor, k), Math.max(S.anchor, k)];
    for (let i = a; i <= b; i++) on ? S.sel.add(S.vols[i].volume) : S.sel.delete(S.vols[i].volume);
  } else {
    S.sel.has(v.volume) ? S.sel.delete(v.volume) : S.sel.add(v.volume);
    S.anchor = k;
  }
  paint();
}
function straggleEl() {
  if (!S.stragglers.length) return null;
  const n = S.stragglers.length;
  return h('section', { class: 'waiting' },
    h('div', { class: 'sec-head' }, h('h2', {}, 'Waiting for a volume'), h('span', { class: 'jp' }, '未収録'),
      h('span', { class: 'sub' }, `${n} chapter${n === 1 ? '' : 's'} not collected into a volume yet. They’ll be bindable once MangaDex tags them.`)),
    h('div', { class: 'wchips' }, S.stragglers.map((c) => {
      const chip = h('span', { class: 'wchip', title: [c.title, c.groups[0], ago(c.date)].filter(Boolean).join(' · ') }, c.chapter ? `#${c.chapter}` : '★');
      const full = S.chapters.find((x) => x.id === c.id); if (full) full._chip = chip;
      return chip;
    })));
}

function paint() {
  for (const c of S.chapters) {
    const v = c.volume && S.volBy.get(c.volume);
    c._bar?.classList.toggle('sel', !!v && S.sel.has(c.volume));
    c._bar?.classList.toggle('have', !!v && v.downloaded);
    c._bar?.classList.toggle('loose', !v);
  }
  for (const v of S.vols || []) {
    const card = S.volCards?.get(v.volume); if (!card) continue;
    const sel = S.sel.has(v.volume);
    card.classList.toggle('sel', sel);
    card.classList.toggle('have', !!v.downloaded);
    card.setAttribute('aria-pressed', String(sel));
    paintVolProgress(v.volume);
  }
  updateBindbar();
}
function paintVolProgress(vol) {
  const card = S.volCards?.get(vol); if (!card) return;
  const p = S.vprog.get(vol);
  card.classList.toggle('busy', p != null);
  card.style.setProperty('--p', p ?? 0);
}

// ---- bind bar
const bindbar = h('div', { class: 'bindbar', role: 'region', 'aria-label': 'Selection' });
document.body.append(bindbar);
function updateBindbar() {
  const on = !!S.manga && S.sel.size > 0 && location.hash.startsWith('#/manga/');
  bindbar.classList.toggle('show', on);
  document.body.classList.toggle('has-bindbar', on);
  if (!on) return;
  const chosen = (S.vols || []).filter((v) => S.sel.has(v.volume));
  const pages = chosen.reduce((a, v) => a + v.pages, 0);
  const per = S.opts.dataSaver ? 110e3 : 330e3;
  const have = chosen.filter((v) => v.downloaded).length;
  const gappy = chosen.filter((v) => v.gaps.length).length;
  bindbar.replaceChildren(
    h('div', { class: 'n' }, S.sel.size),
    h('div', { class: 'what' }, h('b', {}, `volume${S.sel.size === 1 ? '' : 's'} selected`),
      h('small', {}, [`${pages.toLocaleString()} pages`, `≈${fmtBytes(pages * per)}`, have ? `${have} already on shelf` : null, gappy ? `${gappy} with missing chapters` : null].filter(Boolean).join(' · '))),
    h('span', { class: 'sp' }),
    h('button', { class: 'btn ghost sm', onclick: () => { S.sel.clear(); paint(); } }, 'Clear'),
    h('button', { class: 'bind-btn', onclick: bind }, h('span', { class: 'seal' }, '製'), 'BIND', icon('arrow')));
}
async function bind(e) {
  const btn = e.currentTarget; btn.disabled = true;
  const vols = S.vols.filter((v) => S.sel.has(v.volume)).map((v) => v.volume);
  try {
    const r = await post('/api/download', { manga_id: S.manga.id, volumes: vols, lang: S.opts.lang, data_saver: S.opts.dataSaver, group: S.opts.group });
    flyToPress(vols.map((v) => S.volCards.get(v)).filter(Boolean));
    if (r.tasks.length) toast(`${r.tasks.length} volume${r.tasks.length === 1 ? '' : 's'} sent to the press${r.skipped.length ? ` · ${r.skipped.length} already bound` : ''}`);
    else toast('Those volumes are already on your shelf');
    S.sel.clear(); paint();
  } catch (err) { toast(err.message, 'error'); }
  finally { btn.disabled = false; }
}

function pressTarget() {
  const p = $('.press-pill');
  if (p) { const r = p.getBoundingClientRect(); return [r.left + 28, r.top + 28]; }
  return [innerWidth - 60, innerHeight - 60];
}
function flyToPress(cards) {
  if (reduced) return;
  const vis = cards.filter((c) => { const r = c.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; }).slice(0, 18);
  vis.forEach((card, k) => flyFrom(card, k * 35));
}
function flyFrom(el, delay = 0) {
  if (reduced) return;
  const r = el.getBoundingClientRect();
  const [tx, ty] = pressTarget();
  const f = h('div', { class: 'flyer', style: { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' } });
  document.body.append(f);
  const dx = tx - (r.left + r.width / 2), dy = ty - (r.top + r.height / 2);
  f.animate([
    { transform: 'translate(0,0) scale(1)', opacity: .9, borderRadius: '12px' },
    { transform: `translate(${dx * .5}px, ${dy * .5 - 120}px) scale(.35) rotate(${dx > 0 ? 25 : -25}deg)`, opacity: .9, offset: .55 },
    { transform: `translate(${dx}px, ${dy}px) scale(.05) rotate(60deg)`, opacity: .2, borderRadius: '50%' },
  ], { duration: 820, delay, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'both' }).onfinish = () => { f.remove(); $('.press-pill')?.classList.remove('bump'); void $('.press-pill')?.offsetWidth; $('.press-pill')?.classList.add('bump'); };
}

// ================================================================ the press (live download dock)
const press = $('#press');
let pressOpen = false;
const fanPages = [];
function buildPress() {
  press.replaceChildren(
    h('div', { class: 'press-panel', role: 'dialog', 'aria-label': 'Downloads' },
      h('div', { class: 'press-head' }, h('h4', {}, 'THE PRESS'), h('span', { class: 'jp' }, '印刷所'), h('span', { class: 'sp' }), h('button', { class: 'mini', 'aria-label': 'Close', onclick: () => togglePress(false) }, icon('x'))),
      h('div', { class: 'press-now' },
        h('div', { class: 'fan' }, h('div', { class: 'fan-empty' }, 'pages appear here as they print')),
        h('div', { class: 'now-title' }, ''), h('div', { class: 'now-sub' }, h('span', { class: 'a' }), h('span', { class: 'b' })), h('div', { class: 'pbar' }, h('i'))),
      h('ol', { class: 'press-list' }),
      h('div', { class: 'press-foot' },
        h('button', { class: 'btn sm ghost', onclick: () => post('/api/tasks/clear') }, 'Clear finished'),
        h('span', { style: { flex: 1 } }),
        h('button', { class: 'btn sm ghost', onclick: () => post('/api/tasks/cancel-all') }, 'Cancel all'))),
    h('button', { class: 'press-pill', onclick: () => togglePress() },
      h('span', { class: 'ring' }, h('span', { html: '<svg viewBox="0 0 44 44"><circle class="bg" cx="22" cy="22" r="18"/><circle class="fg" cx="22" cy="22" r="18" stroke-dasharray="113.1" stroke-dashoffset="113.1"/></svg>' }), h('span', { class: 'mid' })),
      h('span', { class: 'pill-txt' }, h('b'), h('small'))));
}
function togglePress(v = !pressOpen) { pressOpen = v; press.classList.toggle('open', v); }
let pressRaf = 0;
function updatePress() { if (!pressRaf) pressRaf = requestAnimationFrame(() => { pressRaf = 0; renderPress(); }); }
function speed() {
  const s = S.speed, now = performance.now();
  while (s.length > 2 && now - s[0].t > 5000) s.shift();
  if (s.length < 2) return 0;
  return (s[s.length - 1].bytes - s[0].bytes) / ((s[s.length - 1].t - s[0].t) / 1000 || 1);
}
function renderPress() {
  const tasks = [...S.tasks.values()];
  press.hidden = !tasks.length;
  if (!tasks.length) { togglePress(false); return; }
  if (!press.firstChild) buildPress();
  const running = tasks.find((t) => t.status === 'running');
  const queued = tasks.filter((t) => t.status === 'queued');
  const done = tasks.filter((t) => t.status === 'done');
  const active = tasks.filter((t) => t.status === 'running' || t.status === 'queued');
  const totPages = active.reduce((a, t) => a + t.pages_total, 0) + done.reduce((a, t) => a + t.pages_total, 0);
  const donePages = active.reduce((a, t) => a + t.pages_done, 0) + done.reduce((a, t) => a + t.pages_total, 0);
  const frac = active.length ? (totPages ? donePages / totPages : 0) : 1;
  const sp = speed();
  const fg = $('.ring .fg', press);
  fg.style.strokeDashoffset = String(113.1 * (1 - frac));
  $('.ring', press).classList.toggle('spin', !!active.length && !running?.pages_done);
  $('.ring .mid', press).textContent = active.length ? `${Math.floor(frac * 100)}%` : '✓';
  $('.pill-txt b', press).textContent = running ? `${running.series} ${running.current || ''}`.trim() : active.length ? 'Waiting…' : `${done.length} file${done.length === 1 ? '' : 's'} bound`;
  $('.pill-txt small', press).textContent = running ? `${fmtBytes(sp)}/s · ${queued.length} queued` : active.length ? `${queued.length} queued` : 'tap to see them';

  const now = $('.press-now', press);
  if (running) {
    const p = running.pages_total ? running.pages_done / running.pages_total : 0;
    const left = running.pages_total - running.pages_done + queued.reduce((a, t) => a + t.pages_total, 0);
    const per = running.pages_done ? running.bytes / running.pages_done : 300e3;
    const eta = sp > 0 ? (left * per) / sp : 0;
    $('.now-title', now).textContent = running.name;
    $('.now-sub .a', now).textContent = `${running.current || '…'} · page ${running.pages_done}/${running.pages_total}`;
    $('.now-sub .b', now).textContent = sp ? `${fmtBytes(sp)}/s${eta ? ` · ~${eta > 90 ? Math.round(eta / 60) + 'm' : Math.round(eta) + 's'} left` : ''}` : '';
    $('.pbar i', now).style.setProperty('--p', p);
  } else {
    $('.now-title', now).textContent = active.length ? 'Warming up the press…' : 'All done.';
    $('.now-sub .a', now).textContent = active.length ? '' : `${done.length} bound · ${fmtBytes(done.reduce((a, t) => a + t.bytes, 0))}`;
    $('.now-sub .b', now).textContent = '';
    $('.pbar i', now).style.setProperty('--p', active.length ? 0 : 1);
  }

  const order = { running: 0, queued: 1, error: 2, done: 3, cancelled: 4 };
  const list = $('.press-list', press);
  list.replaceChildren(...tasks.slice().sort((a, b) => order[a.status] - order[b.status] || b.finished - a.finished).slice(0, 60).map((t) => {
    const st = t.status === 'running' ? `${t.current || 'starting'} · ${t.pages_done}/${t.pages_total}`
      : t.status === 'queued' ? `queued · ${t.pages_total} pages`
      : t.status === 'done' ? `✓ ${t.pages_total} page${t.pages_total === 1 ? '' : 's'} · ${fmtBytes(t.bytes)}`
      : t.status === 'error' ? t.error : 'cancelled';
    const acts = t.status === 'done'
      ? [h('button', { class: 'mini', title: 'Read', onclick: () => openReader(t.file, t.name) }, icon('read')), h('button', { class: 'mini', title: 'Show in Finder', onclick: () => post('/api/reveal', { path: t.file }) }, icon('folder'))]
      : (t.status === 'running' || t.status === 'queued') ? [h('button', { class: 'mini', title: 'Cancel', onclick: () => post(`/api/tasks/${t.id}/cancel`) }, icon('x'))] : [];
    return h('li', { class: `ptask ${t.status}` },
      t.cover ? h('img', { src: t.cover, alt: '' }) : h('div', { class: 'ph' }),
      h('div', { style: { 'min-width': 0 } }, h('div', { class: 'nm' }, shortName(t.name)), h('div', { class: 'st' }, st),
        t.status === 'running' ? h('div', { class: 'pbar' }, h('i', { style: { '--p': t.pages_total ? t.pages_done / t.pages_total : 0 } })) : null),
      h('div', { class: 'acts' }, acts));
  }));
}
function addFanPage(src) {
  const fan = $('.fan', press); if (!fan) return;
  fan.querySelector('.fan-empty')?.remove();
  const img = h('img', { class: 'fan-page', src, alt: '' });
  fanPages.push(img); fan.append(img);
  while (fanPages.length > 5) { const old = fanPages.shift(); old.style.opacity = '0'; setTimeout(() => old.remove(), 500); }
  fanPages.forEach((p, k) => p.style.setProperty('--k', k - (fanPages.length - 1) / 2 + 2));  // keep the fan centred
}
function stamp() {
  if (reduced) return;
  const host = pressOpen ? $('.press-panel', press) : null;
  const s = h('div', { class: 'stamp' }, '済', h('small', {}, 'BOUND'));
  if (host) { s.style.right = '24px'; s.style.top = '40px'; host.append(s); }
  else { const [x, y] = pressTarget(); Object.assign(s.style, { position: 'fixed', left: x - 60 + 'px', top: y - 160 + 'px', zIndex: 50 }); document.body.append(s); }
  setTimeout(() => { press.classList.add('shake'); setTimeout(() => press.classList.remove('shake'), 400); }, 250);
  setTimeout(() => s.remove(), 1700);
}

// ================================================================ live events from the server
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    if (ev.type === 'queued') { ev.tasks.forEach((t) => S.tasks.set(t.id, t)); updatePress(); }
    else if (ev.type === 'task') {
      const t = ev.task; S.tasks.set(t.id, t);
      if (t.status !== 'running' && t.volume) S.vprog.delete(t.volume);
      if (t.status === 'done') {
        stamp();
        const v = S.manga?.id === t.manga_id && t.volume && S.volBy.get(t.volume);
        if (v) v.downloaded = true;
      } else if (t.status === 'error') toast(`${t.name}: ${t.error}`, 'error');
      if (S.manga?.id === t.manga_id) paint();
      updatePress();
    } else if (ev.type === 'page') {
      const t = S.tasks.get(ev.task);
      if (t) { t.pages_done = ev.done; t.pages_total = ev.total; t.bytes = ev.bytes; t.current = ev.label; t.status = 'running'; }
      const total = [...S.tasks.values()].reduce((a, x) => a + (x.bytes || 0), 0);
      S.speed.push({ t: performance.now(), bytes: total });
      if (t?.volume && S.manga?.id === t.manga_id) {
        S.vprog.set(t.volume, t.pages_total ? t.pages_done / t.pages_total : 0);
        paintVolProgress(t.volume);
      }
      addFanPage(ev.img);
      updatePress();
    } else if (ev.type === 'cleared') {
      for (const [id, t] of S.tasks) if (!['running', 'queued'].includes(t.status)) S.tasks.delete(id);
      fanPages.splice(0).forEach((p) => p.remove());
      updatePress();
    } else if (ev.type === 'library') {
      if (location.hash.startsWith('#/library')) refreshLibrary?.();
    }
  };
}

// ================================================================ library
let refreshLibrary = null;
function bookEl(s, i, onclick) {
  const spineTxt = h('span', {}, s.title);
  const b = h('button', { class: 'book', style: { '--i': i }, onclick },
    h('div', { class: 'book-3d' },
      h('div', { class: 'book-spine' }, spineTxt),
      h('div', { class: 'book-front' }, s.cover ? h('img', { src: s.cover, alt: '', loading: 'lazy' }) : h('div', { class: 'noimg' }, '単')),
      h('div', { class: 'book-pages' }),
      h('div', { class: 'book-shadow' })),
    h('div', { class: 'book-title' }, s.title),
    h('div', { class: 'book-meta' }, `${s.files.length} file${s.files.length === 1 ? '' : 's'} · ${fmtBytes(s.size)}`));
  if (s.cover) coverPalette(s.cover).then((p) => p && b.style.setProperty('--spine', p.spine));
  return b;
}

function viewLibrary(openDir) {
  setAccent(null); setBackdrop(null); S.manga = null; updateBindbar();
  document.title = 'Shelf · Tankōbon';
  const stats = h('div', { class: 'lib-stats' });
  const books = h('div', { class: 'books' }, Array.from({ length: 6 }, () => h('div', {}, h('div', { class: 'skel', style: { 'aspect-ratio': '5/7' } }))));
  const el = h('div', { class: 'view library' },
    h('header', { class: 'page-head' },
      h('h1', { class: 'page-title' }, h('span', { class: 'jp' }, '本棚'), 'Your shelf'),
      h('span', { class: 'sp' }),
      h('div', { class: 'lib-actions' },
        h('button', { class: 'btn ghost', onclick: () => post('/api/reveal', { path: '' }) }, icon('folder'), 'Open folder'))),
    stats, books);
  let first = true;
  refreshLibrary = async () => {
    try {
      const { series, out_dir } = await get('/api/library');
      S.outDir = out_dir || S.outDir;
      const files = series.reduce((a, s) => a + s.files.length, 0), size = series.reduce((a, s) => a + s.size, 0);
      stats.replaceChildren(...[[series.length, 'series'], [files, 'files'], [fmtBytes(size), 'on disk']].map(([v, l], i) => h('div', { class: 'stat', style: { '--i': i } }, h('b', {}, v), h('small', {}, l))));
      if (!series.length) {
        books.replaceChildren(h('div', { class: 'empty-note', style: { 'grid-column': '1/-1' } }, h('span', { class: 'seal big' }, '空'), h('div', {}, h('b', {}, 'Nothing bound yet'), 'Find a manga, pick some chapters and hit Bind. Your .cbz files land in ', h('code', {}, S.outDir), '.', h('div', { style: { 'margin-top': '14px' } }, h('a', { class: 'btn solid sm', href: '#/' }, 'Find something', icon('arrow'))))));
        return;
      }
      books.replaceChildren(...series.map((s, i) => bookEl(s, i, () => openDrawer(s))));
      if (first && openDir) { const s = series.find((x) => x.dir === openDir); if (s) openDrawer(s); }
      first = false;
    } catch (e) { books.replaceChildren(h('div', { class: 'empty-note' }, e.message)); }
  };
  refreshLibrary();
  return el;
}

function closeDrawer() { $$('.drawer, .drawer-back').forEach((x) => x.remove()); }
function openDrawer(s) {
  closeDrawer();
  const back = h('div', { class: 'drawer-back', onclick: closeDrawer });
  const strip = shortName;
  const dr = h('aside', { class: 'drawer', role: 'dialog', 'aria-label': s.title },
    h('div', { class: 'drawer-hero', style: { '--bg': s.cover ? `url("${s.cover}")` : 'none' } },
      s.cover ? h('img', { src: s.cover, alt: '' }) : h('div', {}),
      h('div', {}, h('h2', {}, s.title), h('div', { class: 'book-meta' }, `${s.files.length} files · ${fmtBytes(s.size)}${s.writer ? ' · ' + s.writer : ''}`),
        h('div', { class: 'mactions', style: { 'margin-top': '16px' } },
          s.manga_id ? h('a', { class: 'btn sm solid', href: `#/manga/${s.manga_id}` }, 'More chapters', icon('arrow')) : null,
          h('button', { class: 'btn sm', onclick: () => post('/api/reveal', { path: s.dir }) }, icon('folder'), 'Folder'))),
      h('button', { class: 'mini x', 'aria-label': 'Close', onclick: closeDrawer }, icon('x'))),
    h('div', { class: 'drawer-body' }, s.files.map((f) => h('div', { class: 'frow' },
      h('img', { class: 'fthumb', src: `/api/page?p=${enc(f.path)}&n=0`, alt: '', loading: 'lazy' }),
      h('div', { style: { 'min-width': 0 } }, h('div', { class: 'nm' }, strip(f.name)), h('div', { class: 'mt' }, [f.pages ? `${f.pages} page${f.pages === 1 ? '' : 's'}` : null, fmtBytes(f.size), new Date(f.mtime * 1000).toLocaleDateString()].filter(Boolean).join(' · '))),
      h('div', { class: 'acts' },
        h('button', { class: 'mini', title: 'Read', onclick: () => openReader(f.path, `${s.title} — ${strip(f.name)}`) }, icon('read')),
        h('a', { class: 'mini', title: 'Download .cbz', href: `/api/file?p=${enc(f.path)}`, download: f.name }, icon('download')),
        h('button', { class: 'mini', title: 'Show in Finder', onclick: () => post('/api/reveal', { path: f.path }) }, icon('folder')))))));
  document.body.append(back, dr);
}

// ================================================================ reader
const R = { path: '', n: 0, i: 0, mode: store('readerMode') || 'rtl', title: '' };
const readerEl = $('#reader');
let idleTimer;
async function openReader(path, title) {
  try {
    const { pages } = await get(`/api/read?p=${enc(path)}`);
    Object.assign(R, { path, n: pages, i: 0, title: title || path.split('/').pop() });
    readerEl.hidden = false;
    document.body.style.overflow = 'hidden';
    renderReader();
  } catch (e) { toast(e.message, 'error'); }
}
function closeReader() { readerEl.hidden = true; readerEl.replaceChildren(); document.body.style.overflow = ''; }
const pageUrl = (i) => `/api/page?p=${enc(R.path)}&n=${i}`;
function renderReader() {
  const modeBtn = (m, label, ic) => h('button', { class: `btn sm ${R.mode === m ? 'solid' : 'ghost'}`, onclick: () => { R.mode = m; store('readerMode', m); renderReader(); } }, icon(ic), label);
  const top = h('div', { class: 'rd-top' },
    h('button', { class: 'mini', 'aria-label': 'Close reader', onclick: closeReader }, icon('x')),
    h('div', { class: 't' }, R.title), h('span', { class: 'sp' }),
    modeBtn('rtl', 'Manga ←', 'read'), modeBtn('ltr', 'Comic →', 'read'), modeBtn('scroll', 'Scroll', 'scroll'));
  if (R.mode === 'scroll') {
    const sc = h('div', { class: 'rd-scroll' }, Array.from({ length: R.n }, (_, i) => h('img', { src: pageUrl(i), loading: 'lazy', alt: `page ${i + 1}` })));
    readerEl.replaceChildren(top, sc);
    return;
  }
  const stage = h('div', { class: 'rd-stage' });
  const range = h('input', { type: 'range', min: 1, max: R.n, value: R.i + 1, class: R.mode === 'rtl' ? 'rtl' : '', oninput: (e) => goPage(+e.target.value - 1) });
  const pg = h('span', { class: 'pg' });
  const bot = h('div', { class: 'rd-bot' }, range, pg);
  stage.addEventListener('click', (e) => {
    const x = e.clientX / innerWidth;
    if (x < .35) goPage(R.i + (R.mode === 'rtl' ? 1 : -1));
    else if (x > .65) goPage(R.i + (R.mode === 'rtl' ? -1 : 1));
    else readerEl.classList.toggle('idle');
  });
  readerEl.replaceChildren(top, stage, bot);
  R.stage = stage; R.range = range; R.pg = pg;
  goPage(R.i, 0);
}
function goPage(i, dir) {
  if (i < 0 || i >= R.n) { if (i >= R.n) toast('End of file'); return; }
  const d = dir ?? Math.sign(i - R.i);
  R.i = i;
  const img = h('img', { src: pageUrl(i), alt: `page ${i + 1}`, style: { '--dir': R.mode === 'rtl' ? -d : d } });
  R.stage.replaceChildren(img);
  R.range.value = i + 1;
  R.pg.textContent = `${i + 1} / ${R.n}`;
  [1, 2].forEach((k) => { if (i + k < R.n) new Image().src = pageUrl(i + k); });
}
addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && readerEl.hidden && $('.drawer')) return closeDrawer();
  if (readerEl.hidden) return;
  if (e.key === 'Escape') return closeReader();
  if (R.mode === 'scroll') return;
  const fwd = R.mode === 'rtl' ? 'ArrowLeft' : 'ArrowRight', back = R.mode === 'rtl' ? 'ArrowRight' : 'ArrowLeft';
  if (e.key === fwd || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); goPage(R.i + 1); }
  if (e.key === back || e.key === 'PageUp') { e.preventDefault(); goPage(R.i - 1); }
});
readerEl.addEventListener('pointermove', () => { readerEl.classList.remove('idle'); clearTimeout(idleTimer); idleTimer = setTimeout(() => readerEl.classList.add('idle'), 2200); });

// ================================================================ modals
function modal(title, sub, body, { wide } = {}) {
  const close = () => { back.remove(); removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const back = h('div', { class: 'modal-back', onclick: (e) => { if (e.target === back) close(); } },
    h('div', { class: `modal ${wide ? 'wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('div', { class: 'modal-head' }, h('div', {}, h('h3', {}, title), sub ? h('p', {}, sub) : null), h('button', { class: 'mini x', 'aria-label': 'Close', onclick: () => close() }, icon('x'))),
      h('div', { class: 'modal-body' }, body)));
  addEventListener('keydown', onKey);
  $('#modal-root').append(back);
  return { close, el: back };
}

function openLogin() {
  const f = (name, label, type = 'text', extra = {}) => h('label', { class: `in ${extra.full ? 'full' : ''}` }, h('span', {}, label), h('input', { name, type, required: true, autocomplete: extra.ac || 'off', placeholder: extra.ph || '', spellcheck: 'false' }));
  const err = h('div', { class: 'form-err' });
  const submit = h('button', { class: 'btn solid', type: 'submit' }, 'Connect', icon('arrow'));
  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    submit.disabled = true; err.textContent = '';
    try {
      const r = await post('/api/login', data);
      S.me = { logged_in: true, username: r.username };
      renderAccount(); m.close();
      toast(`Connected as ${r.username}`);
      if (!location.hash || location.hash === '#/' || location.hash.startsWith('#/?')) route();
    } catch (x) { err.textContent = x.message; }
    finally { submit.disabled = false; }
  } },
    h('ol', { class: 'steps' },
      h('li', {}, h('span', {}, 'Open ', h('a', { href: 'https://mangadex.org/settings', target: '_blank', rel: 'noopener' }, 'mangadex.org/settings ↗'), ' → API Clients → create a ', h('b', {}, 'personal client'), '.')),
      h('li', {}, h('span', {}, 'Wait until it says ', h('b', {}, 'approved'), ' (sometimes instant, sometimes a staff review), then hit ', h('b', {}, 'Get Secret'), '.')),
      h('li', {}, h('span', {}, 'Paste the client ID (', h('code', {}, 'personal-client-…'), ') and secret below with your MangaDex login.'))),
    h('div', { class: 'form-grid' },
      f('username', 'Username', 'text', { ac: 'username' }),
      f('password', 'Password', 'password', { ac: 'current-password' }),
      f('client_id', 'Client ID', 'text', { ph: 'personal-client-…', full: true }),
      f('client_secret', 'Client secret', 'password', { full: true, ac: 'off' })),
    h('p', { class: 'note' }, icon('lock'), h('span', {}, 'Your password goes straight to auth.mangadex.org once and is never saved. Tankōbon keeps only the client ID/secret and a refresh token in ', h('code', {}, '~/.config/mangadex-dl/auth.json'), ' (readable by you only).')),
    err,
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => m.close() }, 'Cancel'), submit));
  const m = modal('Connect MangaDex', 'Unlocks your follows, reading lists and new-chapter feed.', form);
  setTimeout(() => form.querySelector('input').focus(), 60);
}

function renderAccount() {
  const b = $('#accountBtn');
  if (S.me.logged_in) {
    b.className = 'account-btn';
    b.replaceChildren(h('span', { class: 'av' }, (S.me.username || '?')[0].toUpperCase()), S.me.username);
    b.onclick = (e) => accountMenu(e.currentTarget);
  } else {
    b.className = 'account-btn guest';
    b.replaceChildren(h('span', { class: 'long' }, 'Connect MangaDex'), h('span', { class: 'short' }, 'Log in'));
    b.onclick = openLogin;
  }
}
function accountMenu(anchor) {
  $('.menu')?.remove();
  const r = anchor.getBoundingClientRect();
  const close = () => { menu.remove(); removeEventListener('pointerdown', away, true); };
  const away = (e) => { if (!menu.contains(e.target)) close(); };
  const menu = h('div', { class: 'menu', style: { top: r.bottom + 10 + 'px', right: innerWidth - r.right + 'px' } },
    h('div', { class: 'who' }, h('b', {}, S.me.username), h('small', {}, 'MangaDex account')),
    h('a', { href: `https://mangadex.org/user/me`, target: '_blank', rel: 'noopener', onclick: close }, icon('ext'), 'Profile on MangaDex'),
    h('button', { onclick: async () => { close(); await post('/api/logout'); S.me = { logged_in: false, username: '' }; renderAccount(); toast('Logged out'); route(); } }, icon('logout'), 'Log out'));
  document.body.append(menu);
  setTimeout(() => addEventListener('pointerdown', away, true));
}

// ================================================================ global input: paste anywhere, drop a link, "/" to search
addEventListener('paste', (e) => {
  if (e.target.closest?.('input, textarea')) return;
  const t = e.clipboardData?.getData('text') || '';
  if (looksLikeLink(t)) { e.preventDefault(); toast('Opening pasted link…'); openTarget(t); }
});
let dragDepth = 0;
addEventListener('dragenter', (e) => { if ([...e.dataTransfer.types].some((t) => t.startsWith('text/'))) { dragDepth++; $('#dropzone').classList.add('on'); } });
addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('#dropzone').classList.remove('on'); } });
addEventListener('dragover', (e) => e.preventDefault());
addEventListener('drop', (e) => {
  e.preventDefault(); dragDepth = 0; $('#dropzone').classList.remove('on');
  const t = e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain');
  if (t) openTarget(t.split('\n')[0]);
});
addEventListener('keydown', (e) => {
  if (e.key === '/' && !e.target.closest?.('input, textarea, select') && readerEl.hidden) {
    e.preventDefault();
    const q = $('#q');
    if (q) q.focus(); else { nav('#/'); setTimeout(() => $('#q')?.focus(), 400); }
  }
});

// ================================================================ boot
(async function boot() {
  screentone();
  try {
    const st = await get('/api/state');
    S.me = { logged_in: st.logged_in, username: st.username };
    S.outDir = st.out_dir;
    st.tasks.forEach((t) => S.tasks.set(t.id, t));
  } catch {}
  renderAccount(); updatePress();
  connectEvents();
  addEventListener('hashchange', route);
  route();
})();
