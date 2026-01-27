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

// Custom Discipline Filter Component
class DisciplineFilter {
    init(params) {
        this.params = params;
        this.selectedValues = new Set();

        // Get unique disciplines from data (flatMap for array field), with "Other" at end
        let disciplines = [...new Set(allPositions.flatMap(p => p.disciplines || []))].sort();
        if (disciplines.includes('Other')) {
            disciplines = disciplines.filter(d => d !== 'Other');
            disciplines.push('Other');
        }
        this.disciplines = disciplines;

        // Create filter UI
        this.gui = document.createElement('div');
        this.gui.className = 'discipline-filter-container';
        this.gui.innerHTML = `
            <div style="padding: 10px; min-width: 200px;">
                <div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #e5e7eb;">
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="checkbox" id="select-all" checked style="margin-right: 8px;">
                        <span style="font-weight: 500;">(Select All)</span>
                    </label>
                </div>
                <div id="discipline-options" style="max-height: 250px; overflow-y: auto;">
                    ${this.disciplines.map(d => `
                        <label style="display: flex; align-items: center; cursor: pointer; padding: 4px 0;">
                            <input type="checkbox" value="${d}" checked style="margin-right: 8px;">
                            <span>${d}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `;

        // Initialize all as selected
        this.disciplines.forEach(d => this.selectedValues.add(d));

        // Add event listeners
        this.gui.querySelector('#select-all').addEventListener('change', (e) => {
            const checkboxes = this.gui.querySelectorAll('#discipline-options input[type="checkbox"]');
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

        this.gui.querySelectorAll('#discipline-options input[type="checkbox"]').forEach(cb => {
            cb.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.selectedValues.add(e.target.value);
                } else {
                    this.selectedValues.delete(e.target.value);
                }
                // Update "Select All" checkbox
                const allChecked = this.selectedValues.size === this.disciplines.length;
                this.gui.querySelector('#select-all').checked = allChecked;
                this.params.filterChangedCallback();
            });
        });
    }

    getGui() {
        return this.gui;
    }

    doesFilterPass(params) {
        // If all selected, pass everything
        if (this.selectedValues.size === this.disciplines.length) {
            return true;
        }
        const disciplines = params.data.disciplines || [];
        return disciplines.some(d => this.selectedValues.has(d));
    }

    isFilterActive() {
        return this.selectedValues.size !== this.disciplines.length;
    }

    getModel() {
        if (!this.isFilterActive()) {
            return null;
        }
        return { values: Array.from(this.selectedValues) };
    }

    setModel(model) {
        if (model === null) {
            // Reset to all selected
            this.selectedValues = new Set(this.disciplines);
            this.gui.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
        } else {
            this.selectedValues = new Set(model.values);
            this.gui.querySelectorAll('#discipline-options input[type="checkbox"]').forEach(cb => {
                cb.checked = this.selectedValues.has(cb.value);
            });
            this.gui.querySelector('#select-all').checked = this.selectedValues.size === this.disciplines.length;
        }
    }
}

// AG Grid column definitions
const columnDefs = [
    {
        field: 'created_at',
        headerName: 'Date',
        width: 140,
        sort: 'desc',
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
        valueFormatter: (params) => {
            if (!params.value) return '';
            const date = new Date(params.value);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        }
    },
    {
        field: 'disciplines',
        headerName: 'Discipline',
        width: 220,
        filter: DisciplineFilter,
        cellRenderer: (params) => {
            if (!params.value?.length) return '<span class="text-gray-400">—</span>';
            return params.value
                .map(d => `<span class="discipline-badge">${escapeHtml(d)}</span>`)
                .join(' ');
        }
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
        minWidth: 300,
        filter: 'agTextColumnFilter',
        cellClass: 'message-cell',
        autoHeight: true,
        wrapText: true,
        cellRenderer: (params) => {
            if (!params.value) return '';
            const maxLength = 300;
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
        minWidth: 100,
        maxWidth: 150,
        flex: 0.5,
        filter: false,
        sortable: false,
        cellRenderer: (params) => {
            if (!params.value) return '';
            return `<a href="${params.value}" target="_blank" rel="noopener noreferrer">View Post</a>`;
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
        .select('created_at, disciplines, user_handle, message, url')
        .eq('is_verified_job', true)
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

// Initialize the application
async function init() {
    const loadingEl = document.getElementById('loading');
    const errorEl = document.getElementById('error');
    const gridContainer = document.getElementById('grid-container');
    const gridEl = document.getElementById('positions-grid');

    try {
        // Fetch data
        const positions = await fetchPositions();

        // Store for filter component
        allPositions = positions;

        // Hide loading, show grid
        loadingEl.classList.add('hidden');
        gridContainer.classList.remove('hidden');

        // Create grid
        agGrid.createGrid(gridEl, {
            ...gridOptions,
            rowData: positions
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
