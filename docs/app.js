// Mock mode: add ?mock to the URL to load from mock_data.json instead of Supabase
const USE_MOCK = new URLSearchParams(window.location.search).has('mock');

// Supabase configuration
// Note: This is the anon (public) key - safe to expose because RLS restricts to read-only
const SUPABASE_URL = 'https://qenpxgztlptegosdhhhi.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_';  // Get from Supabase: Settings → API → anon public

// Initialize Supabase client (skip if mock mode)
const supabaseClient = USE_MOCK ? null : window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Grid API reference
let gridApi;

// Store all positions for filter options
let allPositions = [];

// Track expanded rows
const expandedRows = new Set();

// Track expanded badge cells (keyed by "nodeId:fieldName")
const expandedBadgeCells = new Set();

// Track expanded card messages
const expandedCards = new Set();

// Generic checkbox set filter factory
function createCheckboxSetFilter(fieldName, extractValues) {
    return class CheckboxSetFilter {
        init(params) {
            this.params = params;
            this.selectedValues = new Set();

            // Get unique values from data
            let values = [...new Set(allPositions.flatMap(p => extractValues(p)))].sort();
            // Move "Other" and "Unknown" to end if present
            for (const tail of ['Other', 'Unknown']) {
                if (values.includes(tail)) {
                    values = values.filter(v => v !== tail);
                    values.push(tail);
                }
            }
            this.values = values;

            // Create filter UI
            this.gui = document.createElement('div');
            this.gui.className = 'checkbox-filter-container';
            this.gui.innerHTML = `
                <div style="padding: 10px; min-width: 200px;">
                    <div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #e5e7eb;">
                        <label style="display: flex; align-items: center; cursor: pointer;">
                            <input type="checkbox" data-select-all="true" checked style="margin-right: 8px;">
                            <span style="font-weight: 500;">(Select All)</span>
                        </label>
                    </div>
                    <div data-options="true" style="max-height: 250px; overflow-y: auto;">
                        ${this.values.map(v => `
                            <label style="display: flex; align-items: center; cursor: pointer; padding: 4px 0;">
                                <input type="checkbox" value="${escapeHtml(v)}" checked style="margin-right: 8px;">
                                <span>${escapeHtml(v)}</span>
                            </label>
                        `).join('')}
                    </div>
                </div>
            `;

            // Initialize all as selected
            this.values.forEach(v => this.selectedValues.add(v));

            const selectAll = this.gui.querySelector('[data-select-all]');
            const optionsContainer = this.gui.querySelector('[data-options]');

            // Select All handler
            selectAll.addEventListener('change', (e) => {
                const checkboxes = optionsContainer.querySelectorAll('input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = e.target.checked;
                    if (e.target.checked) {
                        this.selectedValues.add(cb.value);
                    } else {
                        this.selectedValues.delete(cb.value);
                    }
                });
                this.params.filterChangedCallback();
            });

            // Individual checkbox handlers
            optionsContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    if (e.target.checked) {
                        this.selectedValues.add(e.target.value);
                    } else {
                        this.selectedValues.delete(e.target.value);
                    }
                    selectAll.checked = this.selectedValues.size === this.values.length;
                    this.params.filterChangedCallback();
                });
            });
        }

        getGui() {
            return this.gui;
        }

        doesFilterPass(params) {
            if (this.selectedValues.size === this.values.length) {
                return true;
            }
            const cellValues = extractValues(params.data);
            return cellValues.some(v => this.selectedValues.has(v));
        }

        isFilterActive() {
            return this.selectedValues.size !== this.values.length;
        }

        getModel() {
            if (!this.isFilterActive()) {
                return null;
            }
            return { values: Array.from(this.selectedValues) };
        }

        setModel(model) {
            const selectAll = this.gui.querySelector('[data-select-all]');
            const optionsContainer = this.gui.querySelector('[data-options]');
            if (model === null) {
                this.selectedValues = new Set(this.values);
                this.gui.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
            } else {
                this.selectedValues = new Set(model.values);
                optionsContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    cb.checked = this.selectedValues.has(cb.value);
                });
                selectAll.checked = this.selectedValues.size === this.values.length;
            }
        }
    };
}

// Create filter classes from factory
const DisciplineFilter = createCheckboxSetFilter('disciplines', p => p.disciplines || []);
const CountryFilter = createCheckboxSetFilter('country', p => {
    const v = p.country;
    return (v && v !== 'Unknown') ? [v] : ['Unknown'];
});
const PositionTypeFilter = createCheckboxSetFilter('position_type', p => p.position_type || []);

