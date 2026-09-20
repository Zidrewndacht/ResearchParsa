// static/ghpages.js
/**
 * Logic exclusive to the client-side-only standalone HTML/GHpages version.
 * Provides toggleDetails and toggleHistory using the embedded data store
 * and client-side renderers, since there is no server to fetch from.
 */

function toggleDetails(element) {
    const row = element.closest('tr');
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ? row.nextElementSibling : null;
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling && row.nextElementSibling.nextElementSibling.classList.contains('history-row') ? row.nextElementSibling.nextElementSibling : null;
    if (!detailRow) return;

    const isExpanded = detailRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        detailRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        if (typeof openDetailIds !== 'undefined') openDetailIds.delete(paperId);
        if (typeof updateUrlWithDetailState === 'function') updateUrlWithDetailState();
    } else {
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
            const historyToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleHistory"]');
            if (historyToggleBtn) {
                historyToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                historyToggleBtn.classList.remove('toggle-pressed');
            }
            if (typeof openHistoryIds !== 'undefined') openHistoryIds.delete(paperId);
        }
        if (typeof openDetailIds !== 'undefined') openDetailIds.add(paperId);
        if (typeof updateUrlWithDetailState === 'function') updateUrlWithDetailState();

        const contentPlaceholder = detailRow.querySelector('.detail-content-placeholder');
        if (typeof papersStore !== 'undefined' && typeof exportRenderers !== 'undefined') {
            const paper = papersStore.getPaperById(paperId);
            if (paper) {
                contentPlaceholder.innerHTML = exportRenderers.renderDetailContent(paper);
                // Wire clickable items (keywords/authors)
                contentPlaceholder.addEventListener('click', function (event) {
                    if (event.target.classList.contains('clickable-item')) {
                        event.preventDefault();
                        const searchTerm = event.target.getAttribute('data-search-term');
                        if (searchTerm && typeof searchInput !== 'undefined' && typeof applyLocalFilters === 'function') {
                            searchInput.value = searchTerm.trim();
                            applyLocalFilters();
                        }
                    }
                });
                requestAnimationFrame(() => {
                    detailRow.offsetHeight; // Trigger reflow
                    detailRow.classList.add('expanded');
                });
                element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                element.classList.add('toggle-pressed');
            }
        }
    }
}

function toggleHistory(element) {
    const row = element.closest('tr');
    const historyRow = row.nextElementSibling && row.nextElementSibling.nextElementSibling && row.nextElementSibling.nextElementSibling.classList.contains('history-row') ? row.nextElementSibling.nextElementSibling : null;
    const detailRow = row.nextElementSibling && row.nextElementSibling.classList.contains('detail-row') ? row.nextElementSibling : null;
    if (!historyRow) return;

    const isExpanded = historyRow.classList.contains('expanded');
    const paperId = row.getAttribute('data-paper-id');

    if (isExpanded) {
        historyRow.classList.remove('expanded');
        element.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        element.classList.remove('toggle-pressed');
        if (typeof openHistoryIds !== 'undefined') openHistoryIds.delete(paperId);
        if (typeof updateUrlWithDetailState === 'function') updateUrlWithDetailState();
    } else {
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
            const detailToggleBtn = row.querySelector('.toggle-btn[onclick*="toggleDetails"]');
            if (detailToggleBtn) {
                detailToggleBtn.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
                detailToggleBtn.classList.remove('toggle-pressed');
            }
            if (typeof openDetailIds !== 'undefined') openDetailIds.delete(paperId);
        }
        if (typeof openHistoryIds !== 'undefined') openHistoryIds.add(paperId);
        if (typeof updateUrlWithDetailState === 'function') updateUrlWithDetailState();

        const contentPlaceholder = historyRow.querySelector('.detail-content-placeholder');
        if (typeof papersStore !== 'undefined' && typeof exportRenderers !== 'undefined') {
            const paper = papersStore.getPaperById(paperId);
            if (paper) {
                contentPlaceholder.innerHTML = exportRenderers.renderHistoryContent(paper);
                requestAnimationFrame(() => {
                    historyRow.offsetHeight; // Trigger reflow
                    historyRow.classList.add('expanded');
                });
                element.innerHTML = '<span>Hide</span><br><span class="arrow">▲</span>';
                element.classList.add('toggle-pressed');
            }
        }
    }
}

document.addEventListener('DOMContentLoaded', function () {
    if (document.body.id !== 'html-export') return;

    // In the static export, server-side filters act as local client-side filters
    // because all data is already embedded and filtered in memory.
    const hideOfftopicCheckbox = document.getElementById('hide-offtopic-checkbox');
    const minPageCountInput = document.getElementById('min-page-count');
    const yearFromInput = document.getElementById('year-from');
    const yearToInput = document.getElementById('year-to');

    if (hideOfftopicCheckbox && typeof applyLocalFilters === 'function') {
        hideOfftopicCheckbox.addEventListener('change', applyLocalFilters);
    }
    if (minPageCountInput && typeof applyLocalFilters === 'function') {
        minPageCountInput.addEventListener('input', applyLocalFilters);
        minPageCountInput.addEventListener('change', applyLocalFilters);
    }
    if (yearFromInput && typeof applyLocalFilters === 'function') {
        yearFromInput.addEventListener('input', applyLocalFilters);
        yearFromInput.addEventListener('change', applyLocalFilters);
    }
    if (yearToInput && typeof applyLocalFilters === 'function') {
        yearToInput.addEventListener('input', applyLocalFilters);
        yearToInput.addEventListener('change', applyLocalFilters);
    }
});