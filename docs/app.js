/* ============================================================
   PhD Sky v3 — Feed + Accounts  ·  app logic (real data)
   Twitter/Bluesky-style feed over the live phd_positions data.
   Branch A: redesign only. Auth/subscriptions/follows surfaces are
   present but routed to a "coming soon" nudge until later branches.
   ============================================================ */
'use strict';

/* ───────────────────────── CONFIG / DATA LAYER ───────────────────────── */
// Mock mode: add ?mock to the URL to load from mock_data.json instead of Supabase
const USE_MOCK = new URLSearchParams(window.location.search).has('mock');

const SUPABASE_URL = 'https://qenpxgztlptegosdhhhi.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_';
const supabaseClient = USE_MOCK ? null : window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Aggregator handles — inlined so it works on file:// and GitHub Pages alike.
// Keep in sync with docs/aggregators.json.
const aggregatorHandles = new Set([
    "tenuretracker.bsky.social", "epsteinweb.bsky.social", "jobboardsearch.com",
    "agristok.bsky.social", "scholarshipunion.bsky.social", "higherjobz.bsky.social",
    "evoldir.bsky.social", "jobrxiv.org", "cosmossn.bsky.social", "vacancyedu.bsky.social",
    "sciencehr.bsky.social", "finland.activitypub.awakari.com.ap.brid.gy",
    "functionalprogramming.activitypub.awakari.com.ap.brid.gy",
    "2rzikkbou3ntafnir2qmmse0gwz.activitypub.awakari.com.ap.brid.gy",
    "darkmatter.activitypub.awakari.com.ap.brid.gy", "academiceurope.bsky.social",
    "iddjobs.org", "epijobs.bsky.social", "rss.dfaria.eu", "inomics.bsky.social",
    "greenjobs.de", "bioinfojobs.bsky.social", "atmchemaerojobs.bsky.social",
    "gulfcareerhunt.bsky.social", "diversifytech.com",
]);
function isAggregator(handle) { return !!handle && aggregatorHandles.has(handle); }

// Per-discipline badge colors (flat, no gradients)
const DISCIPLINE_COLORS = {
    'Biology': '#16a34a', 'Ecology': '#15803d', 'Computer Science': '#6d28d9',
    'Physics': '#0284c7', 'Chemistry & Materials Science': '#0891b2', 'Medicine': '#dc2626',
    'Mathematics': '#7c3aed', 'Economics': '#b45309', 'Sociology & Political Science': '#0369a1',
    'Engineering': '#c2410c', 'Environmental Sciences': '#15803d', 'Psychology': '#be185d',
    'Neuroscience': '#7c3aed', 'History': '#92400e', 'Arts & Humanities': '#a21caf',
    'General call': '#475569',
};
function getDisciplineColor(d) { return DISCIPLINE_COLORS[d] || '#3b82f6'; }

// Short display labels for compact badges/chips
const DISCIPLINE_SHORT = {
    'Computer Science': 'CS', 'Chemistry & Materials Science': 'Chemistry',
    'Sociology & Political Science': 'Sociology', 'Arts & Humanities': 'Arts',
    'Mathematics': 'Math', 'General call': 'General',
};
function discShort(d) { return DISCIPLINE_SHORT[d] || d; }

// Area filter chips (full discipline name + short label)
const AREA_CHIPS = [
    'Biology', 'Computer Science', 'Physics', 'Medicine', 'Ecology',
    'Mathematics', 'Chemistry & Materials Science', 'Psychology',
    'Economics', 'Sociology & Political Science', 'Arts & Humanities',
];
// Level filter chips: [value, label]
const LEVEL_CHIPS = [
    ['PhD Student', 'PhD'], ['Postdoc', 'Postdoc'],
    ['Master Student', 'Master'], ['Research Assistant', 'RA'],
];

const COUNTRY_NORMALIZE = { 'Czechia': 'Czech Republic', 'Europe': 'Unknown' };
function normalizeCountry(c) { return c ? (COUNTRY_NORMALIZE[c] || c) : c; }

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
}

// Mirrors extract_slug() in scripts/generate_seo_pages.py — keep in sync.
function extractSlug(uri) {
    if (!uri) return null;
    const tail = uri.split('/').pop();
    const slug = tail.replace(/[^a-zA-Z0-9_-]/g, '');
    return slug || null;
}

