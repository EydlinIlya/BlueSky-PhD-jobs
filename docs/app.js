// Mock mode: add ?mock to the URL to load from mock_data.json instead of Supabase
const USE_MOCK = new URLSearchParams(window.location.search).has('mock');

// Supabase configuration
// Note: This is the anon (public) key - safe to expose because RLS restricts to read-only
const SUPABASE_URL = 'https://qenpxgztlptegosdhhhi.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_';

// Initialize Supabase client (skip if mock mode)
const supabaseClient = USE_MOCK ? null : window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Store all positions for filter options
let allPositions = [];

// Track expanded card messages
const expandedCards = new Set();

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Fetch data from mock JSON file
async function fetchMockPositions() {
    const response = await fetch('mock_data.json');
    if (!response.ok) throw new Error(`Failed to load mock data: ${response.status}`);
    return response.json();
}

// Fetch data from Supabase
async function fetchSupabasePositions() {
    const { data, error } = await supabaseClient
        .from('phd_positions')
        .select('created_at, disciplines, country, position_type, user_handle, message, url, indexed_at')
        .eq('is_verified_job', true)
        .gte('indexed_at', '2026-01-27')
        .order('created_at', { ascending: false });

    if (error) throw error;
    return data;
}

// Fetch positions from the active data source
async function fetchPositions() {
    if (USE_MOCK) {
        console.log('Loading mock data...');
        return fetchMockPositions();
    }
    return fetchSupabasePositions();
}

// Create HTML for a single position card
function createCard(position, index) {
    const date = position.created_at ? new Date(position.created_at) : null;
    const dateStr = date ? date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';

    const disciplines = position.disciplines || [];
    const disciplineBadges = disciplines.map(d =>
        `<span class="discipline-badge">${escapeHtml(d)}</span>`
    ).join('');

    const positionTypes = position.position_type || [];
    const typeBadges = positionTypes.map(t =>
        `<span class="position-type-badge">${escapeHtml(t)}</span>`
    ).join('');

    const country = position.country && position.country !== 'Unknown' ? position.country : null;
    const profileUrl = position.user_handle ? `https://bsky.app/profile/${position.user_handle}` : '#';

    const message = position.message || '';
    const isTruncated = message.length > 200;
    const isExpanded = expandedCards.has(index);
    const messageClass = isTruncated && !isExpanded ? 'card-message truncated' : 'card-message expanded';

    let validUrl = null;
    if (position.url) {
        try {
            const url = new URL(position.url);
            if (url.protocol === 'https:' || url.protocol === 'http:') {
                validUrl = position.url;
            }
        } catch {
            // Invalid URL
        }
    }

    return `
        <article class="position-card" data-index="${index}">
            <div class="card-header">
                <div class="card-badges">
                    ${disciplineBadges}
                    ${typeBadges}
                </div>
                ${dateStr ? `<span class="card-date">📅 ${dateStr}</span>` : ''}
            </div>

            <div class="card-meta">
                ${country ? `<span class="card-meta-item">🌍 ${escapeHtml(country)}</span>` : ''}
            </div>

            <div class="card-author">
                <a href="${escapeHtml(profileUrl)}" target="_blank" rel="noopener noreferrer">@${escapeHtml(position.user_handle || '')}</a>
            </div>

            <div class="${messageClass}" id="card-msg-${index}">${escapeHtml(message)}</div>
            ${isTruncated ? `<button class="card-expand-btn" onclick="toggleCardMessage(${index})">${isExpanded ? '[ show less ]' : '[ read more ]'}</button>` : ''}

            <div class="card-actions">
                ${validUrl ? `<a href="${escapeHtml(validUrl)}" target="_blank" rel="noopener noreferrer" class="card-link-btn">View Post →</a>` : '<span class="text-gray-400 text-sm">No link</span>'}
            </div>
        </article>
    `;
}

// Render all cards into the responsive grid
function renderCards(positions) {
    const container = document.getElementById('cards-grid');
    container.innerHTML = positions.map((pos, idx) => createCard(pos, idx)).join('');

    const countEl = document.getElementById('card-count');
    if (positions.length === allPositions.length) {
        countEl.textContent = `${allPositions.length} positions`;
    } else {
        countEl.textContent = `Showing ${positions.length} of ${allPositions.length} positions`;
    }
}

// Toggle card message expansion - attached to window for inline onclick
window.toggleCardMessage = function(index) {
    if (expandedCards.has(index)) {
        expandedCards.delete(index);
    } else {
        expandedCards.add(index);
    }

    const msgEl = document.getElementById(`card-msg-${index}`);
    const card = msgEl.closest('.position-card');
    const btn = card.querySelector('.card-expand-btn');

    if (expandedCards.has(index)) {
        msgEl.classList.remove('truncated');
        msgEl.classList.add('expanded');
        btn.textContent = '[ show less ]';
    } else {
        msgEl.classList.add('truncated');
        msgEl.classList.remove('expanded');
        btn.textContent = '[ read more ]';
    }
};

