// Mock mode: add ?mock to the URL to load from mock_data.json instead of Supabase
const USE_MOCK = new URLSearchParams(window.location.search).has('mock');

// Supabase configuration
const SUPABASE_URL = 'https://qenpxgztlptegosdhhhi.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_';
const supabaseClient = USE_MOCK ? null : window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// State
let allPositions = [];
let currentFilteredPositions = [];
let gridApi = null;
const expandedCards = new Set();
let searchQuery = '';

// Infinite scroll
const BATCH_SIZE = 30;
let renderedCount = 0;
let scrollObserver = null;

// ─── Utilities ────────────────────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── Data fetching ────────────────────────────────────────────────────────────

async function fetchMockPositions() {
    const response = await fetch('mock_data.json');
    if (!response.ok) throw new Error(`Failed to load mock data: ${response.status}`);
    return response.json();
}

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

async function fetchPositions() {
    if (USE_MOCK) return fetchMockPositions();
    return fetchSupabasePositions();
}

// ─── Card rendering ───────────────────────────────────────────────────────────

function createCard(position, index) {
    const date = position.created_at ? new Date(position.created_at) : null;
    const dateStr = date ? date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';

    const disciplineBadges = (position.disciplines || [])
        .map(d => `<span class="discipline-badge">${escapeHtml(d)}</span>`).join('');
    const typeBadges = (position.position_type || [])
        .map(t => `<span class="position-type-badge">${escapeHtml(t)}</span>`).join('');

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
            if (url.protocol === 'https:' || url.protocol === 'http:') validUrl = position.url;
        } catch { /* invalid */ }
    }

    return `
        <article class="position-card" data-index="${index}">
            <div class="card-header">
                <div class="card-badges">${disciplineBadges}${typeBadges}</div>
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
                ${validUrl
                    ? `<a href="${escapeHtml(validUrl)}" target="_blank" rel="noopener noreferrer" class="card-link-btn">View Post →</a>`
                    : '<span class="text-gray-400 text-sm">No link</span>'}
            </div>
        </article>`;
}

function renderCardsBatch(reset = false) {
    const container = document.getElementById('cards-grid');

    if (reset) {
        renderedCount = 0;
        container.innerHTML = '';
        expandedCards.clear();
    }

    const batch = currentFilteredPositions.slice(renderedCount, renderedCount + BATCH_SIZE);
    if (batch.length === 0) {
        updateCardCount();
        setSentinelVisible(false);
        return;
    }

    container.insertAdjacentHTML('beforeend',
        batch.map((pos, i) => createCard(pos, renderedCount + i)).join('')
    );
    renderedCount += batch.length;

    const hasMore = renderedCount < currentFilteredPositions.length;
    setSentinelVisible(hasMore);
    updateCardCount();
}

function updateCardCount() {
    const shown = renderedCount;
    const filtered = currentFilteredPositions.length;
    const total = allPositions.length;
    const el = document.getElementById('card-count');

    if (filtered === total) {
        el.textContent = shown < total
            ? `Showing ${shown} of ${total} positions`
            : `${total} positions`;
    } else {
        el.textContent = shown < filtered
            ? `Showing ${shown} of ${filtered} (filtered from ${total})`
            : `${filtered} of ${total} positions`;
    }
}

function setSentinelVisible(visible) {
    document.getElementById('scroll-sentinel').style.display = visible ? 'block' : 'none';
}

function setupInfiniteScroll() {
    const sentinel = document.getElementById('scroll-sentinel');
    scrollObserver = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) renderCardsBatch();
    }, { rootMargin: '300px' });
    scrollObserver.observe(sentinel);
}

window.toggleCardMessage = function(index) {
    if (expandedCards.has(index)) expandedCards.delete(index);
    else expandedCards.add(index);

    const msgEl = document.getElementById(`card-msg-${index}`);
    const btn = msgEl.closest('.position-card').querySelector('.card-expand-btn');
    const expanded = expandedCards.has(index);
    msgEl.classList.toggle('truncated', !expanded);
    msgEl.classList.toggle('expanded', expanded);
    btn.textContent = expanded ? '[ show less ]' : '[ read more ]';
};