function safeUrl(u) {
    if (!u) return null;
    try { const url = new URL(u); return (url.protocol === 'https:' || url.protocol === 'http:') ? u : null; }
    catch { return null; }
}

/* ───────────────────────── STATE ───────────────────────── */
const state = {
    all: [],                 // all positions (canonical, verified)
    duplicateMap: {},        // canonical uri -> [{uri, url, user_handle, created_at}]
    total: 0,                // total open positions
    view: 'feed',            // 'feed' | 'subs'
    stream: 'all',
    tab: 'latest',
    search: '',
    hideAggr: false,
    filters: { level: new Set(), country: new Set(), area: new Set() },
    threadOpen: new Set(),
};

// Infinite scroll
const BATCH_SIZE = 30;
let feedList = [];           // current filtered list
let renderedCount = 0;
let lastDayLabel = null;
let scrollObserver = null;

/* ───────────────────────── DATA FETCHING ───────────────────────── */
async function fetchMockPositions() {
    const r = await fetch('mock_data.json');
    if (!r.ok) throw new Error(`mock data ${r.status}`);
    return r.json();
}

async function fetchStaticSnapshot() {
    try {
        const r = await fetch('positions.json', { cache: 'default' });
        if (!r.ok) return null;
        const data = await r.json();
        if (!data || !Array.isArray(data.positions)) return null;
        const positions = data.positions.map(p => ({ ...p, country: normalizeCountry(p.country) }));
        const dupMap = buildDuplicateMap(data.duplicates || []);
        return { positions, duplicates: dupMap, total: data.total || positions.length };
    } catch (e) { console.warn('snapshot fetch failed', e); return null; }
}

function buildDuplicateMap(rows) {
    const map = {};
    for (const row of rows) {
        const key = row.duplicate_of;
        if (!key) continue;
        (map[key] = map[key] || []).push(row);
    }
    for (const k of Object.keys(map)) map[k].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    return map;
}

async function fetchSupabasePositions() {
    const PAGE = 1000; let all = []; let from = 0;
    while (true) {
        const { data, error } = await supabaseClient
            .from('phd_positions')
            .select('uri, created_at, disciplines, country, position_type, user_handle, message, url, indexed_at')
            .eq('is_verified_job', true)
            .is('duplicate_of', null)
            .gte('indexed_at', '2026-01-27')
            .order('created_at', { ascending: false })
            .range(from, from + PAGE - 1);
        if (error) throw error;
        all = all.concat(data.map(p => ({ ...p, country: normalizeCountry(p.country) })));
        if (data.length < PAGE) break;
        from += PAGE;
    }
    return all;
}

async function fetchDuplicates() {
    if (USE_MOCK) return {};
    const PAGE = 1000; let all = []; let from = 0;
    while (true) {
        const { data, error } = await supabaseClient
            .from('phd_positions')
            .select('uri, url, user_handle, created_at, duplicate_of')
            .not('duplicate_of', 'is', null)
            .gte('indexed_at', '2026-01-27')
            .range(from, from + PAGE - 1);
        if (error) { console.error('dup fetch failed', error); return {}; }
        all = all.concat(data || []);
        if ((data || []).length < PAGE) break;
        from += PAGE;
    }
    return buildDuplicateMap(all);
}

// Three-tier loader: static snapshot → live Supabase. Returns {positions, duplicates, total}.
async function loadFullData() {
    if (USE_MOCK) {
        const positions = await fetchMockPositions();
        return { positions, duplicates: {}, total: positions.length };
    }
    const snap = await fetchStaticSnapshot();
    if (snap) return snap;
    console.warn('falling back to live Supabase query');
    const [positions, duplicates] = await Promise.all([fetchSupabasePositions(), fetchDuplicates()]);
    return { positions, duplicates, total: positions.length };
}

function loadStaticData() {
    const el = document.getElementById('static-positions');
    if (!el) return null;
    try {
        const data = JSON.parse(el.textContent);
        if (data && Array.isArray(data.positions) && data.positions.length > 0) {
            const positions = data.positions.map(p => ({ ...p, country: normalizeCountry(p.country) }));
            return { positions, total: data.total || positions.length };
        }
    } catch (e) { console.warn('static parse failed', e); }
    return null;
}