// Card filter state — empty set means "all" (no restriction)
const cardFilters = {
    types: new Set(),
    countries: new Set(),
    areas: new Set(),
};

// Stored option arrays for index-based lookup (avoids escaping issues in onclick)
const filterOptions = { types: [], countries: [], areas: [] };

// Track which accordion sections are open
const openSections = new Set();

window.toggleFilterSection = function(sectionId) {
    const body = document.getElementById(`body-${sectionId}`);
    const chevron = document.getElementById(`chevron-${sectionId}`);
    if (openSections.has(sectionId)) {
        openSections.delete(sectionId);
        body.classList.remove('open');
        chevron.textContent = '▶';
    } else {
        openSections.add(sectionId);
        body.classList.add('open');
        chevron.textContent = '▼';
    }
};

window.toggleCardFilter = function(category, index) {
    const value = filterOptions[category][index];
    const set = cardFilters[category];
    if (set.has(value)) {
        set.delete(value);
    } else {
        set.add(value);
    }
    updateFilterBadge(category);
    applyCardFilters();
};

function updateFilterBadge(category) {
    const badge = document.getElementById(`badge-${category}`);
    const count = cardFilters[category].size;
    if (count > 0) {
        badge.textContent = count;
        badge.style.display = 'inline-flex';
    } else {
        badge.style.display = 'none';
    }
}

function buildCheckboxList(containerId, category, values) {
    filterOptions[category] = values;
    const container = document.getElementById(containerId);
    container.innerHTML = values.map((v, i) => `
        <label class="filter-option">
            <input type="checkbox" class="filter-checkbox"
                   onchange="toggleCardFilter('${category}', ${i})">
            <span>${escapeHtml(v)}</span>
        </label>
    `).join('');
}

function buildCardFilters(positions) {
    // Level (position_type)
    const types = [...new Set(positions.flatMap(p => p.position_type || []))].sort();
    buildCheckboxList('body-types', 'types', types);

    // Country — sort alphabetically, Unknown at end
    let countries = [...new Set(positions.map(p => p.country).filter(Boolean))].sort();
    countries = countries.filter(c => c !== 'Unknown');
    if (positions.some(p => !p.country || p.country === 'Unknown')) {
        countries.push('Unknown');
    }
    filterOptions.countries = countries;
    buildCheckboxList('country-options', 'countries', countries);

    // Area (disciplines)
    const areas = [...new Set(positions.flatMap(p => p.disciplines || []))].sort();
    buildCheckboxList('body-areas', 'areas', areas);
}

window.filterCountryOptions = function(query) {
    const q = query.toLowerCase();
    const all = filterOptions.countries;
    const container = document.getElementById('country-options');
    container.innerHTML = all
        .map((v, i) => ({ v, i }))
        .filter(({ v }) => v.toLowerCase().includes(q))
        .map(({ v, i }) => `
            <label class="filter-option">
                <input type="checkbox" class="filter-checkbox"
                       onchange="toggleCardFilter('countries', ${i})"
                       ${cardFilters.countries.has(v) ? 'checked' : ''}>
                <span>${escapeHtml(v)}</span>
            </label>
        `).join('');
};

function applyCardFilters() {
    let filtered = allPositions;

    if (cardFilters.types.size > 0) {
        filtered = filtered.filter(p =>
            (p.position_type || []).some(t => cardFilters.types.has(t))
        );
    }
    if (cardFilters.countries.size > 0) {
        filtered = filtered.filter(p =>
            cardFilters.countries.has(p.country || 'Unknown')
        );
    }
    if (cardFilters.areas.size > 0) {
        filtered = filtered.filter(p =>
            (p.disciplines || []).some(d => cardFilters.areas.has(d))
        );
    }

    renderCards(filtered);
}

window.clearCardFilters = function() {
    cardFilters.types.clear();
    cardFilters.countries.clear();
    cardFilters.areas.clear();

    document.querySelectorAll('.filter-checkbox').forEach(cb => cb.checked = false);
    ['types', 'countries', 'areas'].forEach(cat => updateFilterBadge(cat));

    const countrySearch = document.getElementById('country-filter-search');
    if (countrySearch) countrySearch.value = '';

    renderCards(allPositions);
};

// Initialize the application
async function init() {
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');
    const appContainer = document.getElementById('app-container');

    try {
        const positions = await fetchPositions();
        allPositions = positions;

        loadingEl.classList.add('hidden');
        appContainer.classList.remove('hidden');

        buildCardFilters(positions);
        renderCards(positions);

    } catch (error) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        console.error('Initialization error:', error);
    }
}

// Start the app
document.addEventListener('DOMContentLoaded', init);