// ─── Global search ────────────────────────────────────────────────────────────

function setSearchActive(active) {
    document.getElementById('search-bar-container').classList.toggle('has-query', active);
    document.getElementById('btn-search-clear').classList.toggle('hidden', !active);
    if (active) document.getElementById('header-search-container').classList.add('expanded');
}

window.applySearch = function() {
    const input = document.getElementById('global-search');
    searchQuery = input.value.trim().toLowerCase();
    setSearchActive(!!searchQuery);

    const isTableMode = !document.getElementById('table-view').classList.contains('hidden');
    if (isTableMode && gridApi) {
        gridApi.setGridOption('quickFilterText', searchQuery);
        updateTableCount();
    } else {
        applyCardFilters();
    }
};

window.clearSearch = function() {
    document.getElementById('global-search').value = '';
    searchQuery = '';
    setSearchActive(false);

    const isTableMode = !document.getElementById('table-view').classList.contains('hidden');
    if (isTableMode && gridApi) {
        gridApi.setGridOption('quickFilterText', '');
        updateTableCount();
    } else {
        applyCardFilters();
    }
};

// ─── AG Grid (table mode) ─────────────────────────────────────────────────────

function createCheckboxSetFilter(extractValues) {
    return class CheckboxSetFilter {
        init(params) {
            this.params = params;
            this.selectedValues = new Set();
            let values = [...new Set(allPositions.flatMap(p => extractValues(p)))].sort();
            for (const tail of ['Other', 'Unknown']) {
                if (values.includes(tail)) { values = values.filter(v => v !== tail); values.push(tail); }
            }
            this.values = values;
            this.gui = document.createElement('div');
            this.gui.className = 'checkbox-filter-container';
            this.gui.innerHTML = `
                <div style="padding:10px;min-width:200px;">
                    <div style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #334155;">
                        <label style="display:flex;align-items:center;cursor:pointer;">
                            <input type="checkbox" data-select-all="true" checked style="margin-right:8px;">
                            <span style="font-weight:500;">(Select All)</span>
                        </label>
                    </div>
                    <div data-options="true" style="max-height:250px;overflow-y:auto;">
                        ${this.values.map(v => `
                            <label style="display:flex;align-items:center;cursor:pointer;padding:4px 0;">
                                <input type="checkbox" value="${escapeHtml(v)}" checked style="margin-right:8px;">
                                <span>${escapeHtml(v)}</span>
                            </label>`).join('')}
                    </div>
                </div>`;
            this.values.forEach(v => this.selectedValues.add(v));
            const selectAll = this.gui.querySelector('[data-select-all]');
            const opts = this.gui.querySelector('[data-options]');
            selectAll.addEventListener('change', e => {
                opts.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = e.target.checked;
                    e.target.checked ? this.selectedValues.add(cb.value) : this.selectedValues.delete(cb.value);
                });
                this.params.filterChangedCallback();
            });
            opts.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', e => {
                    e.target.checked ? this.selectedValues.add(e.target.value) : this.selectedValues.delete(e.target.value);
                    selectAll.checked = this.selectedValues.size === this.values.length;
                    this.params.filterChangedCallback();
                });
            });
        }
        getGui() { return this.gui; }
        doesFilterPass(params) {
            if (this.selectedValues.size === this.values.length) return true;
            return extractValues(params.data).some(v => this.selectedValues.has(v));
        }
        isFilterActive() { return this.selectedValues.size !== this.values.length; }
        getModel() { return this.isFilterActive() ? { values: [...this.selectedValues] } : null; }
        setModel(model) {
            const selectAll = this.gui.querySelector('[data-select-all]');
            const opts = this.gui.querySelector('[data-options]');
            if (!model) {
                this.selectedValues = new Set(this.values);
                this.gui.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            } else {
                this.selectedValues = new Set(model.values);
                opts.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = this.selectedValues.has(cb.value);
                });
                selectAll.checked = this.selectedValues.size === this.values.length;
            }
        }
    };
}

