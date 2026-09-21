// static/js/filtering/filtering_engine.js
/** Core filtering, sorting, shading, and row-expansion pipeline.
 *  Operates on papersStore data array. Rendering delegated to virtualScroll.
 *  Shared between server-based full page and client-only HTML export. */

let rafId = 0;
let currentFilterAbortController = null;

function getFilterState() {
    const isExport = document.body.id === 'html-export';
    return {
        searchTerm: searchInput ? searchInput.value.toLowerCase().trim() : '',
        hideApproved: hideApprovedCheckbox.checked,
        triStateStates: { ...triStateFilterStates },
        inclusionStates: { ...inclusionFilterStates },
        hideOfftopic: isExport ? hideOfftopicCheckbox.checked : false,
        minPageCount: isExport ? (parseInt(document.getElementById('min-page-count').value, 10) || 0) : 0,
        yearFrom: isExport ? (parseInt(document.getElementById('year-from').value, 10) || 0) : 0,
        yearTo: isExport ? (parseInt(document.getElementById('year-to').value, 10) || 0) : 0,
        isExport: isExport
    };
}

function applyLocalFilters(onComplete) {
    // Cancel any ongoing filter operation
    if (currentFilterAbortController) currentFilterAbortController.abort();

    // Create a new abort controller for this operation
    currentFilterAbortController = new AbortController();
    const signal = currentFilterAbortController.signal;

    clearTimeout(filterTimeoutId);
    document.documentElement.classList.add('busyCursor');
    cancelAnimationFrame(rafId);

    filterTimeoutId = setTimeout(() => {
        // Check if operation was cancelled
        if (signal.aborted) return;

        const state = getFilterState();
        papersStore.applyFilters(state);

        if (currentClientSort.column) {
            papersStore.applySort(currentClientSort.column, currentClientSort.direction);
        }

        rafId = requestAnimationFrame(() => {
            if (signal.aborted) return;
            virtualScroll.reset();
            virtualScroll.prepareDuplicateData();
            updateUrlWithClientFilters();
            updateCounts();
            restoreDetailState();
            if (document.body.id !== 'html-export') {
                const applyButton = document.getElementById('apply-serverside-filters');
                if (applyButton) { applyButton.style.opacity = '0'; applyButton.style.pointerEvents = 'none'; }
            }
            document.documentElement.classList.remove('busyCursor');
            if (currentFilterAbortController?.signal === signal) currentFilterAbortController = null;
            if (typeof onComplete === 'function') onComplete();   // ← ADD
        });
    }, FILTER_DEBOUNCE_DELAY);
}

function performSort(sortBy, direction) {
    if (!sortBy) return;
    currentClientSort = { column: sortBy, direction: direction };
    papersStore.applySort(sortBy, direction);

    // Update sort indicator
    document.querySelectorAll('th .sort-indicator').forEach(ind => ind.textContent = '');
    const sortHeader = document.querySelector(`th[data-sort="${sortBy}"]`);
    if (sortHeader) {
        const indicator = sortHeader.querySelector('.sort-indicator');
        if (indicator) indicator.textContent = direction === 'ASC' ? '▲' : '▼';
    }

    virtualScroll.reset();
    virtualScroll.prepareDuplicateData();   // ← ADD
    updateUrlWithClientFilters();
    updateCounts();
}

function sortTable() {
    document.documentElement.classList.add('busyCursor');
    // Double requestAnimationFrame ensures the browser paints the loading overlay
    // before we start the blocking sort operation
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            setTimeout(() => {
                const sortBy = this.getAttribute('data-sort');
                if (!sortBy) return;
                let newDirection = 'DESC';
                if (currentClientSort.column === sortBy) {
                    newDirection = currentClientSort.direction === 'DESC' ? 'ASC' : 'DESC';
                }
                performSort(sortBy, newDirection);
                requestAnimationFrame(() => {
                    document.documentElement.classList.remove('busyCursor');
                });
            }, 50);
        });
    });
}

let openDetailIds = new Set();
let openHistoryIds = new Set();
let detailStateUpdateTimeout = null;

function updateUrlWithDetailState() {
    clearTimeout(detailStateUpdateTimeout);
    detailStateUpdateTimeout = setTimeout(() => {
        const url = new URL(window.location);
        const sortedDetailIds = [...openDetailIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS);
        if (sortedDetailIds.length > 0) url.searchParams.set('open_details', sortedDetailIds.join(','));
        else url.searchParams.delete('open_details');
        const sortedHistoryIds = [...openHistoryIds].sort((a, b) => parseInt(a, 10) - parseInt(b, 10)).slice(0, MAX_STORED_OPEN_DETAILS);
        if (sortedHistoryIds.length > 0) url.searchParams.set('open_history', sortedHistoryIds.join(','));
        else url.searchParams.delete('open_history');
        window.history.replaceState({}, '', url);
    }, 100);
}

function restoreDetailState() {
    // Only restore for papers currently rendered in the DOM
    [...openDetailIds].forEach(paperId => {
        const mainRow = tbody.querySelector(`tr[data-paper-id="${paperId}"]`);
        if (mainRow && !mainRow.classList.contains('filter-hidden')) {
            const detailRow = mainRow.nextElementSibling;
            if (detailRow && detailRow.classList.contains('detail-row') && !detailRow.classList.contains('expanded')) {
                const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleDetails"]');
                if (toggleButton) toggleDetails(toggleButton);
            }
        }
    });
    [...openHistoryIds].forEach(paperId => {
        const mainRow = tbody.querySelector(`tr[data-paper-id="${paperId}"]`);
        if (mainRow && !mainRow.classList.contains('filter-hidden')) {
            const historyRow = mainRow.nextElementSibling && mainRow.nextElementSibling.nextElementSibling;
            if (historyRow && historyRow.classList.contains('history-row') && !historyRow.classList.contains('expanded')) {
                const toggleButton = mainRow.querySelector('.toggle-btn[onclick*="toggleHistory"]');
                if (toggleButton) toggleHistory(toggleButton);
            }
        }
    });
}

/**
 * Switches between history tabs (Main, Set 1, Set 2, Set 3)
 * Pure client-side - no server communication needed
 * @param {HTMLElement} tabButton - The clicked tab button element
 */
function switchHistoryTab(tabButton) {
    const paperId = tabButton.getAttribute('data-paper-id');
    const selectedTab = tabButton.getAttribute('data-tab');
    const historyRow = tabButton.closest('.history-flex-container');

    if (!historyRow) {
        console.error(`History container not found for paper ${paperId}`);
        return;
    }

    // Remove active class from all tabs
    historyRow.querySelectorAll('.history-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });

    // Remove active class from all tab panels
    historyRow.querySelectorAll('.history-tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    // Add active class to selected tab
    tabButton.classList.add('active');

    // Add active class to selected tab panel using data attributes
    const selectedPanel = historyRow.querySelector(`.history-tab-panel[data-tab-panel="${selectedTab}"][data-paper-id="${paperId}"]`);
    if (selectedPanel) {
        selectedPanel.classList.add('active');
    }
}