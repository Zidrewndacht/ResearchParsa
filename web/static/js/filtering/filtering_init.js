// static/js/filtering/filtering_init.js
/** Composition root: boots the data pipeline and wires event handlers.
 *  Deep-link (focus_paper) runs AFTER data is loaded — no race condition. */

function bootApp() {
    const isExport = document.body.id === 'html-export';
    tableRenderer.computeTotalCols();
    const scrollContainer = document.querySelector('.table-container');
    virtualScroll.init(scrollContainer, tbody, tableRenderer.getTotalCols());

    if (isExport) {
        // Data is embedded in window.__PARSA_DATA__
        const data = window.__PARSA_DATA__ || [];
        papersStore.load(data);
        initializeClientFilters();
        _wireEvents();
        applyLocalFilters(() => _handleFocusPaper());
    } else {
        // Fetch from API with current server-side filter params
        const params = new URLSearchParams(window.location.search);
        const fetchParams = new URLSearchParams();
        if (params.has('hide_offtopic')) fetchParams.set('hide_offtopic', params.get('hide_offtopic'));
        if (params.has('year_from')) fetchParams.set('year_from', params.get('year_from'));
        if (params.has('year_to')) fetchParams.set('year_to', params.get('year_to'));
        if (params.has('min_page_count')) fetchParams.set('min_page_count', params.get('min_page_count'));

        fetch(`/api/papers?${fetchParams.toString()}`)
            .then(r => r.json())
            .then(data => {
                papersStore.load(data.papers);
                // Set total count in footer
                const totalEl = document.getElementById('total-papers-count');
                if (totalEl) totalEl.textContent = data.total_paper_count;
                const loadedEl = document.getElementById('loaded-papers-count');
                if (loadedEl) loadedEl.textContent = data.loaded_count;

                initializeClientFilters();
                _wireEvents();
                applyLocalFilters(() => _handleFocusPaper());
            })
            .catch(err => {
                console.error('Failed to load papers:', err);
                document.documentElement.classList.remove('busyCursor');
            });
    }
}

function _wireEvents() {
    hideApprovedCheckbox.addEventListener('change', applyLocalFilters);
    document.querySelectorAll('.tri-state-checkbox').forEach(cb => {
        const group = cb.getAttribute('data-filter-group');
        cb.addEventListener('click', () => cycleTriStateFilter(group));
    });
    document.querySelectorAll('.inclusion-checkbox').forEach(cb => {
        const group = cb.getAttribute('data-filter-group');
        cb.addEventListener('change', () => toggleInclusionFilter(group));
    });
    searchInput.addEventListener('input', () => {
        clearTimeout(filterTimeoutId);
        document.documentElement.classList.add('busyCursor');
        if (currentFilterAbortController) currentFilterAbortController.abort();
        currentFilterAbortController = new AbortController();
        filterTimeoutId = setTimeout(() => {
            if (currentFilterAbortController.signal.aborted) return;
            applyLocalFilters();
        }, 150);
    });
    document.getElementById('clear-search-btn').addEventListener('click', function () {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
    });
    headers.forEach(header => header.addEventListener('click', sortTable));
    document.addEventListener('click', function (event) {
        const tabButton = event.target.closest('.history-tab-btn');
        if (tabButton) switchHistoryTab(tabButton);
    });
    document.getElementById('longtable-btn')?.addEventListener('click', copyLatexLongtable);

    // --- Edit lock toggle (server-only; exports are already read-only) ---
    const lockBtn = document.getElementById('edit-lock-btn');
    if (lockBtn) {
        const applyLockState = (locked) => {
            document.body.classList.toggle('edit-locked', locked);
            lockBtn.textContent = locked ? '🔒' : '🔓';
            lockBtn.title = locked
                ? 'Unlock to allow manual edits'
                : 'Lock to prevent accidental manual edits';
        };

        // Default to LOCKED when no preference is stored yet
        const stored = localStorage.getItem('parsa_edit_locked');
        applyLockState(stored === null ? true : stored === '1');

        lockBtn.addEventListener('click', () => {
            const locked = document.body.classList.toggle('edit-locked');
            lockBtn.textContent = locked ? '🔒' : '🔓';
            lockBtn.title = locked
                ? 'Unlock to allow edits'
                : 'Lock to prevent accidental edits';
            localStorage.setItem('parsa_edit_locked', locked ? '1' : '0');
        });
    }
}

// ============================================================================
// Deep-link focus — runs AFTER data is loaded and initial render is complete.
// Sets the paper ID as the search term so it becomes the ONLY visible row,
// then scrolls to it, highlights it, and expands its history.
// ============================================================================
function _handleFocusPaper() {
    if (!window.FOCUS_PAPER_ID) return;
    const paperId = String(window.FOCUS_PAPER_ID);

    searchInput.value = paperId;
    applyLocalFilters(() => {
        let row = virtualScroll.ensurePaperVisible(paperId);
        if (row) {
            _highlightAndOpen(row);
        } else {
            // Fallback: clear search, show all, try again
            searchInput.value = '';
            applyLocalFilters(() => {
                row = virtualScroll.ensurePaperVisible(paperId);
                if (row) {
                    _highlightAndOpen(row);
                } else {
                    console.warn('[focus_paper] Paper not found: ' + paperId);
                    alert('Paper "' + paperId + '" was not found in the database.');
                }
            });
        }
    });
}

function _highlightAndOpen(row) {
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('focus-highlight');
    setTimeout(() => row.classList.remove('focus-highlight'), 4000);

    // Expand history row unless already expanded
    const detailRow = row.nextElementSibling;
    const historyRow = detailRow ? detailRow.nextElementSibling : null;
    const historyExpanded = historyRow && historyRow.classList.contains('expanded');
    const historyBtn = row.querySelector('.history-btn');
    if (historyBtn && !historyExpanded) {
        historyBtn.click();
    }
}

document.addEventListener('DOMContentLoaded', bootApp);