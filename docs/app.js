// Supabase configuration
// Note: This is the anon (public) key - safe to expose because RLS restricts to read-only
const SUPABASE_URL = 'https://qenpxgztlptegosdhhhi.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_';  // Get from Supabase: Settings → API → anon public

// Initialize Supabase client
const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Grid API reference
let gridApi;

// AG Grid column definitions
const columnDefs = [
    {
        field: 'created_at',
        headerName: 'Date',
        width: 120,
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
        field: 'discipline',
        headerName: 'Discipline',
        width: 150,
        filter: 'agSetColumnFilter',
        cellRenderer: (params) => {
            if (!params.value) return '<span class="text-gray-400">—</span>';
            return `<span class="discipline-badge">${params.value}</span>`;
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
            // Truncate long messages
            const maxLength = 300;
            const text = params.value.length > maxLength
                ? params.value.substring(0, maxLength) + '...'
                : params.value;
            return `<div class="py-1">${escapeHtml(text)}</div>`;
        }
    },
    {
        field: 'url',
        headerName: 'Link',
        width: 100,
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

// Fetch data from Supabase
async function fetchPositions() {
    try {
        const { data, error } = await supabaseClient
            .from('phd_positions')
            .select('created_at, discipline, message, url')
            .order('created_at', { ascending: false });

        if (error) throw error;
        return data;
    } catch (error) {
        console.error('Error fetching positions:', error);
        throw error;
    }
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
