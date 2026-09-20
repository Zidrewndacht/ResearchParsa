// static/js/filtering/filtering_init.js
/** Composition root: wires all event handlers on DOMContentLoaded.
 *  Boots the data pipeline: fetch/embed → papersStore → virtualScroll → initial render.
 *  Shared between server-based full page and client-only HTML export. */

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
        applyLocalFilters();
    } else {
        // Fetch from API
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
                applyLocalFilters();
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
}

document.addEventListener('DOMContentLoaded', bootApp);

// Deep-link focus (formerly focus_paper.js)
// Handles /?focus_paper=<id> deep links (opened from the Agreement Report's
// outlier links in a new tab). The URL already carries narrowly-scoped
// server-side filters (the paper's year, hide_offtopic=0, min_page_count=0)
// plus the paper ID as search_query, so the new tab renders fast and shows
// essentially only the target. This script just makes sure the ID search is
// applied, then reveals the row, highlights it briefly, and expands its history.
// ============================================================================
(function () {
    'use strict';
    function findRow(paperId) {
        if (typeof CSS !== 'undefined' && CSS.escape) {
            return document.querySelector('#papersTable tbody tr[data-paper-id="' + CSS.escape(paperId) + '"]');
        }
        return Array.prototype.slice
            .call(document.querySelectorAll('#papersTable tbody tr[data-paper-id]'))
            .find(function (r) { return r.getAttribute('data-paper-id') === paperId; }) || null;
    }
    function highlightAndOpen(row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('focus-highlight');
        setTimeout(function () { row.classList.remove('focus-highlight'); }, 4000);

        // Expand the history row unless already expanded.
        // Row structure: data row -> detail-row -> history-row.
        const detailRow = row.nextElementSibling;
        const historyRow = detailRow ? detailRow.nextElementSibling : null;
        const historyExpanded = historyRow && historyRow.classList.contains('expanded');
        const historyBtn = row.querySelector('.history-btn');
        if (historyBtn && !historyExpanded) historyBtn.click(); // invokes onclick="toggleHistory(this)" — same path as a user click
    }
    document.addEventListener('DOMContentLoaded', function () {
        if (!window.FOCUS_PAPER_ID) return;
        const paperId = String(window.FOCUS_PAPER_ID);
        setTimeout(function () {
            // Ensure the ID search is active (index() prefills the input from search_query).
            const searchEl = document.getElementById('search-input');
            if (searchEl && searchEl.value.trim() !== paperId) searchEl.value = paperId;
            if (typeof applyLocalFilters === 'function') { try { applyLocalFilters(); } catch (e) {} }
            // Wait for render
            setTimeout(function () {
                let row = virtualScroll.ensurePaperVisible(paperId);
                if (!row) row = findRow(paperId);
                if (!row && searchEl) {
                // Fallback: if the search doesn't match IDs in this setup, drop the
                // search and rely on the year-filtered table alone.
                    searchEl.value = '';
                    if (typeof applyLocalFilters === 'function') { try { applyLocalFilters(); } catch (e) {} }
                    setTimeout(function () {
                        row = virtualScroll.ensurePaperVisible(paperId) || findRow(paperId);
                        if (row) highlightAndOpen(row);
                        else { console.warn('[focus_paper] Paper not found: ' + paperId); alert('Paper "' + paperId + '" was not found.'); }
                    }, 300);
                } else if (row) {
                    highlightAndOpen(row);
                }
            }, 300);
        }, 200);
    });
})();