function renderCollapsibleBadges(params, badgeClass, fieldName) {
    const values = params.value;
    if (!values || !values.length) return '<span class="text-gray-400">\u2014</span>';
    if (values.length === 1) return `<span class="${badgeClass}">${escapeHtml(values[0])}</span>`;
    const cellKey = params.node.id + ':' + fieldName;
    const isExpanded = expandedBadgeCells.has(cellKey);
    if (isExpanded) {
        return `<div class="badge-stack">${values.map(v => `<span class="${badgeClass}">${escapeHtml(v)}</span>`).join('')}<button class="badge-toggle" onclick="toggleBadgeExpand(event,'${cellKey}')">▴ less</button></div>`;
    }
    return `<div class="badge-collapsed"><span class="${badgeClass}">${escapeHtml(values[0])}</span><button class="badge-toggle" onclick="toggleBadgeExpand(event,'${cellKey}')">+${values.length - 1} ▾</button></div>`;
}

const expandedBadgeCells = new Set();
const expandedRows = new Set();

window.toggleBadgeExpand = function(event, cellKey) {
    event.stopPropagation();
    expandedBadgeCells.has(cellKey) ? expandedBadgeCells.delete(cellKey) : expandedBadgeCells.add(cellKey);
    const rowNode = gridApi.getRowNode(cellKey.split(':')[0]);
    if (rowNode) { gridApi.refreshCells({ rowNodes: [rowNode], force: true }); setTimeout(() => gridApi.resetRowHeights(), 10); }
};

window.toggleExpand = function(event, nodeId) {
    event.stopPropagation();
    expandedRows.has(nodeId) ? expandedRows.delete(nodeId) : expandedRows.add(nodeId);
    const rowNode = gridApi.getRowNode(nodeId);
    if (rowNode) { gridApi.refreshCells({ rowNodes: [rowNode], force: true }); setTimeout(() => gridApi.resetRowHeights(), 10); }
};

function getColumnDefs() {
    const DisciplineFilter = createCheckboxSetFilter(p => p.disciplines || []);
    const CountryFilter = createCheckboxSetFilter(p => { const v = p.country; return (v && v !== 'Unknown') ? [v] : ['Unknown']; });
    const PositionTypeFilter = createCheckboxSetFilter(p => p.position_type || []);

    return [
        {
            field: 'created_at', headerName: 'Date', width: 100, sort: 'desc', autoHeight: true,
            cellClass: 'date-cell', filter: 'agDateColumnFilter',
            filterParams: { comparator: (fd, cv) => { const cd = new Date(cv); cd.setHours(0,0,0,0); fd.setHours(0,0,0,0); return cd < fd ? -1 : cd > fd ? 1 : 0; } },
            cellRenderer: p => { if (!p.value) return ''; const d = new Date(p.value); return `<div>${d.toLocaleDateString('en-US',{month:'short',day:'numeric'})}<br>${d.getFullYear()}</div>`; }
        },
        { field: 'disciplines', headerName: 'Discipline', width: 220, filter: DisciplineFilter, autoHeight: true, cellRenderer: p => renderCollapsibleBadges(p, 'discipline-badge', 'disciplines') },
        { field: 'country', headerName: 'Country', width: 110, filter: CountryFilter, cellRenderer: p => (!p.value || p.value === 'Unknown') ? '<span class="text-gray-400">\u2014</span>' : `<span class="country-badge">${escapeHtml(p.value)}</span>` },
        { field: 'position_type', headerName: 'Type', width: 140, filter: PositionTypeFilter, autoHeight: true, cellRenderer: p => renderCollapsibleBadges(p, 'position-type-badge', 'position_type') },
        { field: 'user_handle', headerName: 'Author', width: 150, filter: 'agTextColumnFilter', cellRenderer: p => p.value ? `<a href="https://bsky.app/profile/${p.value}" target="_blank" rel="noopener noreferrer">@${p.value}</a>` : '' },
        { field: 'message', headerName: 'Position', flex: 2, minWidth: 200, filter: 'agTextColumnFilter', cellClass: 'message-cell', autoHeight: true, wrapText: true,
            cellRenderer: p => {
                if (!p.value) return '';
                const max = 150, expanded = expandedRows.has(p.node.id);
                if (p.value.length <= max) return `<div class="py-1">${escapeHtml(p.value)}</div>`;
                const text = expanded ? p.value : p.value.substring(0, max) + '...';
                return `<div class="py-1">${escapeHtml(text)}<button class="expand-btn" onclick="toggleExpand(event,'${p.node.id}')">${expanded ? '[ show less ]' : '[ read more ]'}</button></div>`;
            }
        },
        { field: 'url', headerName: 'Link', width: 110, filter: false, sortable: false,
            cellRenderer: p => {
                if (!p.value) return '';
                try { const u = new URL(p.value); if (u.protocol !== 'https:' && u.protocol !== 'http:') return '<span class="text-gray-400">Invalid URL</span>'; return `<a href="${escapeHtml(p.value)}" target="_blank" rel="noopener noreferrer">View Post</a>`; }
                catch { return '<span class="text-gray-400">Invalid URL</span>'; }
            }
        }
    ];
}

