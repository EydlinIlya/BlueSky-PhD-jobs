/* ============================================================
   PhD Sky — Research Library feed, accounts, saved searches, and alerts.
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
    'Biology': '#3F6B4F', 'Ecology': '#56703A', 'Computer Science': '#315F78',
    'Physics': '#516C80', 'Chemistry & Materials Science': '#6B6252', 'Medicine': '#985244',
    'Mathematics': '#625C82', 'Economics': '#866633', 'Sociology & Political Science': '#496C70',
    'Engineering': '#8A5E42', 'Environmental Sciences': '#56703A', 'Psychology': '#815C6D',
    'Neuroscience': '#625C82', 'History': '#765E49', 'Arts & Humanities': '#765E49',
    'General call': '#68736E',
};
function getDisciplineColor(d) { return DISCIPLINE_COLORS[d] || '#315F78'; }

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
function normalizePosition(position, index = 0) {
    return {
        ...position,
        country: normalizeCountry(position.country),
        // Production rows have an AT URI. Offline fixtures use the public URL
        // as a stable key so explicit detail actions work in mock mode too.
        uri: position.uri || position.url || `mock-position-${index}`,
    };
}

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
    view: 'feed',            // 'feed' | 'subs' | 'account' | 'followlist'
    stream: 'all',
    tab: 'latest',
    search: '',
    hideAggr: false,
    filters: { level: new Set(), country: new Set(), area: new Set() },
    threadOpen: new Set(),
    user: null,              // Supabase auth user | null
    authMode: 'signup',      // 'signup' | 'signin'
    follows: new Set(),      // followed Bluesky handles (account_follows)
    topics: new Set(),       // followed topic tokens — disciplines/countries (topic_follows)
    subs: [],                // this user's subscriptions (rows from `subscriptions`)
    profile: null,
};

const EMAIL_CONSENT_VERSION = 'weekly-alert-v1';

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
        const positions = data.positions.map(normalizePosition);
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
        all = all.concat(data.map(normalizePosition));
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
        const positions = (await fetchMockPositions()).map(normalizePosition);
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
            const positions = data.positions.map(normalizePosition);
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
    if (!iso) return 'Older';
    const d = new Date(iso); const now = new Date();
    const startOf = x => new Date(x.getFullYear(), x.getMonth(), x.getDate());
    const diffDays = Math.round((startOf(now) - startOf(d)) / 86400000);
    if (diffDays <= 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return 'This week';
    if (diffDays < 31) return 'This month';
    return 'Older';
}

/* ───────────────────────── FILTERING ───────────────────────── */
// Does a position match a saved subscription's filter? (mirrors the digest's
// position_matches in scripts/send_subscription_digests.py)
function subMatchesPosition(s, p) {
    if (s.hide_aggregators && isAggregator(p.user_handle)) return false;
    const discs = p.disciplines || [], types = p.position_type || [];
    const wd = s.disciplines || [], wc = s.countries || [], wt = s.position_types || [];
    if (wd.length && !discs.some(d => wd.includes(d))) return false;
    if (wc.length && !wc.includes(p.country)) return false;
    if (wt.length && !types.some(t => wt.includes(t))) return false;
    const q = (s.query_text || '').trim().toLowerCase();
    if (q) {
        const hay = [p.message, p.user_handle, p.country, discs.join(' '), types.join(' ')].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
    }
    return true;
}

// The "Following" tab = everything you follow + everything you've subscribed to:
// followed accounts ∪ followed topics ∪ saved-search subscriptions.
function matchesFollowing(p) {
    if (state.follows.has(p.user_handle)) return true;
    const discs = p.disciplines || [];
    if (discs.some(d => state.topics.has(d)) || state.topics.has(p.country)) return true;
    for (const s of state.subs) if (subMatchesPosition(s, p)) return true;
    return false;
}

function followingCount() {
    return state.follows.size + state.topics.size + state.subs.length;
}

// Filters shared by both tabs (level/country/area/search/hide-aggregator) —
// NOT the following constraint.
function passesFilters(p) {
    if (state.hideAggr && isAggregator(p.user_handle)) return false;
    const f = state.filters;
    const types = p.position_type || [], discs = p.disciplines || [];
    if (f.level.size && !types.some(t => f.level.has(t))) return false;
    if (f.country.size && !f.country.has(p.country)) return false;
    if (f.area.size && !discs.some(d => f.area.has(d))) return false;
    const q = state.search.trim().toLowerCase();
    if (q) {
        const hay = [p.message, p.user_handle, p.country, discs.join(' '), types.join(' ')]
            .join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
    }
    return true;
}

function visiblePositions() {
    const following = state.tab === 'following';
    return state.all.filter(p => passesFilters(p) && (!following || matchesFollowing(p)));
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
    const moreLink = truncated ? '<button type="button" class="more-link" data-detail="1">Show full text</button>' : '';

    const reposts = (p.uri && state.duplicateMap[p.uri]) || [];
    const rep = reposts.length;
    const tOpen = state.threadOpen.has(p.uri);
    const profileUrl = `https://bsky.app/profile/${encodeURIComponent(handle)}`;
    const postUrl = safeUrl(p.url) || profileUrl;

    // Timestamp doubles as the permalink to the static /p/<slug> page. This is
    // the feed's only internal link to that page, so crawlers can reach the
    // per-job corpus (the <noscript> block is dropped by JS-rendering crawlers).
    const slug = extractSlug(p.uri);
    const timeHTML = slug
        ? `<a class="p-time" href="/p/${slug}" data-stop title="Permalink">${escapeHtml(relTime(p.created_at))}</a>`
        : `<span class="p-time">${escapeHtml(relTime(p.created_at))}</span>`;

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
        ${timeHTML}
        ${(() => { const on = state.follows.has(handle); return `<button type="button" class="p-follow ${on ? 'on' : ''}" data-follow="${escapeHtml(handle)}" aria-pressed="${on}" title="${on ? 'Unfollow' : 'Follow'} @${escapeHtml(handle)}">${on ? 'Following' : 'Follow'}</button>`; })()}
      </div>
      <div class="p-meta-strip">${discBadges}${typeBadges}${countryBadge}</div>
      <div class="p-body">${escapeHtml(bodyText)}${moreLink}</div>
      ${threadHTML}
      <div class="p-actions">
        <button type="button" class="p-act" data-detail="1">Details</button>
        ${slug ? `<a class="p-act" href="/p/${slug}" data-stop>Permalink</a>` : ''}
        <a class="p-act" href="${escapeHtml(postUrl)}" target="_blank" rel="noopener" data-stop style="margin-left:auto;color:var(--primary)">View source</a>
      </div>
    </article>`;
}

function emptyStateHTML() {
    if (state.tab === 'following') {
        if (followingCount() === 0) {
            return `<div class="feed-empty"><div class="ee-mark">—</div><div class="ee-t">Build your Following feed</div><div class="ee-d">Tap <b>+ follow</b> on any poster, follow a discipline/country from <b>Top areas/countries</b>, or <b>save a search</b> — they all show up here together.</div><button class="btn-primary" data-tab-go="latest">Browse all positions</button></div>`;
        }
        return `<div class="feed-empty"><div class="ee-mark">—</div><div class="ee-t">Nothing new from your follows & subscriptions</div><div class="ee-d">When accounts you follow or your saved searches get new matches, they'll appear here.</div><button class="btn-primary" data-tab-go="latest">Show all latest</button></div>`;
    }
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

