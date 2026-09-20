// static/js/core/virtual_scroll.js
/**
 * Virtual scrolling with row unloading.
 * Keeps at most ~WINDOW_SIZE paper-groups in the DOM at any time.
 * Uses spacer <tr> elements above and below the rendered window to
 * preserve scrollbar geometry.
 */
const virtualScroll = (() => {
    const ROW_HEIGHT = 58;       // estimated collapsed height per paper-group (px)
    const BUFFER = 200;           // extra paper-groups rendered above/below viewport
    let scrollContainer = null;
    let tbody = null;
    let spacerTop = null;
    let spacerBottom = null;
    let renderedStart = -1;
    let renderedEnd = -1;
    let totalCols = 0;
    let rafPending = false;

    function init(container, tableBody, cols) {
        scrollContainer = container;
        tbody = tableBody;
        totalCols = cols;

        spacerTop = _makeSpacer();
        spacerBottom = _makeSpacer();
        tbody.appendChild(spacerTop);
        tbody.appendChild(spacerBottom);

        scrollContainer.addEventListener('scroll', _onScroll, { passive: true });
    }

    function _makeSpacer() {
        const tr = document.createElement('tr');
        tr.className = 'virtual-spacer';
        tr.style.height = '0px';
        const td = document.createElement('td');
        td.colSpan = totalCols + 5; // +5 hidden cols
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
        const papers = papersStore.getFiltered();
        const total = papers.length;

        if (total === 0) {
            _clearRendered();
            _setSpacerHeight(spacerTop, 0);
            _setSpacerHeight(spacerBottom, 0);
            renderedStart = 0;
            renderedEnd = 0;
            return;
        }

        const scrollTop = scrollContainer.scrollTop;
        const viewH = scrollContainer.clientHeight;

        let start = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - BUFFER);
        let end = Math.min(total, Math.ceil((scrollTop + viewH) / ROW_HEIGHT) + BUFFER);

        if (start === renderedStart && end === renderedEnd) return;

        // Collapse any expanded detail/history rows that are about to be unloaded
        _collapseExpandedInRange(renderedStart, renderedEnd, start, end);

        _clearRendered();

        _setSpacerHeight(spacerTop, start * ROW_HEIGHT);
        _setSpacerHeight(spacerBottom, Math.max(0, (total - end)) * ROW_HEIGHT);

        const isExport = document.body.id === 'html-export';
        const slice = papers.slice(start, end);
        const frag = tableRenderer.renderBatch(slice, isExport);
        tbody.insertBefore(frag, spacerBottom);

        renderedStart = start;
        renderedEnd = end;

        // Post-render visual hooks
        _applyAlternatingShading();
        if (document.body.id !== 'html-export') {
            _applyDuplicateShading();
        }
        restoreDetailState();
    }

    function reset() {
        renderedStart = -1;
        renderedEnd = -1;
        scrollContainer.scrollTop = 0;
        update();
    }

    function refresh() {
        // Re-render current window (e.g. after cell update)
        const s = renderedStart, e = renderedEnd;
        renderedStart = -1;
        renderedEnd = -1;
        // Preserve scroll position
        const st = scrollContainer.scrollTop;
        update();
        scrollContainer.scrollTop = st;
    }

    function getRenderedRange() {
        return { start: renderedStart, end: renderedEnd };
    }

    function ensurePaperVisible(paperId) {
        const papers = papersStore.getFiltered();
        const idx = papers.findIndex(p => String(p.id) === String(paperId));
        if (idx === -1) return null;
        // Scroll to that position
        scrollContainer.scrollTop = idx * ROW_HEIGHT;
        update();
        return document.querySelector(`tr[data-paper-id="${CSS.escape ? CSS.escape(paperId) : paperId}"]`);
    }

    // --- Internal helpers ---

    function _clearRendered() {
        const rows = tbody.querySelectorAll('tr[data-paper-id], tr.detail-row, tr.history-row');
        for (const r of rows) r.remove();
    }

    function _setSpacerHeight(spacer, px) {
        spacer.style.height = px + 'px';
        const td = spacer.querySelector('td');
        if (td) td.style.height = px + 'px';
    }

    function _collapseExpandedInRange(oldStart, oldEnd, newStart, newEnd) {
        // Collapse expanded rows that will be removed
        const rows = tbody.querySelectorAll('tr.detail-row.expanded, tr.history-row.expanded');
        for (const r of rows) {
            r.classList.remove('expanded');
        }
        // Also reset toggle buttons
        const btns = tbody.querySelectorAll('.toggle-btn.toggle-pressed');
        for (const b of btns) {
            b.classList.remove('toggle-pressed');
            b.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        }
    }

    function _applyAlternatingShading() {
        const rows = tbody.querySelectorAll('tr[data-paper-id]');
        let idx = 0;
        for (const main of rows) {
            const shade = (idx & 1) ? 'alt-shade-2' : 'alt-shade-1';
            main.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
            main.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
            const detail = main.nextElementSibling;
            if (detail && detail.classList.contains('detail-row')) {
                detail.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
                detail.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
            }
            const history = detail && detail.nextElementSibling;
            if (history && history.classList.contains('history-row')) {
                history.classList.toggle('alt-shade-1', shade === 'alt-shade-1');
                history.classList.toggle('alt-shade-2', shade === 'alt-shade-2');
            }
            idx++;
        }
    }

    function _applyDuplicateShading() {
        const rows = tbody.querySelectorAll('tr[data-paper-id]');
        const journalCounts = new Map();
        const titleCounts = new Map();

        for (const row of rows) {
            const jCell = row.cells[journalCellIndex];
            const tCell = row.cells[titleCellIndex];
            const jTxt = jCell ? jCell.textContent.trim().toLowerCase() : '';
            const tTxt = tCell ? tCell.textContent.trim().toLowerCase() : '';
            if (jTxt) journalCounts.set(jTxt, (journalCounts.get(jTxt) || 0) + 1);
            if (tTxt) titleCounts.set(tTxt, (titleCounts.get(tTxt) || 0) + 1);
        }

        let dupTitleCount = 0;
        for (const [, count] of titleCounts) { if (count >= 2) dupTitleCount++; }
        if (duplicateCountElement) duplicateCountElement.textContent = dupTitleCount;

        let maxCount = 0;
        for (const count of journalCounts.values()) { if (count > maxCount) maxCount = count; }

        const baseJournalHue = 210, baseSaturation = 66, minLightness = 96, maxLightness = 84;
        const journalHsl = new Map();
        for (const [name, count] of journalCounts) {
            if (count >= 2) {
                let lightness = maxCount <= 1 ? minLightness
                    : maxLightness + (minLightness - maxLightness) * (1 - (count - 1) / (maxCount - 1));
                lightness = Math.max(maxLightness, Math.min(minLightness, lightness));
                journalHsl.set(name, `hsl(${baseJournalHue}, ${baseSaturation}%, ${lightness}%)`);
            }
        }
        const dupTitleHsl = `hsl(0, 66%, 94%)`;

        for (const row of rows) {
            const jCell = row.cells[journalCellIndex];
            const tCell = row.cells[titleCellIndex];
            if (jCell) jCell.style.backgroundColor = '';
            if (tCell) tCell.style.backgroundColor = '';
            const jTxt = jCell ? jCell.textContent.trim().toLowerCase() : '';
            const tTxt = tCell ? tCell.textContent.trim().toLowerCase() : '';
            if (jTxt && journalCounts.get(jTxt) >= 2) jCell.style.backgroundColor = journalHsl.get(jTxt);
            if (tTxt && titleCounts.get(tTxt) >= 2) tCell.style.backgroundColor = dupTitleHsl;
        }
    }

    return { init, update, reset, refresh, getRenderedRange, ensurePaperVisible };
})();