function updateTableCount() {
    if (!gridApi) return;
    const displayed = gridApi.getDisplayedRowCount();
    const total = allPositions.length;
    const el = document.getElementById('card-count');
    el.textContent = displayed === total ? `${total} positions` : `Showing ${displayed} of ${total} positions`;
}

function initGrid() {
    const gridEl = document.getElementById('positions-grid');
    gridApi = agGrid.createGrid(gridEl, {
        columnDefs: getColumnDefs(),
        defaultColDef: { sortable: true, resizable: true, filterParams: { buttons: ['reset', 'apply'], closeOnApply: true } },
        suppressDragLeaveHidesColumns: true,
        rowData: allPositions,
        quickFilterText: searchQuery || undefined,
        animateRows: true,
        pagination: true,
        paginationPageSize: 50,
        paginationPageSizeSelector: [25, 50, 100],
        domLayout: 'normal',
        onFilterChanged: updateTableCount,
        onGridReady: () => setTimeout(updateTableCount, 100),
    });
}

// ─── View switcher ────────────────────────────────────────────────────────────

window.setView = function(mode) {
    localStorage.setItem('preferred-view', mode);
    const cardsView = document.getElementById('cards-view');
    const tableView = document.getElementById('table-view');
    const filterPanel = document.getElementById('filter-panel');
    const btnClear = document.getElementById('btn-clear');
    const btnCards = document.getElementById('btn-cards');
    const btnTable = document.getElementById('btn-table');

    if (mode === 'table') {
        cardsView.classList.add('hidden');
        filterPanel.classList.add('hidden');
        btnClear.classList.add('hidden');
        tableView.classList.remove('hidden');
        btnCards.classList.remove('active');
        btnTable.classList.add('active');
        if (!gridApi) initGrid();
        else {
            gridApi.setGridOption('quickFilterText', searchQuery);
            updateTableCount();
        }
    } else {
        tableView.classList.add('hidden');
        filterPanel.classList.remove('hidden');
        btnClear.classList.remove('hidden');
        cardsView.classList.remove('hidden');
        btnCards.classList.add('active');
        btnTable.classList.remove('active');
        updateCardCount();
    }
};

// ─── Card filters (accordion) ─────────────────────────────────────────────────

const cardFilters = { types: new Set(), countries: new Set(), areas: new Set() };
const filterOptions = { types: [], countries: [], areas: [] };
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
    set.has(value) ? set.delete(value) : set.add(value);
    updateFilterBadge(category);
    applyCardFilters();
};

function updateFilterBadge(category) {
    const badge = document.getElementById(`badge-${category}`);
    const count = cardFilters[category].size;
    badge.textContent = count;
    badge.style.display = count > 0 ? 'inline-flex' : 'none';
}

function buildCheckboxList(containerId, category, values) {
    filterOptions[category] = values;
    document.getElementById(containerId).innerHTML = values.map((v, i) => `
        <label class="filter-option">
            <input type="checkbox" class="filter-checkbox" onchange="toggleCardFilter('${category}',${i})">
            <span>${escapeHtml(v)}</span>
        </label>`).join('');
}