// Counts live only on the two top tabs.
function updateCounts() {
    let latest = 0, followingMatched = 0;
    for (const p of state.all) {
        if (!passesFilters(p)) continue;
        latest++;
        if (state.user && matchesFollowing(p)) followingMatched++;
    }
    const set = (sel, v) => { const el = $(sel); if (el) el.textContent = v; };
    set('#tab-latest-ct', latest.toLocaleString());
    set('#tab-following-ct', state.user ? followingMatched.toLocaleString() : '');
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
function countNames(extract) {
    const counts = {};
    for (const p of state.all) for (const name of extract(p)) counts[name] = (counts[name] || 0) + 1;
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(e => e[0]);
}

const CHIP_TOP_N = 5;
const chipNames = { area: [], country: [] };   // full name lists by frequency (cached)

function renderFilterChips() {
    // Level — fixed set
    $('#chips-level').innerHTML = LEVEL_CHIPS.map(([val, lab]) =>
        `<button type="button" class="chip" data-level="${escapeHtml(val)}" aria-pressed="false">${escapeHtml(lab)}</button>`).join('');
    // Area + Country — top 5 chips (+ any selected off-list) inline; full alpha list in dropdown
    chipNames.area = countNames(p => p.disciplines || []);
    chipNames.country = countNames(p => (p.country && p.country !== 'Unknown') ? [p.country] : []);
    buildChipDropdown('area', 'chips-area');
    buildChipDropdown('country', 'chips-country');
    renderChipRow('area', 'chips-area');
    renderChipRow('country', 'chips-country');
    bindChips();
}

// Inline chips = top-N by frequency PLUS any currently-selected value not in the
// top-N (so off-list picks show as selected bubbles), then the "all N…" trigger.
function renderChipRow(kind, containerId) {
    const container = $('#' + containerId);
    if (!container) return;
    const names = chipNames[kind];
    const top = names.slice(0, CHIP_TOP_N);
    const extra = [...state.filters[kind]].filter(v => !top.includes(v));
    const shown = [...top, ...extra];
    const label = n => kind === 'area' ? discShort(n) : n;
    const chip = n => `<button type="button" class="chip" data-${kind}="${escapeHtml(n)}" aria-pressed="false">${escapeHtml(label(n))}</button>`;
    container.innerHTML = shown.map(chip).join('') +
        (names.length > CHIP_TOP_N ? `<button type="button" class="chip chip-more" data-more="${kind}" aria-expanded="false">All ${names.length}</button>` : '');
}

// Full-list dropdown (overlay): optional search + scrollable, ALPHABETICAL checklist.
function buildChipDropdown(kind, containerId) {
    const frow = $('#' + containerId).parentElement;
    const names = chipNames[kind];
    let dd = frow.querySelector('.chip-dropdown');
    if (names.length > CHIP_TOP_N) {
        if (!dd) { dd = document.createElement('div'); dd.className = 'chip-dropdown'; frow.appendChild(dd); }
        const sorted = [...names].sort((a, b) => a.localeCompare(b));
        const needSearch = names.length > 8;
        const label = n => kind === 'area' ? discShort(n) : n;
        dd.innerHTML =
            (needSearch ? `<input class="dd-search" placeholder="Filter ${kind === 'area' ? 'areas' : 'countries'}…">` : '') +
            `<div class="dd-list">` +
            sorted.map(n => `<button type="button" class="dd-item" data-${kind}="${escapeHtml(n)}" aria-pressed="false"><span class="dd-check" aria-hidden="true">✓</span><span class="dd-lab">${escapeHtml(label(n))}</span></button>`).join('') +
            `</div>`;
    } else if (dd) { dd.remove(); }
}

function applyAreaChipStyle(c, on) {
    if (on) { const col = getDisciplineColor(c.dataset.area); c.style.background = col; c.style.borderColor = col; c.style.color = '#fff'; }
    else { c.style.background = ''; c.style.borderColor = ''; c.style.color = ''; }
}

function setFilterValue(kind, val, on) {
    if (on) state.filters[kind].add(val); else state.filters[kind].delete(val);
    if (kind === 'level') {
        const chip = document.querySelector(`.chip[data-level="${CSS.escape(val)}"]`);
        if (chip) { chip.classList.toggle('on', on); chip.setAttribute('aria-pressed', String(on)); }
    } else {
        renderChipRow(kind, 'chips-' + kind);            // show/hide off-list selected bubbles
        const it = document.querySelector(`.chip-dropdown .dd-item[data-${kind}="${CSS.escape(val)}"]`);
        if (it) { it.classList.toggle('on', on); it.setAttribute('aria-pressed', String(on)); }
        bindChips();                                     // rebind the rebuilt chip row
    }
    renderFeedReset();
}

function bindChips() {
    $$('.chip[data-level]').forEach(c => {
        c.classList.toggle('on', state.filters.level.has(c.dataset.level));
        c.setAttribute('aria-pressed', String(state.filters.level.has(c.dataset.level)));
        c.onclick = () => setFilterValue('level', c.dataset.level, !state.filters.level.has(c.dataset.level));
    });
    $$('.chip[data-country]').forEach(c => {
        c.classList.toggle('on', state.filters.country.has(c.dataset.country));
        c.setAttribute('aria-pressed', String(state.filters.country.has(c.dataset.country)));
        c.onclick = () => setFilterValue('country', c.dataset.country, !state.filters.country.has(c.dataset.country));
    });
    $$('.chip[data-area]').forEach(c => {
        const sel = state.filters.area.has(c.dataset.area);
        c.classList.toggle('on', sel); applyAreaChipStyle(c, sel);
        c.setAttribute('aria-pressed', String(sel));
        c.onclick = () => setFilterValue('area', c.dataset.area, !state.filters.area.has(c.dataset.area));
    });
    // "all N…" triggers open the fixed-position dropdown (closing any other)
    $$('.chip-more').forEach(c => c.onclick = e => {
        e.stopPropagation();
        const dd = c.closest('.f-row').querySelector('.chip-dropdown');
        $$('.chip-dropdown.open').forEach(o => { if (o !== dd) o.classList.remove('open'); });
        const opening = !dd.classList.contains('open');
        dd.classList.toggle('open', opening);
        c.setAttribute('aria-expanded', String(opening));
        if (opening) {
            const r = c.getBoundingClientRect();
            // The mobile filter sheet animates with translateY, and a transformed
            // ancestor becomes the containing block for position:fixed children —
            // so viewport-space coordinates land offset by the sheet's origin.
            // Probe where 0,0 actually renders and rebase against it. With no
            // transformed ancestor the probe reads 0 and this is a no-op.
            dd.style.top = '0px';
            dd.style.left = '0px';
            const origin = dd.getBoundingClientRect();
            // Measure the real box now that it's displayed — the old code clamped
            // against a hard-coded 280px, which pushed the list off short viewports.
            const h = dd.offsetHeight || 280;
            const w = dd.offsetWidth || 240;
            // Prefer below the trigger; flip above when there isn't room.
            const below = r.bottom + 6;
            const vTop = (below + h + 8 <= window.innerHeight) ? below
                       : Math.max(8, Math.min(r.top - h - 6, window.innerHeight - h - 8));
            const vLeft = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
            dd.style.top = Math.round(vTop - origin.top) + 'px';
            dd.style.left = Math.round(vLeft - origin.left) + 'px';
            // Autofocus pops the soft keyboard on mobile and shrinks the viewport
            // under the sheet, so only do it where there's a pointer.
            const s = dd.querySelector('.dd-search');
            if (s && window.matchMedia('(hover: hover)').matches) s.focus();
        }
    });
    // dropdown checklist items
    $$('.chip-dropdown .dd-item').forEach(it => {
        const kind = it.dataset.area !== undefined ? 'area' : 'country';
        const val = it.dataset[kind];
        it.classList.toggle('on', state.filters[kind].has(val));
        it.setAttribute('aria-pressed', String(state.filters[kind].has(val)));
        it.onclick = () => setFilterValue(kind, val, !state.filters[kind].has(val));
    });
    // dropdown search box filters the visible list
    $$('.chip-dropdown .dd-search').forEach(inp => inp.oninput = () => {
        const q = inp.value.trim().toLowerCase();
        inp.closest('.chip-dropdown').querySelectorAll('.dd-item').forEach(it => {
            it.style.display = it.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
    });
}

function clearFilters() {
    state.filters.level.clear(); state.filters.country.clear(); state.filters.area.clear();
    state.hideAggr = false; state.search = '';
    $('#cmd-input').value = '';
    $('#chip-hideaggr').classList.remove('on');
    $('#chip-hideaggr').setAttribute('aria-pressed', 'false');
    $$('.chip.on').forEach(c => { c.classList.remove('on'); c.style.background = ''; c.style.borderColor = ''; c.style.color = ''; });
    $$('.chip-dropdown .dd-item.on').forEach(it => it.classList.remove('on'));
    $$('.chip-dropdown.open').forEach(d => d.classList.remove('open'));
    renderFeedReset();
}

/* ───────────────────────── ACTIVITY RAIL ───────────────────────── */
function renderActivity() {
    const today = state.all.filter(p => dayLabel(p.created_at) === 'Today').length;
    $('#activity-today').innerHTML =
        `<div>· <strong style="color:var(--fg)">+${today}</strong> new position${today === 1 ? '' : 's'} today</div>`;

    const dcounts = {};
    for (const p of state.all) for (const d of (p.disciplines || [])) dcounts[d] = (dcounts[d] || 0) + 1;
    renderTrendCard('#activity-trends', dcounts, 'area');

    const ccounts = {};
    for (const p of state.all) { const c = p.country; if (c && c !== 'Unknown') ccounts[c] = (ccounts[c] || 0) + 1; }
    renderTrendCard('#activity-countries', ccounts, 'country');
}

// Renders a "top 5 + Other" stat list. kind 'area' uses discipline colors and
// discipline topic-follows; kind 'country' uses the country color + country
// topic-follows. Named rows click to set the matching filter; Other is inert.
function renderTrendCard(sel, counts, kind) {
    const el = $(sel); if (!el) return;
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const top = entries.slice(0, 5);
    const otherSum = entries.slice(5).reduce((s, [, n]) => s + n, 0);
    const max = top.length ? top[0][1] : 1;
    const colorFor = n => kind === 'area' ? getDisciplineColor(n) : 'var(--country-bg)';
    const label = n => kind === 'area' ? discShort(n) : n;
    const topicKind = kind === 'area' ? 'discipline' : 'country';
    let html = top.map(([name, n], i) => {
        const on = state.topics.has(name);
        const followBtn = state.user
            ? `<button type="button" class="trend-follow ${on ? 'on' : ''}" data-topic="${escapeHtml(name)}" data-topic-kind="${topicKind}" aria-pressed="${on}">${on ? 'Following' : 'Follow'}</button>`
            : '';
        return `<div class="trend-row">
        <button type="button" class="trend-main" data-trend="${escapeHtml(name)}" data-trend-kind="${kind}" aria-label="Filter by ${escapeHtml(label(name))}">
        <span class="trend-rank">${i + 1}</span>
        <span class="trend-name">${escapeHtml(label(name))}</span>
        <span class="trend-bar"><span class="trend-fill" style="width:${Math.round(n / max * 100)}%;background:${colorFor(name)}"></span></span>
        <span class="trend-ct">${n}</span></button>${followBtn}
      </div>`;
    }).join('');
    if (otherSum > 0) {
        html += `<div class="trend-row trend-other">
        <span class="trend-rank">·</span>
        <span class="trend-name" style="color:var(--fg-subtle)">Other</span>
        <span class="trend-bar"><span class="trend-fill" style="width:${Math.round(otherSum / max * 100)}%;background:var(--aggregator-bg)"></span></span>
        <span class="trend-ct">${otherSum}</span>
      </div>`;
    }
    el.innerHTML = html;
}

/* ───────────────────────── POST FLYOUT ───────────────────────── */
let activeDialog = null;
let overlayReturnFocus = null;

function setBackgroundInert(inert) {
    ['.topbar', '.shell', '#mobile-nav', '.site-footer'].forEach(selector => {
        const element = $(selector);
        if (element) element.inert = inert;
    });
}

function openDialog(element, initialSelector) {
    overlayReturnFocus = document.activeElement;
    activeDialog = element;
    element.classList.add('open');
    element.setAttribute('aria-hidden', 'false');
    $('#backdrop').classList.add('open');
    setBackgroundInert(true);
    requestAnimationFrame(() => {
        const first = initialSelector ? element.querySelector(initialSelector) : null;
        (first || element.querySelector('button, a[href], input, [tabindex="0"]') || element).focus();
    });
}

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
    openDialog($('#flyout'), '#flyout-close');
}

function closeOverlays() {
    $$('.modal').forEach(m => { m.classList.remove('open'); m.setAttribute('aria-hidden', 'true'); });
    $('#flyout').classList.remove('open');
    $('#flyout').setAttribute('aria-hidden', 'true');
    const rail = $('#left-rail'); if (rail) rail.classList.remove('open');  // mobile filter sheet
    $('#backdrop').classList.remove('open');
    setBackgroundInert(false);
    activeDialog = null;
    if (overlayReturnFocus && document.contains(overlayReturnFocus)) overlayReturnFocus.focus();
    overlayReturnFocus = null;
}

// Sync active state across left rail, river tabs, and the mobile bottom nav.
function setActiveNav() {
    let railKey;
    if (state.view === 'subs') railKey = 'saved';
    else if (state.view === 'followlist') railKey = 'followlist';
    else railKey = state.tab === 'latest' ? 'all' : '';   // My feed has no rail link
    $$('.rail-link').forEach(x => {
        const active = x.dataset.stream === railKey;
        x.classList.toggle('active', active);
        x.setAttribute('aria-pressed', String(active));
    });
    $$('.river-tab').forEach(x => {
        const active = state.view === 'feed' && x.dataset.tab === state.tab;
        x.classList.toggle('active', active);
        x.setAttribute('aria-pressed', String(active));
    });
    const mnavKey = state.view === 'subs' ? 'saved'
        : state.view === 'followlist' ? ''
        : (state.tab === 'following' ? 'following' : 'all');
    $$('.mnav-btn').forEach(b => b.classList.toggle('active', b.dataset.mnav === mnavKey));
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

// Streams/tabs that depend on subscriptions (Branch C) / follows (Branch D).
const COMING_SOON = 'This arrives in the next release — your account is ready for it.';

/* ───────────────────────── AUTH (Supabase) ───────────────────────── */
// Native providers go through Supabase Auth; bluesky/orcid are deferred to the
// auth-academic-oauth branch and render as "coming soon".
const PROVIDERS = [
    { id: 'bluesky', label: 'Continue with Bluesky', hint: 'soon', cls: 'bsky', soon: true,
      glyph: '<svg width="18" height="18" viewBox="0 0 600 530"><path fill="#3b82f6" d="M135 75c66 49 137 150 163 204 26-54 97-155 163-204 48-36 126-63 126 26 0 18-10 150-16 171-21 73-95 91-161 80 115 20 144 85 81 150-120 124-172-31-185-66-2-7-4-10-4-7 0-3-2 0-4 7-13 35-65 190-185 66-63-65-34-130 81-150-66 11-140-7-161-80-6-21-16-153-16-171 0-89 78-62 126-26z"/></svg>' },
    { id: 'orcid', label: 'Continue with ORCID', hint: 'soon', soon: true,
      glyph: '<svg width="18" height="18" viewBox="0 0 256 256"><path fill="#A6CE39" d="M128 0C57.3 0 0 57.3 0 128s57.3 128 128 128 128-57.3 128-128S198.7 0 128 0z"/><path fill="#fff" d="M86.3 186.2H70.9V79.1h15.4v107.1zM108.9 79.1h41.6c39.6 0 57 28.3 57 53.6 0 27.5-21.5 53.6-56.8 53.6h-41.8V79.1zm15.4 93.3h24.5c34.9 0 42.9-26.5 42.9-39.7 0-21.5-13.7-39.7-43.7-39.7h-23.7v79.4zM88.7 56.8c0 5.5-4.5 10.1-10.1 10.1s-10.1-4.6-10.1-10.1c0-5.6 4.5-10.1 10.1-10.1s10.1 4.6 10.1 10.1z"/></svg>' },
    { id: 'google', label: 'Continue with Google',
      glyph: '<svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.3 6.1 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 16 18.9 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.3 0-9.7-3.1-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.1-4.1 5.6l6.2 5.2C41.4 35.6 44 30.3 44 24c0-1.3-.1-2.3-.4-3.5z"/></svg>' },
    { id: 'github', label: 'Continue with GitHub',
      glyph: '<svg width="18" height="18" viewBox="0 0 16 16" fill="#e2e8f0"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>' },
];
const ICON_CLOSE = '<svg class="svg" width="14" height="14" viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>';

function authEnabled() { return !!supabaseClient; }

function userInitials(u) {
    const name = (u.user_metadata && (u.user_metadata.full_name || u.user_metadata.name)) || u.email || '?';
    return name.split(/[ @.]/).filter(Boolean).map(w => w[0]).slice(0, 2).join('').toUpperCase() || '?';
}
function userName(u) {
    return (u.user_metadata && (u.user_metadata.full_name || u.user_metadata.name)) || (u.email ? u.email.split('@')[0] : 'Researcher');
}

function openAuth(mode) {
    if (!authEnabled()) { toast('Sign-in is unavailable in this mode.'); return; }
    state.authMode = mode || 'signup';
    renderAuthModal();
    openDialog($('#modal-auth'), '#auth-email');
}

function renderAuthModal() {
    const signup = state.authMode === 'signup';
    $('#auth-card').innerHTML = `
      <button class="modal-close" data-close="1">${ICON_CLOSE}</button>
      <div class="modal-head">
        <div class="auth-mark">PhD Sky</div>
        <div class="auth-sub">${signup
            ? 'Create a free account to subscribe to filters and follow accounts.'
            : 'Welcome back. Sign in to manage your subscriptions.'}</div>
      </div>
      <div class="auth-tabs">
        <button class="auth-tab ${signup ? 'active' : ''}" data-mode="signup">Sign up</button>
        <button class="auth-tab ${!signup ? 'active' : ''}" data-mode="signin">Log in</button>
      </div>
      <div class="auth-body">
        ${PROVIDERS.filter(p => !p.soon).map(p => `
          <button class="prov-btn ${p.cls || ''}" data-prov="${p.id}">
            <span class="glyph">${p.glyph}</span>
            <span class="pl">${signup ? p.label : p.label.replace('Continue', 'Sign in')}</span>
            ${p.hint ? `<span class="pr">${p.hint}</span>` : ''}
          </button>`).join('')}
        <div class="auth-divider">or</div>
        <div class="field"><label for="auth-email">Email</label><input type="email" id="auth-email" placeholder="you@university.edu" autocomplete="email"></div>
        <div class="field"><label for="auth-pass">Password</label><input type="password" id="auth-pass" placeholder="At least 8 characters" autocomplete="${signup ? 'new-password' : 'current-password'}"></div>
        <button class="btn-primary" id="auth-email-submit" style="margin-top:4px">${signup ? 'Create account' : 'Log in'} →</button>
        <div class="auth-foot">${signup
            ? 'Already have an account? <a data-mode="signin">Log in</a>'
            : 'New here? <a data-mode="signup">Create an account</a>'}</div>
        ${signup ? `<div class="auth-foot" style="margin-top:8px">By creating an account you agree to our <a href="/terms" target="_blank" rel="noopener">Terms</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</div>` : ''}
      </div>`;
    bindAuth();
}

function bindAuth() {
    $('#auth-card').querySelectorAll('[data-prov]').forEach(b => b.onclick = () => doProviderAuth(b.dataset.prov));
    const sub = $('#auth-email-submit');
    if (sub) sub.onclick = doEmailAuth;
    $('#auth-card').querySelectorAll('[data-mode]').forEach(a => a.onclick = () => { state.authMode = a.dataset.mode; renderAuthModal(); });
    $('#auth-card').querySelectorAll('[data-close]').forEach(b => b.onclick = closeOverlays);
}

async function doProviderAuth(id) {
    const prov = PROVIDERS.find(p => p.id === id);
    if (!prov || prov.soon) { toast(`${prov ? prov.label.replace('Continue with ', '') : 'This provider'} sign-in is coming soon.`); return; }
    const { error } = await supabaseClient.auth.signInWithOAuth({
        provider: id,
        options: { redirectTo: window.location.origin + window.location.pathname },
    });
    if (error) toast(`Sign-in failed: ${error.message}`);
    // On success the browser redirects; session is restored on return.
}

async function doEmailAuth() {
    const email = ($('#auth-email').value || '').trim();
    const pass = $('#auth-pass').value || '';
    if (!email) { $('#auth-email').focus(); return; }
    if (!pass) { $('#auth-pass').focus(); return; }
    const signup = state.authMode === 'signup';
    const btn = $('#auth-email-submit'); btn.disabled = true;
    try {
        if (signup) {
            // Confirmation link returns to the current origin (must be in Supabase's
            // redirect allow-list), so email signup works on previews / localhost,
            // not just the Site URL (phdsky.org).
            const { data, error } = await supabaseClient.auth.signUp({
                email, password: pass,
                options: { emailRedirectTo: window.location.origin + window.location.pathname },
            });
            if (error) { toast(`Sign-up failed: ${error.message}`); return; }
            if (data.session) { closeOverlays(); toast('Welcome to PhD Sky!', true); }
            else { closeOverlays(); toast('Check your email to confirm your account.', true); }
        } else {
            const { error } = await supabaseClient.auth.signInWithPassword({ email, password: pass });
            if (error) { toast(`Sign-in failed: ${error.message}`); return; }
            closeOverlays(); toast('Signed in.', true);
        }
    } finally { btn.disabled = false; }
}

async function signOut() {
    await supabaseClient.auth.signOut();
    toast('Signed out.');
}

/* ───────────────────────── AUTH-AWARE CHROME ───────────────────────── */
function renderTopbar() {
    const u = state.user;
    const wrap = $('#top-account');
    if (u) {
        wrap.innerHTML = `
          <div class="profile-wrap">
            <button type="button" class="avatar" id="avatar-btn" title="${escapeHtml(userName(u))}" aria-label="Open account menu" aria-expanded="false">${escapeHtml(userInitials(u))}</button>
            <div class="profile-menu" id="profile-menu" role="menu">
              <div class="pm-header">
                <div class="avatar sm">${escapeHtml(userInitials(u))}</div>
                <div class="pm-id"><span class="pm-name">${escapeHtml(userName(u))}</span><span class="pm-handle">${escapeHtml(u.email || '')}</span></div>
              </div>
              <div class="pm-list">
                <button type="button" class="pm-item" role="menuitem" data-pm="feed">Feed</button>
                <button type="button" class="pm-item" role="menuitem" data-pm="subs">Saved searches <span class="badge-ct">${state.subs.length}</span></button>
                <button type="button" class="pm-item" role="menuitem" data-pm="following">My feed</button>
                <button type="button" class="pm-item" role="menuitem" data-pm="account">Account &amp; privacy</button>
                <div class="pm-sep"></div>
                <button type="button" class="pm-item danger" role="menuitem" data-pm="logout">Sign out</button>
              </div>
            </div>
          </div>`;
        const av = $('#avatar-btn');
        av.onclick = e => {
            e.stopPropagation();
            const open = $('#profile-menu').classList.toggle('open');
            av.setAttribute('aria-expanded', String(open));
        };
        wrap.querySelectorAll('[data-pm]').forEach(it => it.onclick = () => {
            const a = it.dataset.pm;
            $('#profile-menu').classList.remove('open');
            if (a === 'logout') signOut();
            else if (a === 'subs') selectStream('saved');
            else if (a === 'following') selectStream('following');
            else if (a === 'account') setView('account');
            else if (a === 'feed') selectStream('all');
        });
    } else {
        wrap.innerHTML =
            `<button class="btn-signin" data-auth="signin">Log in</button>
             <button class="btn-signup" data-auth="signup">Sign up</button>`;
        wrap.querySelectorAll('[data-auth]').forEach(b => b.onclick = () => openAuth(b.dataset.auth));
    }
}

function renderRailSubs() {
    const u = state.user;
    const sec = $('#rail-subs-section');
    if (u) {
        const list = state.subs.length ? state.subs.map(s => `
          <button type="button" class="sub-row" data-open-subs="1">
            <span class="ss-q">${escapeHtml(subLabel(s))}</span>
            <span class="ss-meta"><span class="cad">${s.deliver_email && s.email_consent_at ? 'Weekly email on' : 'Saved only'}</span></span>
          </button>`).join('')
          : `<div class="saved-state">No saved searches yet.</div>`;
        sec.innerHTML = `
          <div class="rail-title">Saved searches <button type="button" class="more text-button" data-open-subs="1">Manage</button></div>
          ${list}
          <button type="button" class="btn-add-search" id="rail-add-sub">Save current search</button>
          <button type="button" class="btn-primary" id="rail-email-sub">Email me weekly</button>`;
        sec.querySelectorAll('[data-open-subs]').forEach(el => el.onclick = () => setView('subs'));
        $('#rail-add-sub').onclick = () => saveCurrentSearch();
        $('#rail-email-sub').onclick = () => startWeeklyForCurrentSearch();
    } else {
        sec.innerHTML = `
          <div class="rail-nudge">
            <div class="nh">Create a free account</div>
            <div class="nb">Save research queries, follow sources, and optionally request one weekly email.</div>
            <button class="nbtn" data-auth="signup">Sign up</button>
          </div>`;
        sec.querySelectorAll('[data-auth]').forEach(b => b.onclick = () => openAuth(b.dataset.auth));
    }
}

/* ───────────────────────── FOLLOWS ───────────────────────── */
// The rail "Following" tab opens this view: a list of accounts the user follows
// (mirrors the Subscriptions page).
function renderFollowingPage() {
    const el = $('#view-following');
    if (!el) return;
    if (!state.user) { el.innerHTML = ''; return; }
    const handles = [...state.follows].sort((a, b) => a.localeCompare(b));
    const rows = handles.length ? handles.map(h => `
        <div class="acct-row">
          <div class="acct-avatar ${isAggregator(h) ? 'aggr' : ''}">${escapeHtml(h[0] ? h[0].toUpperCase() : '?')}</div>
          <a class="acct-handle" href="https://bsky.app/profile/${encodeURIComponent(h)}" target="_blank" rel="noopener">@${escapeHtml(h)}</a>
          ${isAggregator(h) ? '<span class="p-aggr-tag">aggr</span>' : ''}
          <button class="acct-unfollow" data-unfollow="${escapeHtml(h)}">following</button>
        </div>`).join('') : `
        <div class="subs-empty">
          <div class="ee">You're not following any accounts yet.</div>
          <button class="btn-primary" data-tab-go="latest">Browse positions</button>
        </div>`;
    el.innerHTML = `
      <div class="subs-page">
        <div class="subs-hero">
          <h1 class="subs-h1">Following</h1>
          <div class="subs-lead">Accounts you follow — their new positions appear in <b>My feed</b>. Follow more with <b>+ follow</b> on any post.</div>
        </div>
        <div>
          <div class="subs-block-title"><span>Accounts · ${handles.length}</span></div>
          ${rows}
        </div>
      </div>`;
    el.querySelectorAll('[data-unfollow]').forEach(b => b.onclick = () => toggleFollowAccount(b.dataset.unfollow));
    el.querySelectorAll('[data-tab-go]').forEach(b => b.onclick = () => selectTab(b.dataset.tabGo));
}

async function loadFollows() {
    if (!state.user) { state.follows = new Set(); state.topics = new Set(); return; }
    const [acct, topic] = await Promise.all([
        supabaseClient.from('account_follows').select('handle'),
        supabaseClient.from('topic_follows').select('token'),
    ]);
    if (acct.error) console.warn('loadFollows (accounts) failed', acct.error);
    if (topic.error) console.warn('loadFollows (topics) failed', topic.error);
    state.follows = new Set((acct.data || []).map(r => r.handle));
    state.topics = new Set((topic.data || []).map(r => r.token));
}

async function toggleFollowAccount(handle) {
    if (!state.user) { openAuth('signup'); return; }
    const adding = !state.follows.has(handle);
    if (adding) {
        state.follows.add(handle);
        const { error } = await supabaseClient.from('account_follows')
            .insert({ user_id: state.user.id, handle });
        if (error) { state.follows.delete(handle); toast(`Follow failed: ${error.message}`); return; }
    } else {
        state.follows.delete(handle);
        const { error } = await supabaseClient.from('account_follows')
            .delete().eq('user_id', state.user.id).eq('handle', handle);
        if (error) { state.follows.add(handle); toast(`Unfollow failed: ${error.message}`); return; }
    }
    // Update any visible follow buttons for this handle + the rail count.
    $$(`[data-follow="${CSS.escape(handle)}"]`).forEach(b => {
        b.classList.toggle('on', adding);
        b.setAttribute('aria-pressed', String(adding));
        b.textContent = adding ? 'Following' : 'Follow';
    });
    updateCounts();
    if (state.view === 'followlist') renderFollowingPage();
    if (state.tab === 'following') renderFeedReset();
    toast(adding ? `Following @${handle}` : `Unfollowed @${handle}`, adding);
}

async function toggleFollowTopic(token, kind) {
    if (!state.user) { openAuth('signup'); return; }
    const adding = !state.topics.has(token);
    if (adding) {
        state.topics.add(token);
        const { error } = await supabaseClient.from('topic_follows')
            .insert({ user_id: state.user.id, token, kind });
        if (error) { state.topics.delete(token); toast(`Follow failed: ${error.message}`); return; }
    } else {
        state.topics.delete(token);
        const { error } = await supabaseClient.from('topic_follows')
            .delete().eq('user_id', state.user.id).eq('token', token);
        if (error) { state.topics.add(token); toast(`Unfollow failed: ${error.message}`); return; }
    }
    renderActivity();
    if (state.tab === 'following') renderFeedReset();
    toast(adding ? `Following ${discShort(token)}` : `Unfollowed ${discShort(token)}`, adding);
}

/* ───────────────────────── SUBSCRIPTIONS ───────────────────────── */
function subLabel(s) {
    const parts = [
        ...(s.disciplines || []).map(discShort),
        ...(s.position_types || []),
        ...(s.countries || []),
    ];
    if (s.query_text) parts.push(`"${s.query_text}"`);
    return parts.length ? parts.join(' · ') : 'all positions';
}

function currentFilterPayload() {
    return {
        query_text: state.search.trim() || null,
        disciplines: [...state.filters.area].sort(),
        countries: [...state.filters.country].sort(),
        position_types: [...state.filters.level].sort(),
        hide_aggregators: state.hideAggr,
    };
}

async function loadSubs() {
    if (!state.user) { state.subs = []; return; }
    const { data, error } = await supabaseClient
        .from('subscriptions').select('*').order('created_at', { ascending: false });
    if (error) { console.warn('loadSubs failed', error); return; }
    state.subs = data || [];
}

function sameFilter(subscription, payload) {
    const normalized = values => [...(values || [])].sort().join('\u0000');
    return (subscription.query_text || '').trim().toLowerCase() === (payload.query_text || '').trim().toLowerCase()
        && normalized(subscription.disciplines) === normalized(payload.disciplines)
        && normalized(subscription.countries) === normalized(payload.countries)
        && normalized(subscription.position_types) === normalized(payload.position_types)
        && Boolean(subscription.hide_aggregators) === Boolean(payload.hide_aggregators);
}

async function ensureCurrentSearchSaved() {
    const payload = currentFilterPayload();
    const existing = state.subs.find(subscription => sameFilter(subscription, payload));
    if (existing) return { subscription: existing, created: false };
    const row = {
        user_id: state.user.id,
        ...payload,
        cadence: 'weekly',
        deliver_email: false,
        deliver_rss: false,
    };
    const { data, error } = await supabaseClient.from('subscriptions').insert(row).select('*').single();
    if (error) {
        if (error.code === '23505') {
            await loadSubs();
            return { subscription: state.subs.find(subscription => sameFilter(subscription, payload)), created: false };
        }
        throw error;
    }
    state.subs.unshift(data);
    return { subscription: data, created: true };
}

async function saveCurrentSearch() {
    if (!state.user) { openAuth('signup'); return; }
    let result;
    try { result = await ensureCurrentSearchSaved(); }
    catch (error) { toast(`Could not save: ${error.message}`); return; }
    renderRailSubs();
    if (state.view === 'subs') renderSubsPage();
    toast(result.created ? 'Search saved. Email remains off.' : 'This search is already saved.', true);
}

async function startWeeklyForCurrentSearch() {
    if (!state.user) { openAuth('signup'); return; }
    try {
        const { subscription } = await ensureCurrentSearchSaved();
        renderRailSubs();
        openWeeklyAlertDialog(subscription);
    } catch (error) { toast(`Could not prepare alert: ${error.message}`); }
}

function openWeeklyAlertDialog(subscription) {
    const card = $('#alert-card');
    card.innerHTML = `
      <button type="button" class="modal-close" data-close="1" aria-label="Close">${ICON_CLOSE}</button>
      <div class="modal-head">
        <h2 id="alert-dialog-title" class="page-heading">Start weekly emails?</h2>
        <p class="auth-sub">This is separate from saving the search. No email will be sent until you confirm.</p>
      </div>
      <div class="auth-body">
        <dl class="alert-summary">
          <dt>Filters</dt><dd>${escapeHtml(subLabel(subscription))}</dd>
          <dt>Recipient</dt><dd>${escapeHtml(state.user.email || '')}</dd>
          <dt>Frequency</dt><dd>Once a week, on Monday</dd>
        </dl>
        <p class="field-help">These are user-requested service messages. You can stop one alert or all weekly emails at any time.</p>
        <button type="button" class="btn-primary" id="confirm-weekly-alert">Start weekly emails</button>
        <button type="button" class="btn-ghost" data-close="1">Keep saved without email</button>
      </div>`;
    card.querySelectorAll('[data-close]').forEach(button => button.onclick = closeOverlays);
    $('#confirm-weekly-alert').onclick = () => confirmWeeklyAlert(subscription.id);
    openDialog($('#modal-alert'), '#confirm-weekly-alert');
}

async function confirmWeeklyAlert(id) {
    const now = new Date().toISOString();
    const button = $('#confirm-weekly-alert');
    if (button) button.disabled = true;
    const fields = {
        deliver_email: true,
        cadence: 'weekly',
        email_consent_at: now,
        email_consent_version: EMAIL_CONSENT_VERSION,
        unsubscribed_at: null,
        last_processed_at: now,
        last_notified_at: now,
    };
    const { error } = await supabaseClient.from('subscriptions').update(fields).eq('id', id);
    if (error) { if (button) button.disabled = false; toast(`Could not start emails: ${error.message}`); return; }
    const subscription = state.subs.find(item => item.id === id);
    if (subscription) Object.assign(subscription, fields);
    closeOverlays();
    renderRailSubs();
    if (state.view === 'subs') renderSubsPage();
    toast('Weekly emails started.', true);
}

async function pauseWeeklyAlert(id) {
    await updateSub(id, { deliver_email: false, unsubscribed_at: new Date().toISOString() });
    toast('Weekly emails stopped. The search is still saved.', true);
}

async function updateSub(id, fields) {
    const { error } = await supabaseClient.from('subscriptions').update(fields).eq('id', id);
    if (error) { toast(`Update failed: ${error.message}`); return; }
    const s = state.subs.find(x => x.id === id);
    if (s) Object.assign(s, fields);
    renderRailSubs();
    renderSubsPage();
}

async function deleteSub(id) {
    const { error } = await supabaseClient.from('subscriptions').delete().eq('id', id);
    if (error) { toast(`Delete failed: ${error.message}`); return; }
    state.subs = state.subs.filter(x => x.id !== id);
    renderRailSubs();
    renderSubsPage();
    toast('Subscription deleted');
}

function setView(v) {
    state.view = v;
    $('#view-feed').classList.toggle('hidden', v !== 'feed');
    $('#view-subs').classList.toggle('hidden', v !== 'subs');
    $('#view-account').classList.toggle('hidden', v !== 'account');
    $('#view-following').classList.toggle('hidden', v !== 'followlist');
    if (v === 'subs') renderSubsPage();
    if (v === 'account') renderAccountPage();
    if (v === 'followlist') renderFollowingPage();
    setActiveNav();
    const route = v === 'subs' ? 'subscriptions' : v === 'account' ? 'account' : v === 'followlist' ? 'following' : 'feed';
    if (window.location.hash !== `#${route}`) history.replaceState(null, '', `#${route}`);
    window.scrollTo({ top: 0 });
}

function renderSubsPage() {
    const u = state.user;
    const el = $('#view-subs');
    if (!u) { el.innerHTML = ''; return; }
    const cards = state.subs.length ? state.subs.map(s => {
        const tags = [
            ...(s.disciplines || []).map(d => `<span class="b" style="background:${getDisciplineColor(d)}">${escapeHtml(discShort(d))}</span>`),
            ...(s.position_types || []).map(t => `<span class="b b-pos">${escapeHtml(t)}</span>`),
            ...(s.countries || []).map(c => `<span class="b b-country">${escapeHtml(c)}</span>`),
        ].join('') || '<span class="b b-disc-General">all positions</span>';
        const emailOn = Boolean(s.deliver_email && s.email_consent_at);
        return `<div class="sub-card" data-sub="${escapeHtml(s.id)}">
          <div class="sub-card-head">
            <div class="sub-card-q">${escapeHtml(subLabel(s))}</div>
          </div>
          <div class="sub-card-tags">${tags}</div>
          <div class="sub-delivery">
            <span class="del-static">${emailOn ? `Weekly email → <span class="em">${escapeHtml(u.email || '')}</span>` : 'Saved search · email off'}</span>
            ${emailOn
                ? `<button type="button" class="btn-ghost" data-pause-sub="${escapeHtml(s.id)}">Stop weekly emails</button>`
                : `<button type="button" class="btn-primary" data-start-sub="${escapeHtml(s.id)}">Email me weekly</button>`}
            <button type="button" class="sub-delete" data-del-sub="${escapeHtml(s.id)}">Delete search</button>
          </div>
        </div>`;
    }).join('') : `
      <div class="subs-empty">
        <div class="ee">No saved searches yet.</div>
        <button type="button" class="btn-primary" id="subs-empty-add">Save your current search</button>
      </div>`;

    el.innerHTML = `
      <div class="subs-page">
        <div class="subs-hero">
          <h1 class="subs-h1">Saved searches</h1>
          <div class="subs-lead">Saving a search does not subscribe you. Weekly email is optional and starts only after a separate confirmation.</div>
        </div>
        <div>
          <div class="subs-block-title"><span>Saved searches · ${state.subs.length}</span><button type="button" class="more text-button" id="subs-add">Save current search</button></div>
          ${cards}
        </div>
      </div>`;
}

/* ───────────────────────── COOKIE BANNER ───────────────────────── */
async function loadProfile() {
    if (!state.user) { state.profile = null; return; }
    const { data, error } = await supabaseClient.from('profiles').select('*').eq('id', state.user.id).maybeSingle();
    if (error) console.warn('loadProfile failed', error);
    state.profile = data || { id: state.user.id, email: state.user.email || '', display_name: '', handle: '' };
}

function renderAccountPage() {
    const element = $('#view-account');
    if (!state.user) { element.innerHTML = ''; return; }
    const profile = state.profile || {};
    element.innerHTML = `
      <div class="account-page">
        <header>
          <h1 class="page-heading">Account &amp; privacy</h1>
          <p class="page-lead">Correct your profile, export your data, change optional analytics, or permanently delete the account.</p>
        </header>
        <section class="settings-card" aria-labelledby="profile-heading">
          <h2 id="profile-heading">Profile details</h2>
          <div class="field"><label for="account-name">Display name</label><input id="account-name" value="${escapeHtml(profile.display_name || '')}" autocomplete="name"></div>
          <div class="field"><label for="account-handle">Academic handle</label><input id="account-handle" value="${escapeHtml(profile.handle || '')}" autocomplete="username"></div>
          <div class="field"><label for="account-email">Email</label><input id="account-email" type="email" value="${escapeHtml(state.user.email || profile.email || '')}" autocomplete="email"></div>
          <p class="field-help">Changing email may require confirmation at both the old and new addresses.</p>
          <div class="settings-actions"><button type="button" class="btn-primary" id="save-profile">Save corrections</button></div>
          <p class="form-status" id="profile-status" aria-live="polite"></p>
        </section>
        <section class="settings-card" aria-labelledby="data-heading">
          <h2 id="data-heading">Your data</h2>
          <p>Download a JSON copy of your profile, follows, topics, and saved searches. PhD Sky does not sell this data or use it to train AI models.</p>
          <div class="settings-actions">
            <button type="button" class="btn-ghost" id="export-account">Download JSON export</button>
            <button type="button" class="btn-ghost" data-cookie-settings>Cookie settings</button>
          </div>
        </section>
        <section class="settings-card danger-card" aria-labelledby="delete-heading">
          <h2 id="delete-heading">Delete account</h2>
          <p>This permanently deletes the Auth account and cascades to your profile, follows, topics, and saved searches.</p>
          <div class="field"><label for="delete-confirm">Type DELETE to confirm</label><input id="delete-confirm" autocomplete="off" spellcheck="false"></div>
          <div class="settings-actions"><button type="button" class="btn-primary" id="delete-account" disabled>Delete my account permanently</button></div>
          <p class="form-status" id="delete-status" aria-live="polite"></p>
        </section>
      </div>`;
    $('#save-profile').onclick = saveProfile;
    $('#export-account').onclick = exportAccountData;
    const confirmation = $('#delete-confirm');
    confirmation.oninput = () => { $('#delete-account').disabled = confirmation.value !== 'DELETE'; };
    $('#delete-account').onclick = deleteOwnAccount;
    bindCookieSettingsButtons(element);
}

async function saveProfile() {
    const button = $('#save-profile');
    const status = $('#profile-status');
    button.disabled = true;
    status.textContent = 'Saving…';
    const displayName = $('#account-name').value.trim();
    const handle = $('#account-handle').value.trim();
    const email = $('#account-email').value.trim();
    const emailChanged = email && email !== state.user.email;
    try {
        const { error: profileError } = await supabaseClient.from('profiles').update({
            display_name: displayName || null,
            handle: handle || null,
        }).eq('id', state.user.id);
        if (profileError) throw profileError;
        const authChanges = { data: { ...(state.user.user_metadata || {}), full_name: displayName || null } };
        if (emailChanged) authChanges.email = email;
        const { data, error: authError } = await supabaseClient.auth.updateUser(authChanges);
        if (authError) throw authError;
        if (data.user) state.user = data.user;
        await loadProfile();
        renderTopbar();
        status.textContent = emailChanged ? 'Saved. Check your email to confirm the address change.' : 'Profile updated.';
    } catch (error) { status.textContent = `Could not save: ${error.message}`; }
    finally { button.disabled = false; }
}

function exportAccountData() {
    const exportData = {
        exported_at: new Date().toISOString(),
        account: { id: state.user.id, email: state.user.email, created_at: state.user.created_at },
        profile: state.profile,
        saved_searches: state.subs,
        followed_accounts: [...state.follows],
        followed_topics: [...state.topics],
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `phd-sky-account-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast('Account export downloaded.', true);
}

async function deleteOwnAccount() {
    if ($('#delete-confirm').value !== 'DELETE') return;
    const button = $('#delete-account');
    const status = $('#delete-status');
    button.disabled = true;
    status.textContent = 'Deleting account…';
    const { error } = await supabaseClient.rpc('delete_own_account');
    if (error) {
        status.textContent = `Could not delete account: ${error.message}`;
        button.disabled = false;
        return;
    }
    await supabaseClient.auth.signOut({ scope: 'local' });
    state.user = null; state.profile = null; state.subs = [];
    state.follows = new Set(); state.topics = new Set();
    selectStream('all');
    renderTopbar(); renderRailSubs();
    toast('Your account and saved data were deleted.', true);
}

let analyticsLoaded = false;

function loadOptionalAnalytics() {
    if (analyticsLoaded) return;
    analyticsLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {
        ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied', analytics_storage: 'granted',
    });
    window.gtag('js', new Date());
    window.gtag('config', 'G-B81CELELQD', { anonymize_ip: true });
    const google = document.createElement('script');
    google.async = true;
    google.src = 'https://www.googletagmanager.com/gtag/js?id=G-B81CELELQD';
    google.dataset.optionalAnalytics = 'google';
    document.head.appendChild(google);

    window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };
    const vercel = document.createElement('script');
    vercel.defer = true;
    vercel.src = '/_vercel/insights/script.js';
    vercel.dataset.optionalAnalytics = 'vercel';
    document.head.appendChild(vercel);
}

function withdrawOptionalAnalytics() {
    if (typeof window.gtag === 'function') window.gtag('consent', 'update', { analytics_storage: 'denied' });
    document.cookie.split(';').map(value => value.split('=')[0].trim()).filter(name => name.startsWith('_ga')).forEach(name => {
        document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
        document.cookie = `${name}=; Max-Age=0; path=/; domain=.phdsky.org; SameSite=Lax`;
    });
}

function bindCookieSettingsButtons(root = document) {
    root.querySelectorAll('[data-cookie-settings]').forEach(button => {
        button.onclick = () => {
            if (window.CookieConsent) window.CookieConsent.showPreferences();
        };
    });
}

function setupCookieBanner() {
    if (typeof window.CookieConsent === 'undefined') return;
    window.CookieConsent.run({
        cookie: { name: 'phdsky_consent', expiresAfterDays: 182, sameSite: 'Lax' },
        guiOptions: { consentModal: { layout: 'bar', position: 'bottom', equalWeightButtons: true } },
        categories: { necessary: { enabled: true, readOnly: true }, analytics: {} },
        language: {
            default: 'en',
            translations: { en: {
                consentModal: {
                    title: 'Optional visitor statistics',
                    description: 'With your permission, PhD Sky loads Google Analytics and Vercel Analytics to understand aggregate use. There are no ads or profiling. <a href="/privacy">Privacy notice</a>.',
                    acceptAllBtn: 'Allow analytics', acceptNecessaryBtn: 'Necessary only', showPreferencesBtn: 'Choose settings'
                },
                preferencesModal: {
                    title: 'Cookie settings', acceptAllBtn: 'Allow analytics', acceptNecessaryBtn: 'Necessary only', savePreferencesBtn: 'Save settings', closeIconLabel: 'Close',
                    sections: [
                        { title: 'Necessary storage', description: 'Authentication and the phdsky_consent choice are needed for requested features.', linkedCategory: 'necessary' },
                        { title: 'Optional analytics', description: 'Loads Google Analytics and Vercel Analytics only after consent. You can withdraw consent here at any time.', linkedCategory: 'analytics' },
                    ],
                },
            } }
        },
        onConsent: () => window.CookieConsent.acceptedCategory('analytics') ? loadOptionalAnalytics() : withdrawOptionalAnalytics(),
        onChange: () => window.CookieConsent.acceptedCategory('analytics') ? loadOptionalAnalytics() : withdrawOptionalAnalytics(),
    });
    bindCookieSettingsButtons();
    if (new URLSearchParams(window.location.search).get('cookie-settings') === '1') {
        setTimeout(() => window.CookieConsent.showPreferences(), 0);
    }
}

/* ───────────────────────── EVENT WIRING ───────────────────────── */
function selectTab(tab) {                          // 'latest' | 'following' (My feed)
    if (tab === 'following' && !state.user) { openAuth('signup'); return; }
    state.tab = tab;
    state.view = 'feed';
    $('#view-feed').classList.remove('hidden');
    $('#view-subs').classList.add('hidden');
    $('#view-account').classList.add('hidden');
    $('#view-following').classList.add('hidden');
    setActiveNav();
    renderFeedReset();
    if (window.location.hash !== '#feed') history.replaceState(null, '', '#feed');
    window.scrollTo({ top: 0 });
}
function selectStream(stream) {                     // rail / bottom-nav / profile entry
    if (stream === 'saved') {
        if (!state.user) { openAuth('signup'); return; }
        setView('subs');
        return;
    }
    if (stream === 'followlist') {                  // rail "Following" → account list view
        if (!state.user) { openAuth('signup'); return; }
        setView('followlist');
        return;
    }
    selectTab(stream === 'following' ? 'following' : 'latest');
}

function routeFromHash() {
    const route = window.location.hash.replace(/^#/, '');
    if (route === 'subscriptions') {
        if (state.user) setView('subs'); else openAuth('signin');
    } else if (route === 'account') {
        if (state.user) setView('account'); else openAuth('signin');
    } else if (route === 'following') {
        if (state.user) setView('followlist'); else openAuth('signin');
    } else if (route === 'feed') {
        selectStream('all');
    }
}

function wireEvents() {
    $('#backdrop').onclick = closeOverlays;
    $('#flyout-close').onclick = closeOverlays;
    $('#mark').onclick = event => { event.preventDefault(); state.search = ''; $('#cmd-input').value = ''; selectStream('all'); window.scrollTo({ top: 0 }); };
    $('#clear-filters').onclick = clearFilters;

    // command bar / search
    const cmd = $('#cmd-input');
    let searchT;
    cmd.addEventListener('input', () => { clearTimeout(searchT); searchT = setTimeout(() => { state.search = cmd.value; if (state.view === 'feed') renderFeedReset(); }, 180); });
    cmd.addEventListener('keydown', e => {
        if (e.key === 'Escape') { cmd.value = ''; state.search = ''; renderFeedReset(); cmd.blur(); }
        if (e.key === 'Enter') {
            state.search = cmd.value;
            if (state.view !== 'feed') selectStream('all');
            else renderFeedReset();
            toast('Search applied. It has not been saved or subscribed.', true);
        }
    });

    // hide-aggregator chip
    $('#chip-hideaggr').onclick = e => {
        state.hideAggr = !state.hideAggr;
        e.currentTarget.classList.toggle('on', state.hideAggr);
        e.currentTarget.setAttribute('aria-pressed', String(state.hideAggr));
        renderFeedReset();
    };

    // close fixed filter dropdowns on scroll (page or rail) so they don't drift
    const closeDropdowns = () => $$('.chip-dropdown.open').forEach(d => d.classList.remove('open'));
    window.addEventListener('scroll', closeDropdowns);
    const railEl = document.querySelector('.left-rail');
    if (railEl) railEl.addEventListener('scroll', closeDropdowns);

    // streams + tabs
    $$('.rail-link').forEach(l => l.onclick = () => selectStream(l.dataset.stream));
    $$('.river-tab').forEach(t => t.onclick = () => selectTab(t.dataset.tab));

    // mobile: bottom nav + filter sheet
    const rail = $('#left-rail');
    const closeSheet = () => { if (rail) rail.classList.remove('open'); $('#backdrop').classList.remove('open'); };
    const sc = $('#sheet-close'); if (sc) sc.onclick = closeSheet;
    $$('.mnav-btn').forEach(b => b.onclick = () => {
        const a = b.dataset.mnav;
        if (a === 'filters') { if (rail) rail.classList.add('open'); $('#backdrop').classList.add('open'); return; }
        closeSheet();
        selectStream(a);
    });

    // trends (areas + countries) → follow topic, or set the matching filter
    const onTrendClick = e => {
        const tf = e.target.closest('[data-topic]');
        if (tf) { e.stopPropagation(); toggleFollowTopic(tf.dataset.topic, tf.dataset.topicKind || 'discipline'); return; }
        const row = e.target.closest('[data-trend]'); if (!row) return;
        const name = row.dataset.trend;
        const fk = row.dataset.trendKind === 'area' ? 'area' : 'country';
        const chip = document.querySelector(`.chip[data-${fk}="${CSS.escape(name)}"]`);
        if (chip) { if (!chip.classList.contains('on')) chip.click(); }
        else if (!state.filters[fk].has(name)) { state.filters[fk].add(name); renderFeedReset(); }
    };
    $('#activity-trends').addEventListener('click', onTrendClick);
    $('#activity-countries').addEventListener('click', onTrendClick);

    // feed delegation
    $('#feed-stream').addEventListener('click', e => {
        if (e.target.closest('[data-stop]')) return; // let real links work
        const sg = e.target.closest('[data-stream-go]');
        if (sg) { selectStream(sg.dataset.streamGo); return; }
        const tg = e.target.closest('[data-tab-go]');
        if (tg) { selectTab(tg.dataset.tabGo); return; }
        const fol = e.target.closest('[data-follow]');
        if (fol) { e.stopPropagation(); toggleFollowAccount(fol.dataset.follow); return; }
        const tog = e.target.closest('[data-toggle]');
        if (tog) {
            e.stopPropagation();
            const id = tog.dataset.toggle;
            state.threadOpen.has(id) ? state.threadOpen.delete(id) : state.threadOpen.add(id);
            const el = document.querySelector(`[data-thread="${CSS.escape(id)}"]`);
            if (el) el.classList.toggle('open');
            return;
        }
        const detail = e.target.closest('[data-detail]');
        const post = e.target.closest('.post');
        if (detail && post) openFlyout(post.dataset.id);
    });

    // delegated: empty-state clear + close profile menu / filter dropdowns on outside click
    document.addEventListener('click', e => {
        if (e.target.closest('#empty-clear')) { clearFilters(); return; }
        const pm = $('#profile-menu');
        if (pm && pm.classList.contains('open') && !e.target.closest('.profile-wrap')) {
            pm.classList.remove('open');
            const avatar = $('#avatar-btn'); if (avatar) avatar.setAttribute('aria-expanded', 'false');
        }
        const ddOpen = $$('.chip-dropdown.open');
        if (ddOpen.length && !e.target.closest('.chip-dropdown') && !e.target.closest('.chip-more')) {
            ddOpen.forEach(d => d.classList.remove('open'));
        }
    });

    // subscriptions page interactions (delegated)
    $('#view-subs').addEventListener('click', e => {
        if (e.target.closest('#subs-add') || e.target.closest('#subs-empty-add')) { saveCurrentSearch(); return; }
        const start = e.target.closest('[data-start-sub]');
        if (start) { const subscription = state.subs.find(item => item.id === start.dataset.startSub); if (subscription) openWeeklyAlertDialog(subscription); return; }
        const pause = e.target.closest('[data-pause-sub]');
        if (pause) { pauseWeeklyAlert(pause.dataset.pauseSub); return; }
        const dsub = e.target.closest('[data-del-sub]');
        if (dsub) { deleteSub(dsub.dataset.delSub); return; }
    });

    // keyboard
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') { closeOverlays(); return; }
        if (e.key === 'Tab' && activeDialog) {
            const focusable = [...activeDialog.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]')]
                .filter(element => element.offsetParent !== null);
            if (!focusable.length) { e.preventDefault(); activeDialog.focus(); return; }
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); $('#cmd-input').focus(); }
    });

    window.addEventListener('hashchange', routeFromHash);
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

async function setupAuth() {
    if (!authEnabled()) { renderTopbar(); renderRailSubs(); return; }
    try {
        const { data } = await supabaseClient.auth.getSession();
        state.user = data.session ? data.session.user : null;
        if (state.user) { await Promise.all([loadFollows(), loadSubs(), loadProfile()]); }
    } catch (e) { console.warn('auth session load failed', e); }
    renderTopbar();
    renderRailSubs();
    refreshFollowUI();
    routeFromHash();
    supabaseClient.auth.onAuthStateChange(async (_event, session) => {
        const wasUser = !!state.user;
        state.user = session ? session.user : null;
        if (state.user) { await Promise.all([loadFollows(), loadSubs(), loadProfile()]); }
        else {
            state.follows = new Set(); state.topics = new Set(); state.subs = []; state.profile = null;
            if (wasUser) selectStream('all');   // following/subs need auth → back to Latest
        }
        renderTopbar();
        renderRailSubs();
        refreshFollowUI();
        if (state.user) routeFromHash();
    });
}

// Re-render surfaces that depend on follow state.
function refreshFollowUI() {
    updateCounts();
    renderActivity();
    if (state.view === 'followlist') renderFollowingPage();
    if (state.tab === 'following') renderFeedReset();
    else { // refresh per-post follow buttons in place
        $$('[data-follow]').forEach(b => {
            const on = state.follows.has(b.dataset.follow);
            b.classList.toggle('on', on);
            b.setAttribute('aria-pressed', String(on));
            b.textContent = on ? 'Following' : 'Follow';
        });
    }
}

async function init() {
    setupCookieBanner();
    renderTopbar();
    renderRailSubs();
    wireEvents();
    setActiveNav();
    await setupAuth();
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
