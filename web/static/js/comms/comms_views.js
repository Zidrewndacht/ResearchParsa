// static/js/comms_views.js
/**
 * Server reads & navigation: row expansion (detail/history),
 * server-side filtering, and keyboard shortcuts for filters.
 */
// --- DOM Element References (Server Filters) ---
const minPageCountInput = document.getElementById('min-page-count');
const yearFromInput = document.getElementById('year-from');
const yearToInput = document.getElementById('year-to');
const applyButton = document.getElementById('apply-serverside-filters');

function showApplyButton() { applyButton.style.opacity = '1'; applyButton.style.pointerEvents = 'visible'; }

function handleEnterKey(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        applyServerSideFilters();
    }
}

/**
 * Toggles the visibility of the history row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 * @param {boolean} instant - true when reopened automatically by the virtual
 *                            scroller; skips the open animation.
 */
function toggleHistory(element, instant = false) {
    const row = element.closest('tr'); // Main paper row
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
        row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
        row.nextElementSibling.nextElementSibling : null;
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
        row.nextElementSibling : null;
    const isHistoryExpanded = historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');
    if (isHistoryExpanded) {
        // Hiding the history row (only reachable via a user click)
        historyRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        // Showing the history row
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            detailToggleBtn.classList.remove('toggle-pressed');
            openDetailIds.delete(paperId);
        }
        openHistoryIds.add(paperId);
        updateUrlWithDetailState();
        const contentPlaceholder = historyRow.querySelector('.detail-content-placeholder');
        fetch(`/get_history_row?paper_id=${encodeURIComponent(paperId)}`)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success' && data.html) {
                    contentPlaceholder.innerHTML = data.html;
                    if (instant) {
                        // Automatic restore (virtual scroller): appear already-open, no animation.
                        _expandInstantly(historyRow);
                    } else {
                        // User click: animate the expansion.
                        requestAnimationFrame(() => {
                            historyRow.offsetHeight;
                            historyRow.classList.add('expanded');
                        });
                    }
                    element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                    element.classList.add('toggle-pressed');
                } else {
                    console.error(`Error loading history row for paper ${paperId}:`, data.message);
                    contentPlaceholder.innerHTML = `<p>Error loading history: ${data.message || 'Unknown error'}</p>`;
                }
            })
            .catch(error => {
                console.error(`Error fetching history row for paper ${paperId}:`, error);
                contentPlaceholder.innerHTML = `<p>Error loading history: ${error.message}</p>`;
            });
    }
}

/**
 * Toggles the visibility of the detail row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 * @param {boolean} instant - true when reopened automatically by the virtual
 *                            scroller; skips the open animation.
 */
function toggleDetails(element, instant = false) {
    const row = element.closest('tr'); // Main paper row
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
        row.nextElementSibling : null;
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
        row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
        row.nextElementSibling.nextElementSibling : null;
    const isExpanded = detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');
    if (isExpanded) {
        // Hiding the detail row (only reachable via a user click)
        detailRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        openDetailIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        // Showing the detail row
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            historyToggleBtn.classList.remove('toggle-pressed');
            openHistoryIds.delete(paperId);
        }
        openDetailIds.add(paperId);
        updateUrlWithDetailState();
        const contentPlaceholder = detailRow.querySelector('.detail-content-placeholder');
        fetch(`/get_detail_row?paper_id=${encodeURIComponent(paperId)}`)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success' && data.html) {
                    contentPlaceholder.innerHTML = data.html;
                    // --- Event Delegation for Clickable Items (Authors/Keywords) ---
                    const detailContainer = contentPlaceholder;
                    detailContainer.addEventListener('click', function (event) {
                        if (event.target.classList.contains('clickable-item')) {
                            event.preventDefault();
                            const searchTerm = event.target.getAttribute('data-search-term');
                            if (searchTerm) {
                                searchInput.value = searchTerm.trim();
                                applyLocalFilters();
                            }
                        }
                    });
                    // --- End Event Delegation Setup ---
                    if (instant) {
                        // Automatic restore (virtual scroller): appear already-open, no animation.
                        _expandInstantly(detailRow);
                    } else {
                        // User click: animate the expansion.
                        requestAnimationFrame(() => {
                            detailRow.offsetHeight; // Trigger reflow
                            detailRow.classList.add('expanded');
                        });
                    }
                    element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                    element.classList.add('toggle-pressed');
                } else {
                    console.error(`Error loading detail row for paper ${paperId}:`, data.message);
                    if (contentPlaceholder) {
                        contentPlaceholder.innerHTML = `<p>Error loading details: ${data.message || 'Unknown error'}</p>`;
                    }
                }
            })
            .catch(error => {
                console.error(`Error fetching detail row for paper ${paperId}:`, error);
                if (contentPlaceholder) {
                    contentPlaceholder.innerHTML = `<p>Error loading details: ${error.message}</p>`;
                }
            });
    }
}

function _wireClickableItems(container) {
    container.addEventListener('click', function (event) {
        if (event.target.classList.contains('clickable-item')) {
            event.preventDefault();
            const searchTerm = event.target.getAttribute('data-search-term');
            if (searchTerm) {
                searchInput.value = searchTerm.trim();
                applyLocalFilters();
            }
        }
    });
}

function applyServerSideFilters() {
    document.documentElement.classList.add('busyCursor');
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('hide_offtopic', hideOfftopicCheckbox.checked ? '1' : '0');
    const yf = document.getElementById('year-from').value.trim();
    if (yf !== '' && !isNaN(parseInt(yf))) urlParams.set('year_from', yf); else urlParams.delete('year_from');
    const yt = document.getElementById('year-to').value.trim();
    if (yt !== '' && !isNaN(parseInt(yt))) urlParams.set('year_to', yt); else urlParams.delete('year_to');
    const mpc = document.getElementById('min-page-count').value.trim();
    if (mpc !== '' && !isNaN(parseInt(mpc))) urlParams.set('min_page_count', mpc); else urlParams.delete('min_page_count');

    const fetchUrl = `/api/papers?${urlParams.toString()}`;
    fetch(fetchUrl)
        .then(r => r.json())
        .then(data => {
            papersStore.load(data.papers);
            const totalEl = document.getElementById('total-papers-count');
            if (totalEl) totalEl.textContent = data.total_paper_count;
            const loadedEl = document.getElementById('loaded-papers-count');
            if (loadedEl) loadedEl.textContent = data.loaded_count;

            const newUrl = `${window.location.pathname}?${urlParams.toString()}`;
            window.history.replaceState({ path: newUrl }, '', newUrl);
            applyLocalFilters(); //update local filters and let it remove busy state
        })
        .catch(error => {
            console.error('Error fetching papers:', error);
            document.documentElement.classList.remove('busyCursor');
        });
}

// ============================================================================
// DOMContentLoaded — Views / Filters wiring
// ============================================================================
document.addEventListener('DOMContentLoaded', function () {
    if (document.body.id === 'html-export') return; // No server filters in export
    yearFromInput.addEventListener('change', showApplyButton);
    yearToInput.addEventListener('change', showApplyButton);
    minPageCountInput.addEventListener('change', showApplyButton);
    hideOfftopicCheckbox.addEventListener('change', applyServerSideFilters);
    applyButton.addEventListener('click', applyServerSideFilters);
    // --- Enter Key Handlers for Server-Side Filters ---
    if (yearFromInput) yearFromInput.addEventListener('keydown', handleEnterKey);
    if (yearToInput) yearToInput.addEventListener('keydown', handleEnterKey);
    if (minPageCountInput) minPageCountInput.addEventListener('keydown', handleEnterKey);
});