/* ───────────────────────── TIME HELPERS ───────────────────────── */
function relTime(iso) {
    if (!iso) return '';
    const then = new Date(iso); const now = new Date();
    const s = Math.max(0, (now - then) / 1000);
    if (s < 60) return 'now';
    if (s < 3600) return Math.floor(s / 60) + 'm';
    if (s < 86400) return Math.floor(s / 3600) + 'h';
    if (s < 86400 * 7) return Math.floor(s / 86400) + 'd';
    return then.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function dayLabel(iso) {
    if (!iso) return 'Earlier';
    const d = new Date(iso); const now = new Date();
    const startOf = x => new Date(x.getFullYear(), x.getMonth(), x.getDate());
    const diffDays = Math.round((startOf(now) - startOf(d)) / 86400000);
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/* ───────────────────────── FILTERING ───────────────────────── */
function visiblePositions() {
    const f = state.filters;
    const q = state.search.trim().toLowerCase();
    return state.all.filter(p => {
        if (state.hideAggr && isAggregator(p.user_handle)) return false;
        const types = p.position_type || [];
        const discs = p.disciplines || [];
        if (f.level.size && !types.some(t => f.level.has(t))) return false;
        if (f.country.size && !f.country.has(p.country)) return false;
        if (f.area.size && !discs.some(d => f.area.has(d))) return false;
        if (q) {
            const hay = [p.message, p.user_handle, p.country, discs.join(' '), types.join(' ')]
                .join(' ').toLowerCase();
            if (!hay.includes(q)) return false;
        }
        return true;
    });
}

/* ───────────────────────── FEED RENDER ───────────────────────── */
const MSG_LIMIT = 280;

function postHTML(p) {
    const handle = p.user_handle || 'unknown';
    const initial = handle[0] ? handle[0].toUpperCase() : '?';
    const aggr = isAggregator(handle);
    const discBadges = (p.disciplines || []).map(d =>
        `<span class="b" style="background:${getDisciplineColor(d)}">${escapeHtml(discShort(d))}</span>`).join('');
    const typeBadges = (p.position_type || []).map(t => `<span class="b b-pos">${escapeHtml(t)}</span>`).join('');
    const countryBadge = (p.country && p.country !== 'Unknown') ? `<span class="b b-country">${escapeHtml(p.country)}</span>` : '';

    const msg = p.message || '';
    const truncated = msg.length > MSG_LIMIT;
    const bodyText = truncated ? msg.slice(0, MSG_LIMIT).trimEnd() + '…' : msg;
    const moreLink = truncated ? '<span class="more-link">show more</span>' : '';

    const reposts = (p.uri && state.duplicateMap[p.uri]) || [];
    const rep = reposts.length;
    const tOpen = state.threadOpen.has(p.uri);
    const profileUrl = `https://bsky.app/profile/${encodeURIComponent(handle)}`;
    const postUrl = safeUrl(p.url) || profileUrl;

    let threadHTML = '';
    if (rep > 0) {
        threadHTML = `<div class="p-thread ${tOpen ? 'open' : ''}" data-thread="${escapeHtml(p.uri)}">
          <button class="p-thread-toggle" data-toggle="${escapeHtml(p.uri)}"><span class="arr">▸</span> ${rep} earlier repost${rep > 1 ? 's' : ''}</button>
          <div class="p-thread-list">
            ${reposts.map(r => {
                const rl = safeUrl(r.url);
                const h = `@${escapeHtml(r.user_handle || 'unknown')}`;
                const hh = rl ? `<a class="h" href="${escapeHtml(rl)}" target="_blank" rel="noopener">${h}</a>` : `<span class="h">${h}</span>`;
                return `<div class="p-thread-item"><span class="dot"></span>${hh}<span class="t">${escapeHtml(relTime(r.created_at))}</span></div>`;
            }).join('')}
          </div>
        </div>`;
    }

    return `<article class="post" data-id="${escapeHtml(p.uri)}">
      <div class="p-avatar ${aggr ? 'aggr' : ''}">${escapeHtml(initial)}</div>
      <div class="p-head">
        <a class="p-handle" href="${escapeHtml(profileUrl)}" target="_blank" rel="noopener" data-stop>@${escapeHtml(handle)}</a>
        ${aggr ? '<span class="p-aggr-tag">aggr</span>' : ''}
        <span class="p-time">${escapeHtml(relTime(p.created_at))}</span>
        <button class="p-follow" data-follow="${escapeHtml(handle)}" title="Follow @${escapeHtml(handle)}">+ follow</button>
      </div>
      <div class="p-meta-strip">${discBadges}${typeBadges}${countryBadge}</div>
      <div class="p-body">${escapeHtml(bodyText)}${moreLink}</div>
      ${threadHTML}
      <div class="p-actions">
        <a class="p-act" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener" data-stop style="margin-left:auto;color:var(--primary)">view on Bluesky →</a>
      </div>
    </article>`;
}

function emptyStateHTML() {
    if (state.search || state.filters.level.size || state.filters.country.size || state.filters.area.size || state.hideAggr) {
        return `<div class="feed-empty"><div class="ee-mark">—</div><div class="ee-t">No positions match these filters</div><div class="ee-d">Try removing a filter chip on the left or clearing your search.</div><button class="btn-primary" id="empty-clear">Clear filters</button></div>`;
    }
    return `<div class="feed-empty"><div class="ee-mark">—</div><div class="ee-t">No positions loaded yet</div><div class="ee-d">Hang tight — fetching the latest positions.</div></div>`;
}

function renderFeedReset() {
    feedList = visiblePositions();
    renderedCount = 0;
    lastDayLabel = null;
    const stream = $('#feed-stream');
    if (!feedList.length) { stream.innerHTML = emptyStateHTML(); updateCounts(); return; }
    stream.innerHTML = '';
    renderNextBatch();
    updateCounts();
}

function renderNextBatch() {
    const stream = $('#feed-stream');
    const slice = feedList.slice(renderedCount, renderedCount + BATCH_SIZE);
    let html = '';
    for (const p of slice) {
        const dl = dayLabel(p.created_at);
        if (dl !== lastDayLabel) {
            const ct = feedList.filter(x => dayLabel(x.created_at) === dl).length;
            html += `<div class="day-sep"><span class="lbl">${escapeHtml(dl)}</span><span class="ct">${ct} position${ct > 1 ? 's' : ''}</span></div>`;
            lastDayLabel = dl;
        }
        html += postHTML(p);
    }
    stream.insertAdjacentHTML('beforeend', html);
    renderedCount += slice.length;
    const loader = $('#loader');
    loader.classList.toggle('hidden', renderedCount >= feedList.length);
}

function updateCounts() {
    const total = state.total || state.all.length;
    const ctAll = $('#ct-all'); if (ctAll) ctAll.textContent = total.toLocaleString();
    const tabCt = $('#tab-latest-ct'); if (tabCt) tabCt.textContent = feedList.length.toLocaleString();
}

/* ───────────────────────── INFINITE SCROLL ───────────────────────── */
function setupInfiniteScroll() {
    if (scrollObserver) scrollObserver.disconnect();
    scrollObserver = new IntersectionObserver(entries => {
        for (const e of entries) {
            if (e.isIntersecting && renderedCount < feedList.length) renderNextBatch();
        }
    }, { rootMargin: '600px' });
    scrollObserver.observe($('#loader'));
}

/* ───────────────────────── FILTER CHIPS ───────────────────────── */
function renderFilterChips() {
    // Level
    $('#chips-level').innerHTML = LEVEL_CHIPS.map(([val, lab]) =>
        `<span class="chip" data-level="${escapeHtml(val)}">${escapeHtml(lab)}</span>`).join('');
    // Area
    $('#chips-area').innerHTML = AREA_CHIPS.map(d =>
        `<span class="chip" data-area="${escapeHtml(d)}">${escapeHtml(discShort(d))}</span>`).join('');
    // Country — top 8 by frequency from loaded data
    const counts = {};
    for (const p of state.all) {
        if (p.country && p.country !== 'Unknown') counts[p.country] = (counts[p.country] || 0) + 1;
    }
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8).map(e => e[0]);
    $('#chips-country').innerHTML = top.map(c =>
        `<span class="chip" data-country="${escapeHtml(c)}">${escapeHtml(c)}</span>`).join('');

    bindChips();
}

function bindChips() {
    $$('.chip[data-level]').forEach(c => c.onclick = () => toggleChip(c, 'level', c.dataset.level));
    $$('.chip[data-country]').forEach(c => c.onclick = () => toggleChip(c, 'country', c.dataset.country));
    $$('.chip[data-area]').forEach(c => c.onclick = () => {
        const on = c.classList.toggle('on');
        if (on) { c.style.background = getDisciplineColor(c.dataset.area); c.style.borderColor = getDisciplineColor(c.dataset.area); c.style.color = '#fff'; state.filters.area.add(c.dataset.area); }
        else { c.style.background = ''; c.style.borderColor = ''; c.style.color = ''; state.filters.area.delete(c.dataset.area); }
        renderFeedReset();
    });
}

function toggleChip(el, kind, val) {
    const on = el.classList.toggle('on');
    if (on) state.filters[kind].add(val); else state.filters[kind].delete(val);
    renderFeedReset();
}

function clearFilters() {
    state.filters.level.clear(); state.filters.country.clear(); state.filters.area.clear();
    state.hideAggr = false; state.search = '';
    $('#cmd-input').value = '';
    $('#chip-hideaggr').classList.remove('on');
    $$('.chip.on').forEach(c => { c.classList.remove('on'); c.style.background = ''; c.style.borderColor = ''; c.style.color = ''; });
    renderFeedReset();
}

/* ───────────────────────── ACTIVITY RAIL ───────────────────────── */
function renderActivity() {
    const today = state.all.filter(p => dayLabel(p.created_at) === 'Today').length;
    const total = state.total || state.all.length;
    $('#activity-today').innerHTML =
        `<div>· <strong style="color:var(--fg)">+${today}</strong> new position${today === 1 ? '' : 's'} today</div>
         <div>· <strong style="color:var(--fg)">${total.toLocaleString()}</strong> open positions</div>`;

    // Top disciplines
    const counts = {};
    for (const p of state.all) for (const d of (p.disciplines || [])) counts[d] = (counts[d] || 0) + 1;
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const max = top.length ? top[0][1] : 1;
    $('#activity-trends').innerHTML = top.map(([d, n], i) => `
      <div class="trend-row" data-trend-area="${escapeHtml(d)}">
        <span class="trend-rank">${i + 1}</span>
        <span class="trend-name">${escapeHtml(discShort(d))}</span>
        <span class="trend-bar"><span class="trend-fill" style="width:${Math.round(n / max * 100)}%;background:${getDisciplineColor(d)}"></span></span>
        <span class="trend-ct">${n}</span>
      </div>`).join('');
}

/* ───────────────────────── POST FLYOUT ───────────────────────── */
function openFlyout(uri) {
    const p = state.all.find(x => x.uri === uri); if (!p) return;
    const handle = p.user_handle || 'unknown';
    const aggr = isAggregator(handle);
    const meta = [
        ...(p.disciplines || []).map(d => `<span class="b" style="background:${getDisciplineColor(d)}">${escapeHtml(discShort(d))}</span>`),
        ...(p.position_type || []).map(t => `<span class="b b-pos">${escapeHtml(t)}</span>`),
        (p.country && p.country !== 'Unknown') ? `<span class="b b-country">${escapeHtml(p.country)}</span>` : '',
    ].join('');
    const reposts = (state.duplicateMap[uri] || []);
    const profileUrl = `https://bsky.app/profile/${encodeURIComponent(handle)}`;
    const postUrl = safeUrl(p.url) || profileUrl;
    const date = p.created_at ? new Date(p.created_at).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '';

    $('#flyout-body').innerHTML = `
      <div class="flyout-author">
        <div class="p-avatar ${aggr ? 'aggr' : ''}" style="position:relative;top:0;left:0;width:40px;height:40px">${escapeHtml(handle[0] ? handle[0].toUpperCase() : '?')}</div>
        <div style="display:flex;flex-direction:column;gap:2px">
          <a href="${escapeHtml(profileUrl)}" target="_blank" rel="noopener" style="font-family:var(--font-mono);font-size:14px;color:var(--fg);font-weight:600">@${escapeHtml(handle)}</a>
          <div style="font-family:var(--font-mono);font-size:11px;color:var(--fg-subtle)">${aggr ? 'aggregator · ' : ''}${escapeHtml(date)}</div>
        </div>
      </div>
      <div class="p-meta-strip">${meta}</div>
      <div class="flyout-msg">${escapeHtml(p.message || '')}</div>
      ${reposts.length ? `<div class="flyout-section">
        <div class="flyout-section-title">Earlier reposts · ${reposts.length}</div>
        ${reposts.map(r => {
            const rl = safeUrl(r.url);
            const h = `@${escapeHtml(r.user_handle || 'unknown')}`;
            const hh = rl ? `<a class="h" href="${escapeHtml(rl)}" target="_blank" rel="noopener">${h}</a>` : `<span class="h">${h}</span>`;
            return `<div class="dup-row">${hh}<span class="t">${escapeHtml(relTime(r.created_at))}</span></div>`;
        }).join('')}
      </div>` : ''}
      <div style="display:flex;gap:8px;margin-top:6px">
        <a class="btn-primary" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener">View on Bluesky →</a>
      </div>`;
    $('#flyout').classList.add('open');
    $('#backdrop').classList.add('open');
}

function closeOverlays() {
    $$('.modal').forEach(m => m.classList.remove('open'));
    $('#flyout').classList.remove('open');
    $('#backdrop').classList.remove('open');
}

/* ───────────────────────── TOASTS ───────────────────────── */
const ICON_CHECK = '<path d="M3 8.5l3 3 7-7" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>';
const ICON_BELL = '<path d="M8 16a2 2 0 0 0 2-2H6a2 2 0 0 0 2 2zM8 1.9l-.8.16A4 4 0 0 0 4 6c0 .63-.13 2.2-.46 3.74-.16.77-.38 1.57-.66 2.26h10.24c-.29-.69-.5-1.49-.66-2.26C12.13 8.2 12 6.63 12 6a4 4 0 0 0-3.2-3.92L8 1.9z"/>';
let toastT;
function toast(msg, ok) {
    const w = $('#toast-wrap');
    const el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = `<span class="ti ${ok ? 'ok' : ''}"><svg class="svg" width="14" height="14" viewBox="0 0 16 16" fill="currentColor">${ok ? ICON_CHECK : ICON_BELL}</svg></span><span>${escapeHtml(msg)}</span>`;
    w.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 250); }, 2800);
}