function buildCardFilters(positions) {
    const types = [...new Set(positions.flatMap(p => p.position_type || []))].sort();
    buildCheckboxList('body-types', 'types', types);

    let countries = [...new Set(positions.map(p => p.country).filter(Boolean))].sort();
    countries = countries.filter(c => c !== 'Unknown');
    if (positions.some(p => !p.country || p.country === 'Unknown')) countries.push('Unknown');
    filterOptions.countries = countries;
    buildCheckboxList('country-options', 'countries', countries);

    const areas = [...new Set(positions.flatMap(p => p.disciplines || []))].sort();
    buildCheckboxList('body-areas', 'areas', areas);
}

window.filterCountryOptions = function(query) {
    const q = query.toLowerCase();
    document.getElementById('country-options').innerHTML = filterOptions.countries
        .map((v, i) => ({ v, i }))
        .filter(({ v }) => v.toLowerCase().includes(q))
        .map(({ v, i }) => `
            <label class="filter-option">
                <input type="checkbox" class="filter-checkbox" onchange="toggleCardFilter('countries',${i})" ${cardFilters.countries.has(v) ? 'checked' : ''}>
                <span>${escapeHtml(v)}</span>
            </label>`).join('');
};

function applyCardFilters() {
    let filtered = allPositions;
    if (searchQuery) {
        filtered = filtered.filter(p =>
            (p.message || '').toLowerCase().includes(searchQuery) ||
            (p.user_handle || '').toLowerCase().includes(searchQuery) ||
            (p.country || '').toLowerCase().includes(searchQuery) ||
            (p.disciplines || []).some(d => d.toLowerCase().includes(searchQuery)) ||
            (p.position_type || []).some(t => t.toLowerCase().includes(searchQuery))
        );
    }
    if (cardFilters.types.size > 0) filtered = filtered.filter(p => (p.position_type || []).some(t => cardFilters.types.has(t)));
    if (cardFilters.countries.size > 0) filtered = filtered.filter(p => cardFilters.countries.has(p.country || 'Unknown'));
    if (cardFilters.areas.size > 0) filtered = filtered.filter(p => (p.disciplines || []).some(d => cardFilters.areas.has(d)));
    currentFilteredPositions = filtered;
    renderCardsBatch(true);
}

window.clearCardFilters = function() {
    cardFilters.types.clear(); cardFilters.countries.clear(); cardFilters.areas.clear();
    document.querySelectorAll('.filter-checkbox').forEach(cb => cb.checked = false);
    ['types', 'countries', 'areas'].forEach(cat => updateFilterBadge(cat));
    const cs = document.getElementById('country-filter-search');
    if (cs) cs.value = '';
    currentFilteredPositions = allPositions;
    renderCardsBatch(true);
};

// ─── Init ─────────────────────────────────────────────────────────────────────

async function init() {
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');
    const appContainer = document.getElementById('app-container');

    try {
        const positions = await fetchPositions();
        allPositions = positions;
        currentFilteredPositions = positions;

        loadingEl.classList.add('hidden');
        appContainer.classList.remove('hidden');

        buildCardFilters(positions);
        renderCardsBatch(true);
        setupInfiniteScroll();

        const searchInput = document.getElementById('global-search');
        const searchContainer = document.getElementById('header-search-container');

        searchInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') applySearch();
            if (e.key === 'Escape') { searchInput.blur(); }
        });

        searchInput.addEventListener('focus', () => {
            searchContainer.classList.add('expanded');
        });

        searchInput.addEventListener('blur', () => {
            if (!searchQuery) searchContainer.classList.remove('expanded');
        });

        // Restore preferred view (desktop only)
        const preferred = localStorage.getItem('preferred-view');
        if (preferred === 'table' && window.innerWidth >= 768) setView('table');

    } catch (error) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        console.error('Initialization error:', error);
    }
}

document.addEventListener('DOMContentLoaded', init);