// AG Grid column definitions
const columnDefs = [
    {
        field: 'created_at',
        headerName: 'Date',
        width: 100,
        sort: 'desc',
        autoHeight: true,
        cellClass: 'date-cell',
        filter: 'agDateColumnFilter',
        filterParams: {
            comparator: (filterDate, cellValue) => {
                const cellDate = new Date(cellValue);
                cellDate.setHours(0, 0, 0, 0);
                filterDate.setHours(0, 0, 0, 0);
                if (cellDate < filterDate) return -1;
                if (cellDate > filterDate) return 1;
                return 0;
            }
        },
        cellRenderer: (params) => {
            if (!params.value) return '';
            const date = new Date(params.value);
            const monthDay = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            const year = date.getFullYear();
            return `<div>${monthDay}<br>${year}</div>`;
        }
    },
    {
        field: 'disciplines',
        headerName: 'Discipline',
        width: 220,
        filter: DisciplineFilter,
        autoHeight: true,
        cellRenderer: (params) => renderCollapsibleBadges(params, 'discipline-badge', 'disciplines')
    },
    {
        field: 'country',
        headerName: 'Country',
        width: 110,
        filter: CountryFilter,
        cellRenderer: (params) => {
            if (!params.value || params.value === 'Unknown') return '<span class="text-gray-400">\u2014</span>';
            return `<span class="country-badge">${escapeHtml(params.value)}</span>`;
        }
    },
    {
        field: 'position_type',
        headerName: 'Type',
        width: 140,
        filter: PositionTypeFilter,
        autoHeight: true,
        cellRenderer: (params) => renderCollapsibleBadges(params, 'position-type-badge', 'position_type')
    },
    {
        field: 'user_handle',
        headerName: 'Author',
        width: 150,
        filter: 'agTextColumnFilter',
        cellRenderer: (params) => {
            if (!params.value) return '';
            const profileUrl = `https://bsky.app/profile/${params.value}`;
            return `<a href="${profileUrl}" target="_blank" rel="noopener noreferrer">@${params.value}</a>`;
        }
    },
    {
        field: 'message',
        headerName: 'Position',
        flex: 2,
        minWidth: 200,
        filter: 'agTextColumnFilter',
        cellClass: 'message-cell',
        autoHeight: true,
        wrapText: true,
        cellRenderer: (params) => {
            if (!params.value) return '';
            const maxLength = 150;
            const isTruncated = params.value.length > maxLength;
            const isExpanded = expandedRows.has(params.node.id);

            if (!isTruncated) {
                return `<div class="py-1">${escapeHtml(params.value)}</div>`;
            }

            const text = isExpanded ? params.value : params.value.substring(0, maxLength) + '...';
            const btnText = isExpanded ? '[ show less ]' : '[ read more ]';
            return `<div class="py-1">${escapeHtml(text)}<button class="expand-btn" onclick="toggleExpand(event, '${params.node.id}')">${btnText}</button></div>`;
        }
    },
    {
        field: 'url',
        headerName: 'Link',
        width: 110,
        filter: false,
        sortable: false,
        cellRenderer: (params) => {
            if (!params.value) return '';
            // Validate URL scheme to prevent javascript: injection
            try {
                const url = new URL(params.value);
                if (url.protocol !== 'https:' && url.protocol !== 'http:') {
                    return '<span class="text-gray-400">Invalid URL</span>';
                }
                return `<a href="${escapeHtml(params.value)}" target="_blank" rel="noopener noreferrer">View Post</a>`;
            } catch {
                return '<span class="text-gray-400">Invalid URL</span>';
            }
        }
    }
];

// AG Grid options
const gridOptions = {
    columnDefs: columnDefs,
    defaultColDef: {
        sortable: true,
        resizable: true,
        filterParams: {
            buttons: ['reset', 'apply'],
            closeOnApply: true
        }
    },
    suppressDragLeaveHidesColumns: true,
    rowData: [],
    animateRows: true,
    pagination: true,
    paginationPageSize: 50,
    paginationPageSizeSelector: [25, 50, 100],
    domLayout: 'normal',
    onFilterChanged: updateRowCount,
    onGridReady: (params) => {
        gridApi = params.api;
    }
};

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update the row count display
function updateRowCount() {
    const displayed = gridApi.getDisplayedRowCount();
    const total = gridApi.getModel().getRowCount();
    const countEl = document.getElementById('row-count');

    if (displayed === total) {
        countEl.textContent = `${total} positions`;
    } else {
        countEl.textContent = `Showing ${displayed} of ${total} positions`;
    }
}