const COMING_SOON = 'Accounts are coming soon — sign-up will let you save searches & follow accounts.';

/* ───────────────────────── AUTH-AWARE CHROME (Branch A: stubs) ───────────────────────── */
function renderTopbar() {
    $('#top-account').innerHTML =
        `<button class="btn-signin" data-auth="signin">Log in</button>
         <button class="btn-signup" data-auth="signup">Sign up</button>`;
}
function renderRailSubs() {
    $('#rail-subs-section').innerHTML = `
      <div class="rail-nudge">
        <div class="nh">＋ Subscribe to a filter</div>
        <div class="nb">Save any search and get new positions by daily or weekly alert. Free account — coming soon.</div>
        <button class="nbtn" data-auth="signup">Create account</button>
      </div>`;
}

/* ───────────────────────── COOKIE BANNER ───────────────────────── */
function setupCookieBanner() {
    if (typeof window.CookieConsent === 'undefined') return;
    const grant = () => { if (typeof window.gtag === 'function') window.gtag('consent', 'update', { analytics_storage: 'granted' }); };
    window.CookieConsent.run({
        guiOptions: { consentModal: { layout: 'bar', position: 'bottom', equalWeightButtons: false } },
        categories: { necessary: { enabled: true, readOnly: true }, analytics: {} },
        language: {
            default: 'en',
            translations: { en: { consentModal: {
                title: '> Cookies',
                description: 'We use Google Analytics for visitor stats. No ads, no profiling. <a href="/privacy">Privacy policy</a>.',
                acceptAllBtn: 'Accept', acceptNecessaryBtn: 'Decline', showPreferencesBtn: ''
            } } }
        },
        onConsent: ({ cookie }) => { if (cookie.categories.includes('analytics')) grant(); },
        onChange: ({ cookie }) => { if (cookie.categories.includes('analytics')) grant(); },
    });
}

