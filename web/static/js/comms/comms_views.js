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
 */
function toggleHistory(element) {
    const row = element.closest('tr'); // Main paper row
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
        row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
        row.nextElementSibling.nextElementSibling : null;
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
        row.nextElementSibling : null;
    if (!historyRow) return;
    const isHistoryExpanded = historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isHistoryExpanded) {
        historyRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');  // Remove pressed state from THIS button
        openHistoryIds.delete(paperId);
        updateUrlWithDetailState();
    } else {
        // Showing the history row
        // First, check if the detail row is open for the same paper, close it if necessary
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            detailToggleBtn.classList.remove('toggle-pressed');  // FIX: Remove from detailToggleBtn, not element
            openDetailIds.delete(paperId);
        }

        openHistoryIds.add(paperId);
        updateUrlWithDetailState();

        const contentPlaceholder = historyRow.querySelector('.detail-content-placeholder');

        if (document.body.id === 'html-export') {
            // Render from embedded data
            const paper = papersStore.getPaperById(paperId);
            if (paper && typeof exportRenderers !== 'undefined') {
                contentPlaceholder.innerHTML = exportRenderers.renderHistoryContent(paper);
                requestAnimationFrame(() => { historyRow.offsetHeight; historyRow.classList.add('expanded'); });
                element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                element.classList.add('toggle-pressed');
            }
        } else {
            fetch(`/get_history_row?paper_id=${encodeURIComponent(paperId)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success' && data.html) {
                        contentPlaceholder.innerHTML = data.html;
                        requestAnimationFrame(() => { historyRow.offsetHeight; historyRow.classList.add('expanded'); });
                        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                        element.classList.add('toggle-pressed');
                    } else {
                        contentPlaceholder.innerHTML = `<p>Error loading history: ${data.message || 'Unknown error'}</p>`;
                    }
                })
                .catch(error => { contentPlaceholder.innerHTML = `<p>Error loading history: ${error.message}</p>`; });
        }
    }
}

/**
 * Toggles the visibility of the detail row for a given paper.
 * @param {HTMLElement} element - The button element clicked to trigger the toggle.
 */
function toggleDetails(element) {
    const row = element.closest('tr'); // Main paper row
    // The detail row is the first sibling after the main row
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ?
        row.nextElementSibling : null;
    // The history row is the second sibling after the main row (detail row is the first)
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling &&
        row.nextElementSibling.nextElementSibling.classList.contains('history-row') ?
        row.nextElementSibling.nextElementSibling : null;

    const isExpanded = detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        // Hiding the detail row
        detailRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');  // Remove pressed state
        openDetailIds.delete(paperId); // Remove from set
        updateUrlWithDetailState(); // Update URL
    } else {
        // Showing the detail row
        // First, check if the history row is open for the same paper, close it if necessary
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            // Find the corresponding history toggle button in the main row and update its text
            // The history button is in the main row itself
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
            historyToggleBtn.classList.remove('toggle-pressed');  // Remove pressed state
            openHistoryIds.delete(paperId); // Remove history ID from set
        }

        // Now proceed to show the detail row
        openDetailIds.add(paperId); // Add ID to set
        updateUrlWithDetailState(); // Update URL immediately

        const contentPlaceholder = detailRow.querySelector('.detail-content-placeholder');

        if (document.body.id === 'html-export') {
            const paper = papersStore.getPaperById(paperId);
            if (paper && typeof exportRenderers !== 'undefined') {
                contentPlaceholder.innerHTML = exportRenderers.renderDetailContent(paper);
                _wireClickableItems(contentPlaceholder);
                requestAnimationFrame(() => { detailRow.offsetHeight; detailRow.classList.add('expanded'); });
                element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                element.classList.add('toggle-pressed');
            }
        } else {
            fetch(`/get_detail_row?paper_id=${encodeURIComponent(paperId)}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success' && data.html) {
                        contentPlaceholder.innerHTML = data.html;
                        _wireClickableItems(contentPlaceholder);
                        requestAnimationFrame(() => { detailRow.offsetHeight; detailRow.classList.add('expanded'); });
                        element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                        element.classList.add('toggle-pressed');
                    } else {
                        contentPlaceholder.innerHTML = `<p>Error loading details: ${data.message || 'Unknown error'}</p>`;
                    }
                })
                .catch(error => { contentPlaceholder.innerHTML = `<p>Error loading details: ${error.message}</p>`; });
        }
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