// Clear all filters - attached to window for inline onclick
window.clearAllFilters = function() {
    gridApi.setFilterModel(null);
}

// Toggle row expansion - attached to window for inline onclick
window.toggleExpand = function(event, nodeId) {
    event.stopPropagation();

    if (expandedRows.has(nodeId)) {
        expandedRows.delete(nodeId);
    } else {
        expandedRows.add(nodeId);
    }

    // Refresh the row to re-render
    const rowNode = gridApi.getRowNode(nodeId);
    if (rowNode) {
        gridApi.refreshCells({ rowNodes: [rowNode], force: true });
        // Reset row height after content change
        setTimeout(() => gridApi.resetRowHeights(), 10);
    }
}

// Render collapsible badges for array columns
function renderCollapsibleBadges(params, badgeClass, fieldName) {
    const values = params.value;
    if (!values || !values.length) return '<span class="text-gray-400">\u2014</span>';

    if (values.length === 1) {
        return `<span class="${badgeClass}">${escapeHtml(values[0])}</span>`;
    }

    const cellKey = params.node.id + ':' + fieldName;
    const isExpanded = expandedBadgeCells.has(cellKey);

    if (isExpanded) {
        const badges = values
            .map(v => `<span class="${badgeClass}">${escapeHtml(v)}</span>`)
            .join('');
        return `<div class="badge-stack">${badges}<button class="badge-toggle" onclick="toggleBadgeExpand(event, '${cellKey}')">\u25b4 less</button></div>`;
    }

    const first = `<span class="${badgeClass}">${escapeHtml(values[0])}</span>`;
    const remaining = values.length - 1;
    return `<div class="badge-collapsed">${first}<button class="badge-toggle" onclick="toggleBadgeExpand(event, '${cellKey}')">+${remaining} \u25be</button></div>`;
}

// Toggle badge expand/collapse - attached to window for inline onclick
window.toggleBadgeExpand = function(event, cellKey) {
    event.stopPropagation();

    if (expandedBadgeCells.has(cellKey)) {
        expandedBadgeCells.delete(cellKey);
    } else {
        expandedBadgeCells.add(cellKey);
    }

    const nodeId = cellKey.split(':')[0];
    const rowNode = gridApi.getRowNode(nodeId);
    if (rowNode) {
        gridApi.refreshCells({ rowNodes: [rowNode], force: true });
        setTimeout(() => gridApi.resetRowHeights(), 10);
    }
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

    // Validate URL
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

// Render all cards
function renderCards(positions) {
    const container = document.getElementById('cards-list');
    container.innerHTML = positions.map((pos, idx) => createCard(pos, idx)).join('');

    const countEl = document.getElementById('card-count');
    countEl.textContent = `${positions.length} positions`;
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
}

// Filter cards based on search query
function filterCards(query) {
    const q = query.toLowerCase();
    const filtered = allPositions.filter(p =>
        (p.message || '').toLowerCase().includes(q) ||
        (p.user_handle || '').toLowerCase().includes(q) ||
        (p.disciplines || []).some(d => d.toLowerCase().includes(q)) ||
        (p.country || '').toLowerCase().includes(q) ||
        (p.position_type || []).some(t => t.toLowerCase().includes(q))
    );
    renderCards(filtered);
}

// Initialize the application
async function init() {
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');
    const gridContainer = document.getElementById('grid-container');
    const gridEl = document.getElementById('positions-grid');
    const cardsContainer = document.getElementById('cards-container');

    try {
        // Fetch data
        const positions = await fetchPositions();

        // Store for filter component
        allPositions = positions;

        // Hide loading
        loadingEl.classList.add('hidden');

        // Show grid (desktop)
        gridContainer.classList.remove('hidden');

        // Show cards (mobile) - CSS handles visibility based on viewport
        cardsContainer.classList.remove('hidden');
        cardsContainer.classList.add('visible');

        // Create grid for desktop
        agGrid.createGrid(gridEl, {
            ...gridOptions,
            rowData: positions
        });

        // Render cards for mobile
        renderCards(positions);

        // Set up card search
        const searchInput = document.getElementById('card-search');
        searchInput.addEventListener('input', (e) => {
            filterCards(e.target.value);
        });

        // Update count after grid is ready
        setTimeout(updateRowCount, 100);

    } catch (error) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        console.error('Initialization error:', error);
    }
}

// Start the app
document.addEventListener('DOMContentLoaded', init);
