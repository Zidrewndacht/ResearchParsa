// static/js/core/virtual_scroll.js
/**
 * Virtual scrolling with row unloading.
 * Renders at most ~(BUFFER*2 + viewport) paper-groups at any time.
 * Uses incremental add/remove at the edges — rows that stay in view
 * are NEVER re-rendered, preserving expanded state and shading.
 */
const virtualScroll = (() => {
    const ROW_HEIGHT = 58;       // estimated collapsed height per paper-group (px)
    const BUFFER = 4;          // extra paper-groups rendered above/below viewport
    let scrollContainer = null;
    let tbody = null;
    let spacerTop = null;
    let spacerBottom = null;
    let renderedStart = -1;
    let renderedEnd = -1;
    let totalCols = 0;
    let rafPending = false;

    let _lastScrollTop = 0;
    let _headerExpanded = false;
    const UNCOLLAPSE_TOLERANCE = 120;   // px of sustained upward scroll before the header re-expands
    let _scrollAccum = 0;
    
    /* Measure the three natural row heights once; row 1 is 0px in the export. */
    function _measureHeaderRows() {
        const rows = document.querySelectorAll('#papersTable thead tr');
        if (!rows.length || !scrollContainer) return;
        scrollContainer.style.setProperty('--hdr-h1', (rows[0].offsetHeight || 0) + 'px');
        scrollContainer.style.setProperty('--hdr-h2', (rows[1].offsetHeight || 0) + 'px');
        scrollContainer.style.setProperty('--hdr-h3', (rows[2].offsetHeight || 0) + 'px');
        scrollContainer.style.setProperty('--hdr-h4', (rows[3].offsetHeight || 0) + 'px');  // ← ADD
    }

    function _setHeaderExpanded(expanded) {
        if (expanded === _headerExpanded) return;
        _headerExpanded = expanded;
        scrollContainer.classList.toggle('header-expanded', expanded);
    }

    let _lastProgress = -1;
    
    function _updateHeaderState(scrollTop) {
        const max = scrollContainer.scrollHeight - scrollContainer.clientHeight;
        const progress = max > 0 ? scrollTop / max : 0;
        if (Math.abs(progress - _lastProgress) > 0.001) {   // skip tiny deltas
            scrollContainer.style.setProperty('--scroll-progress', progress.toFixed(4));
            _lastProgress = progress;
        }
        if (scrollTop <= 0) {          // top of table: pure natural layout, as today
            _lastScrollTop = scrollTop;
            _scrollAccum = 0;
            _setHeaderExpanded(false);
            return;
        }
        const delta = scrollTop - _lastScrollTop;
        _lastScrollTop = scrollTop;
        if (delta > 0) {               // downward: collapse now, re-arm the tolerance
            _scrollAccum = 0;
            _setHeaderExpanded(false);
        } else if (delta < 0) {        // upward: expand only after sustained movement
            _scrollAccum -= delta;
            if (_scrollAccum >= UNCOLLAPSE_TOLERANCE) _setHeaderExpanded(true);
        }
    }

    function init(container, tableBody, cols) {
        scrollContainer = container;
        tbody = tableBody;
        totalCols = cols;
        spacerTop = _makeSpacer();
        spacerBottom = _makeSpacer();
        tbody.appendChild(spacerTop);
        tbody.appendChild(spacerBottom);
        scrollContainer.addEventListener('scroll', _onScroll, { passive: true });
        _measureHeaderRows();
        window.addEventListener('resize', _measureHeaderRows);
    }

    function _makeSpacer() {
        const tr = document.createElement('tr');
        tr.className = 'virtual-spacer';
        tr.style.height = '0px';
        const td = document.createElement('td');
        td.colSpan = totalCols + 5;
        td.style.padding = '0';
        td.style.border = 'none';
        td.style.height = '0px';
        tr.appendChild(td);
        return tr;
    }

    function _onScroll() {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(() => {
            rafPending = false;
            update();
        });
    }

    function update() {
        _updateHeaderState(scrollContainer.scrollTop);   // first line
        const papers = papersStore.getFiltered();
        const total = papers.length;
        scrollContainer.classList.toggle('table-rendered', total > 0);   // ← ADD

        if (total === 0) {
            _clearAllRendered();
            _setSpacerHeight(spacerTop, 0);
            _setSpacerHeight(spacerBottom, 0);
            renderedStart = 0;
            renderedEnd = 0;
            return;
        }

        const scrollTop = scrollContainer.scrollTop;
        const viewH = scrollContainer.clientHeight;
        const newStart = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER);
        const newEnd = Math.min(total, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + BUFFER);

        if (newStart === renderedStart && newEnd === renderedEnd) return;

        const isExport = document.body.id === 'html-export';

        if (renderedStart === -1) {
            // --- Initial render ---
            const fragment = document.createDocumentFragment();
            for (let i = newStart; i < newEnd; i++) {
                _appendPaperToFragment(fragment, papers[i], i, isExport);
            }
            tbody.insertBefore(fragment, spacerBottom);
        } else {
            // --- Incremental update: remove out-of-range, add new ---

            // Remove from top: [renderedStart, newStart)
            for (let i = renderedStart; i < newStart && i < renderedEnd; i++) {
                _removePaperByIndex(papers, i);
            }
            // Remove from bottom: [newEnd, renderedEnd)
            for (let i = Math.max(newEnd, renderedStart); i < renderedEnd; i++) {
                _removePaperByIndex(papers, i);
            }

            // Add at top: [newStart, min(renderedStart, newEnd))
            if (newStart < renderedStart) {
                const topEnd = Math.min(renderedStart, newEnd);
                const frag = document.createDocumentFragment();
                for (let i = newStart; i < topEnd; i++) {
                    _appendPaperToFragment(frag, papers[i], i, isExport);
                }
                spacerTop.after(frag);
            }

            // Add at bottom: [max(renderedEnd, newStart), newEnd)
            if (newEnd > renderedEnd) {
                const bottomStart = Math.max(renderedEnd, newStart);
                const frag = document.createDocumentFragment();
                for (let i = bottomStart; i < newEnd; i++) {
                    _appendPaperToFragment(frag, papers[i], i, isExport);
                }
                tbody.insertBefore(frag, spacerBottom);
            }
        }

        // Update spacers
        _setSpacerHeight(spacerTop, newStart * ROW_HEIGHT);
        _setSpacerHeight(spacerBottom, Math.max(0, (total - newEnd)) * ROW_HEIGHT);

        renderedStart = newStart;
        renderedEnd = newEnd;

        // Restore expanded detail/history rows that were re-created after scrolling
        if (typeof restoreDetailState === 'function') restoreDetailState();
    }

    // --- Row creation with deterministic shading ---
    function _appendPaperToFragment(fragment, paper, arrayIndex, isExport) {
        const rows = tableRenderer.renderPaper(paper, isExport);
        const shade = (arrayIndex & 1) ? 'alt-shade-2' : 'alt-shade-1';

        // --- duplicate shading at creation time (was a separate O(n) pass) ---
        const jTxt = (paper.deannualized_conference || paper.journal || '').trim().toLowerCase();
        const tTxt = (paper.title || '').trim().toLowerCase();
        const mainRow = rows[0];
        const jCell = mainRow.cells[journalCellIndex];
        const tCell = mainRow.cells[titleCellIndex];
        if (jCell && jTxt && _dupJournalCounts.get(jTxt) >= 2)
            jCell.style.backgroundColor = _dupJournalHsl.get(jTxt);
        if (tCell && tTxt && _dupTitleCounts.get(tTxt) >= 2)
            tCell.style.backgroundColor = _dupTitleHsl;
        // ----------------------------------------------------------------

        for (const r of rows) {
            r.classList.add(shade);
            fragment.appendChild(r);
        }
    }

    // --- Row removal (collapse before removing) ---
    function _removePaperByIndex(papers, index) {
        if (index < 0 || index >= papers.length) return;
        const paperId = String(papers[index].id);
        const mainRow = tbody.querySelector(`tr[data-paper-id="${_cssEscape(paperId)}"]`);
        if (!mainRow) return;

        const detailRow = mainRow.nextElementSibling;
        const historyRow = detailRow ? detailRow.nextElementSibling : null;

        // Collapse expanded rows before removal
        if (detailRow && detailRow.classList.contains('expanded')) {
            detailRow.classList.remove('expanded');
        }
        if (historyRow && historyRow.classList.contains('expanded')) {
            historyRow.classList.remove('expanded');
        }
        // Reset toggle buttons
        const btns = mainRow.querySelectorAll('.toggle-btn.toggle-pressed');
        for (const b of btns) {
            b.classList.remove('toggle-pressed');
            b.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        }

        if (historyRow) historyRow.remove();
        if (detailRow) detailRow.remove();
        mainRow.remove();
    }

    function _clearAllRendered() {
        const rows = tbody.querySelectorAll('tr[data-paper-id], tr.detail-row, tr.history-row');
        for (const r of rows) r.remove();
    }

    function _setSpacerHeight(spacer, px) {
        spacer.style.height = px + 'px';
        const td = spacer.querySelector('td');
        if (td) td.style.height = px + 'px';
    }

    // --- Public API ---
    function reset() {
        _clearAllRendered();
        renderedStart = -1;
        renderedEnd = -1;
        scrollContainer.scrollTop = 0;
        update();
    }

    function refresh() {
        // Used after AJAX cell updates to re-render current window
        const st = scrollContainer.scrollTop;
        _clearAllRendered();
        renderedStart = -1;
        renderedEnd = -1;
        scrollContainer.scrollTop = st; 
        _lastScrollTop = st; 
        update();
        scrollContainer.scrollTop = st;
    }

    function ensurePaperVisible(paperId) {
        const papers = papersStore.getFiltered();
        const idx = papers.findIndex(p => String(p.id) === String(paperId));
        if (idx === -1) return null;
        scrollContainer.scrollTop = idx * ROW_HEIGHT;
        scrollContainer.scrollTop = idx * ROW_HEIGHT; 
        _lastScrollTop = scrollContainer.scrollTop; 
        update();
        return tbody.querySelector(`tr[data-paper-id="${_cssEscape(String(paperId))}"]`);
    }

    function getRenderedRange() {
        return { start: renderedStart, end: renderedEnd };
    }

    function _cssEscape(str) {
        if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(str);
        return str.replace(/([^\w-])/g, '\\$1');
    }

    // --- Module-level cache (add near top of the IIFE, after existing lets) ---
    let _dupJournalCounts = new Map();
    let _dupTitleCounts = new Map();
    let _dupJournalHsl = new Map();
    let _dupTitleHsl = '';
    let _dupTitleCount = 0;

    // --- Called from filtering_engine.js after filters/sort change ---
    function prepareDuplicateData() {
        const papers = papersStore.getFiltered();
        _dupJournalCounts = new Map();
        _dupTitleCounts = new Map();
        for (const p of papers) {
            const jTxt = (p.deannualized_conference || p.journal || '').trim().toLowerCase();
            const tTxt = (p.title || '').trim().toLowerCase();
            if (jTxt) _dupJournalCounts.set(jTxt, (_dupJournalCounts.get(jTxt) || 0) + 1);
            if (tTxt) _dupTitleCounts.set(tTxt, (_dupTitleCounts.get(tTxt) || 0) + 1);
        }
        _dupTitleCount = 0;
        for (const [, count] of _dupTitleCounts) { if (count >= 2) _dupTitleCount++; }
        if (duplicateCountElement) duplicateCountElement.textContent = _dupTitleCount;

        let maxCount = 0;
        for (const count of _dupJournalCounts.values()) { if (count > maxCount) maxCount = count; }
        const baseJournalHue = 210, baseSaturation = 66, minLightness = 96, maxLightness = 84;
        _dupJournalHsl = new Map();
        for (const [name, count] of _dupJournalCounts) {
            if (count >= 2) {
                let lightness = maxCount <= 1 ? minLightness
                    : maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
                lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
                _dupJournalHsl.set(name, `hsl(${baseJournalHue}, ${baseSaturation}%, ${lightness}%)`);
            }
        }
        _dupTitleHsl = `hsl(0, 66%, 94%)`;
    }

    // --- Called from update(); only touches rendered rows ---
    function _applyDuplicateShading() {
        const rows = tbody.querySelectorAll('tr[data-paper-id]');
        for (const row of rows) {
            const jCell = row.cells[journalCellIndex];
            const tCell = row.cells[titleCellIndex];
            if (jCell) jCell.style.backgroundColor = '';
            if (tCell) tCell.style.backgroundColor = '';
            const jTxt = jCell ? jCell.textContent.trim().toLowerCase() : '';
            const tTxt = tCell ? tCell.textContent.trim().toLowerCase() : '';
            if (jTxt && _dupJournalCounts.get(jTxt) >= 2) jCell.style.backgroundColor = _dupJournalHsl.get(jTxt);
            if (tTxt && _dupTitleCounts.get(tTxt) >= 2) tCell.style.backgroundColor = _dupTitleHsl;
        }
    }

    return { init, update, reset, refresh, getRenderedRange, ensurePaperVisible, prepareDuplicateData };
})();