/* ───────────────────────── EVENT WIRING ───────────────────────── */
function selectStream(stream) {
    if (stream === 'following' || stream === 'saved') { toast(COMING_SOON); return; }
    state.stream = stream;
    $$('.rail-link').forEach(x => x.classList.toggle('active', x.dataset.stream === stream));
    renderFeedReset();
}
function selectTab(tab) {
    if (tab === 'forme') { toast(COMING_SOON); return; }
    state.tab = tab;
    $$('.river-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === tab));
    renderFeedReset();
}

function wireEvents() {
    $('#backdrop').onclick = closeOverlays;
    $('#flyout-close').onclick = closeOverlays;
    $('#mark').onclick = () => { state.search = ''; $('#cmd-input').value = ''; selectStream('all'); window.scrollTo({ top: 0 }); };
    $('#clear-filters').onclick = clearFilters;

    // command bar / search
    const cmd = $('#cmd-input');
    let searchT;
    cmd.addEventListener('input', () => { clearTimeout(searchT); searchT = setTimeout(() => { state.search = cmd.value; renderFeedReset(); }, 180); });
    cmd.addEventListener('keydown', e => { if (e.key === 'Escape') { cmd.value = ''; state.search = ''; renderFeedReset(); cmd.blur(); } });

    // hide-aggregator chip
    $('#chip-hideaggr').onclick = e => { state.hideAggr = !state.hideAggr; e.currentTarget.classList.toggle('on', state.hideAggr); renderFeedReset(); };

    // streams + tabs
    $$('.rail-link').forEach(l => l.onclick = () => selectStream(l.dataset.stream));
    $$('.river-tab').forEach(t => t.onclick = () => selectTab(t.dataset.tab));

    // trends → set area filter
    $('#activity-trends').addEventListener('click', e => {
        const row = e.target.closest('[data-trend-area]'); if (!row) return;
        const area = row.dataset.trendArea;
        const chip = document.querySelector(`.chip[data-area="${CSS.escape(area)}"]`);
        if (chip && !chip.classList.contains('on')) chip.click();
    });

    // feed delegation
    $('#feed-stream').addEventListener('click', e => {
        if (e.target.closest('[data-stop]')) return; // let real links work
        const fol = e.target.closest('[data-follow]');
        if (fol) { e.stopPropagation(); toast(COMING_SOON); return; }
        const tog = e.target.closest('[data-toggle]');
        if (tog) {
            e.stopPropagation();
            const id = tog.dataset.toggle;
            state.threadOpen.has(id) ? state.threadOpen.delete(id) : state.threadOpen.add(id);
            const el = document.querySelector(`[data-thread="${CSS.escape(id)}"]`);
            if (el) el.classList.toggle('open');
            return;
        }
        const post = e.target.closest('.post');
        if (post) openFlyout(post.dataset.id);
    });

    // auth entry points + empty-state clear (delegated)
    document.addEventListener('click', e => {
        if (e.target.closest('[data-auth]')) { toast(COMING_SOON); return; }
        if (e.target.closest('#empty-clear')) { clearFilters(); return; }
    });

    // keyboard
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeOverlays();
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); $('#cmd-input').focus(); }
    });
}

/* ───────────────────────── INIT ───────────────────────── */
function onDataReady(positions, duplicates, total) {
    state.all = positions;
    state.duplicateMap = duplicates || {};
    state.total = total || positions.length;
    renderFilterChips();
    renderActivity();
    renderFeedReset();
}

async function init() {
    setupCookieBanner();
    renderTopbar();
    renderRailSubs();
    wireEvents();
    setupInfiniteScroll();

    const staticData = loadStaticData();
    if (staticData) {
        // immediate paint from embedded data
        onDataReady(staticData.positions, {}, staticData.total);
        // background full load (snapshot/live) for complete data + duplicates
        loadFullData()
            .then(({ positions, duplicates, total }) => onDataReady(positions, duplicates, total))
            .catch(err => console.warn('background load failed; using embedded data', err));
    } else {
        try {
            const { positions, duplicates, total } = await loadFullData();
            onDataReady(positions, duplicates, total);
        } catch (err) {
            console.error('init error', err);
            $('#feed-stream').innerHTML = `<div class="feed-error">Failed to load positions. Please try again later.</div>`;
        }
    }
}

document.addEventListener('DOMContentLoaded', init);
