// static/js/core/table_renderer.js
/**
 * Builds DOM rows from paper data objects.
 * Produces HTML structurally identical to the retired papers_table.html / paper_cells.html.
 */
const tableRenderer = (() => {

    const TYPE_EMOJIS = {
        'article': '📄', 'inproceedings': '📚', 'incollection': '📖',
        'book': '📘', 'phdthesis': '🎓', 'mastersthesis': '🎓',
        'techreport': '📋', 'misc': '📁'
    };
    const DEFAULT_TYPE_EMOJI = '📄';
    const PDF_EMOJIS = { 'PDF': '📕', 'annotated': '📗', 'paywalled': '💰', 'none': '❔' };

    // Total visible columns (for colspan on detail/history rows)
    let totalCols = 0;
    function computeTotalCols() {
        let dyn = 0;
        for (const g of APP_CONFIG.groups) {
            if (g.filter_type === 'tri_state') dyn += 1;
            else if (g.filter_type === 'inclusion' || g.filter_type === 'none') dyn += (g.fields || []).length;
        }
        totalCols = 6 + 2 + dyn + 9;
        return totalCols;
    }

    function esc(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function renderStatus(value) {
        if (value === 1 || value === true || value === '1' || value === 'true') return '✔️';
        if (value === 0 || value === false || value === '0' || value === 'false') return '❌';
        return '❔';
    }

    function renderVerifiedBy(value) {
        if (value === 'user') return '<span title="User">👤</span>';
        if (value === null || value === undefined || value === '') return '<span title="Unverified">❔</span>';
        const escaped = esc(value);
        return `<span title="${escaped}">🖥️</span>`;
    }

    function renderChangedBy(value) {
        if (value === 'user') return '<span title="User">👤</span>';
        if (value === null || value === undefined || value === '') return '<span title="Unknown">❔</span>';
        const escaped = esc(value);
        return `<span title="${escaped}">🖥️</span>`;
    }

    function formatRelevance(val) {
        if (val === null || val === undefined || val === '') return '';
        const num = parseFloat(val);
        if (isNaN(num)) return '';
        return (Math.round(num * 10) / 10).toFixed(1).replace(/\.?0+$/, '');
    }

    function getBool(obj, path) {
        if (!obj || !path) return null;
        let cur = obj;
        for (const k of path.split('.')) {
            if (cur && typeof cur === 'object' && k in cur) cur = cur[k];
            else return null;
        }
        if (cur === true || cur === 1 || cur === '1' || cur === 'true') return true;
        if (cur === false || cur === 0 || cur === '0' || cur === 'false') return false;
        return null;
    }

    function getPath(obj, path) {
        if (!obj || !path) return null;
        let cur = obj;
        for (const k of path.split('.')) {
            if (cur && typeof cur === 'object' && k in cur) cur = cur[k];
            else return null;
        }
        return cur;
    }

    // --- Cell builders ---

    function buildPdfCell(paper, isExport) {
        const td = document.createElement('td');
        td.className = 'status-cell emoji-column';
        const hasLinkedPdf = paper.pdf_filename && (paper.pdf_state === 'PDF' || paper.pdf_state === 'annotated');
        // Clickable affordance (cursor/hover) only where a click does something:
        // live app = PDF viewer link + upload link; export = PDF file link only.
        if (hasLinkedPdf || !isExport) td.classList.add('pdf-status');
        if (hasLinkedPdf) {
            const a = document.createElement('a');
            a.target = '_blank';
            a.className = 'pdf-link';
            if (isExport) {
                const dir = paper.pdf_state === 'annotated' ? 'data/pdf_annotated' : 'data/pdf';
                a.href = `${dir}/${paper.pdf_filename}`;
                a.title = 'Open PDF';
            } else {
                a.href = `/static/pdfjs/web/viewer.html?file=/serve_pdf/${encodeURIComponent(paper.id)}`;
                a.title = paper.pdf_state === 'annotated'
                    ? 'Open this annotated PDF in the Annotator'
                    : 'Open this PDF in the Annotator';
            }
            a.textContent = PDF_EMOJIS[paper.pdf_state] || '❔';
            td.appendChild(a);
        } else if (!isExport) {
            const a = document.createElement('a');
            a.href = '#';
            a.className = 'pdf-upload-link';
            a.setAttribute('data-paper-id', paper.id);
            const isPaywalled = paper.pdf_state === 'paywalled';
            a.title = isPaywalled
                ? 'Article is paywalled. Click to upload if a copy is available'
                : 'No PDF stored yet. Click to upload PDF';
            a.textContent = isPaywalled ? '💰' : '❔';
            td.appendChild(a);
        } else if (paper.pdf_state === 'paywalled') {
            const span = document.createElement('span');
            span.title = 'This paper is paywalled';
            span.textContent = '💰';
            td.appendChild(span);
        }
        // In export, pdf_state === 'none' renders nothing
        return td;
    }

    function buildTitleCell(paper) {
        const td = document.createElement('td');
        td.className = 'title-cell';
        if (paper.doi) {
            const a = document.createElement('a');
            a.href = `https://doi.org/${paper.doi}`;
            a.target = '_blank';
            a.textContent = paper.title || '';
            td.appendChild(a);
        } else {
            const span = document.createElement('span');
            span.style.fontWeight = '300';
            span.textContent = paper.title || '';
            td.appendChild(span);
        }
        return td;
    }

    function buildInferredCell(paper, path, editable) {
        const c = paper.classification || {};
        const cert = paper.main_certainty || {};
        const certainty = cert[path] || 'solid';
        const td = document.createElement('td');
        td.className = `status-cell ${editable ? 'editable-status ' : ''}certainty-${certainty}`;
        td.setAttribute('data-field', path);
        if (certainty === 'conflict') {
            td.innerHTML = '<span class="conflict-warning">⚠️</span>';
        } else {
            const span = document.createElement('span');
            span.className = 'emoji-content';
            span.textContent = renderStatus(getBool(c, path));
            td.appendChild(span);
        }
        return td;
    }

    function buildTextPresenceCell(paper, path, highlight) {
        const c = paper.classification || {};
        const cert = paper.main_certainty || {};
        const certainty = cert[path] || 'solid';
        const td = document.createElement('td');
        td.className = `status-cell ${highlight ? 'highlight-status ' : ''}certainty-${certainty}`;
        td.setAttribute('data-field', path);
        const val = getPath(c, path);
        const span = document.createElement('span');
        span.className = 'emoji-content';
        span.textContent = (val && String(val).trim()) ? '✔️' : '❌';
        td.appendChild(span);
        return td;
    }

    function buildDomainCells(paper, editable) {
        const cells = [];
        const c = paper.classification || {};
        for (const group of APP_CONFIG.groups) {
            if (group.filter_type === 'tri_state') {
                cells.push(buildInferredCell(paper, group.json_path, editable));
            } else if (group.filter_type === 'inclusion' || group.filter_type === 'none') {
                for (const fd of group.fields || []) {
                    const path = `${group.json_path}.${fd.key}`;
                    if (fd.render_type === 'text_presence') {
                        cells.push(buildTextPresenceCell(paper, path, !!fd.highlight));
                    } else {
                        const td = buildInferredCell(paper, path, editable);
                        if (fd.highlight) td.classList.add('highlight-status');
                        cells.push(td);
                    }
                }
            }
        }
        return cells;
    }

    // --- Main row builder ---
    function buildMainRow(paper, isExport) {
        const editable = !isExport;
        const c = paper.classification || {};
        const cert = paper.main_certainty || {};
        const tr = document.createElement('tr');
        tr.setAttribute('data-paper-id', paper.id);

        // 1. PDF
        tr.appendChild(buildPdfCell(paper, isExport));

        // 2. Title
        tr.appendChild(buildTitleCell(paper));

        // 3. Year
        const yearTd = document.createElement('td');
        yearTd.className = 'secondary-text-cell number-cell';
        yearTd.textContent = paper.year ?? '';
        tr.appendChild(yearTd);

        // 4. Page count
        const pcTd = document.createElement('td');
        pcTd.className = 'secondary-text-cell number-cell';
        pcTd.setAttribute('data-field', 'page_count');
        pcTd.textContent = paper.page_count ?? '';
        tr.appendChild(pcTd);

        // 5. Journal
        const jTd = document.createElement('td');
        jTd.className = 'secondary-text-cell';
        jTd.textContent = paper.deannualized_conference || paper.journal || '';
        tr.appendChild(jTd);

        // 6. Type
        const typeTd = document.createElement('td');
        typeTd.className = 'status-cell emoji-column';
        typeTd.title = paper.type || '';
        typeTd.textContent = TYPE_EMOJIS[paper.type] || DEFAULT_TYPE_EMOJI;
        tr.appendChild(typeTd);

        // 7. Off-topic
        tr.appendChild(buildInferredCell(paper, 'is_offtopic', editable));

        // 8. Relevance
        const relTd = document.createElement('td');
        relTd.className = 'secondary-text-cell number-cell';
        relTd.setAttribute('data-field', 'relevance');
        relTd.textContent = formatRelevance(getPath(c, 'relevance'));
        tr.appendChild(relTd);

        // 9. Dynamic domain cells
        for (const td of buildDomainCells(paper, editable)) {
            tr.appendChild(td);
        }

        // 10. Changed
        const chTd = document.createElement('td');
        chTd.className = 'secondary-text-cell changed-cell highlight-status';
        chTd.textContent = paper.changed_formatted || '';
        tr.appendChild(chTd);

        // 11. Changed by
        const cbTd = document.createElement('td');
        cbTd.className = 'status-cell changed-by-cell highlight-status';
        cbTd.setAttribute('data-field', 'changed_by');
        cbTd.innerHTML = renderChangedBy(paper.changed_by);
        tr.appendChild(cbTd);

        // 12. Verified
        const vCert = cert['verified'] || 'solid';
        const vTd = document.createElement('td');
        vTd.className = `status-cell ${editable ? 'editable-status ' : ''}certainty-${vCert}`;
        vTd.setAttribute('data-field', 'verified');
        if (vCert === 'conflict') {
            vTd.innerHTML = '<span class="conflict-warning">⚠️</span>';
        } else {
            vTd.innerHTML = `<span class="emoji-content">${renderStatus(paper.verified)}</span>`;
        }
        tr.appendChild(vTd);

        // 13. Estimated score
        const esTd = document.createElement('td');
        esTd.className = 'secondary-text-cell number-cell';
        esTd.setAttribute('data-field', 'estimated_score');
        esTd.textContent = paper.estimated_score ?? '';
        tr.appendChild(esTd);

        // 14. Verified by
        const vbTd = document.createElement('td');
        vbTd.className = `status-cell ${editable ? 'editable-verify' : ''}`;
        vbTd.setAttribute('data-field', 'verified_by');
        vbTd.innerHTML = renderVerifiedBy(paper.verified_by);
        tr.appendChild(vbTd);

        // 15. User override count
        const uoTd = document.createElement('td');
        uoTd.className = 'secondary-text-cell number-cell';
        uoTd.setAttribute('data-field', 'user_override_count');
        uoTd.textContent = paper.user_override_count ?? '0';
        tr.appendChild(uoTd);

        // 16. User comment state
        const ucTd = document.createElement('td');
        ucTd.className = 'status-cell';
        ucTd.setAttribute('data-field', 'user_comment_state');
        const hasTrace = paper.user_trace && String(paper.user_trace).trim();
        ucTd.innerHTML = `<span class="emoji-content">${hasTrace ? '✔️' : '❌'}</span>`;
        tr.appendChild(ucTd);

        // 17. History toggle
        const hTd = document.createElement('td');
        hTd.className = 'toggle-btn history-btn';
        hTd.setAttribute('onclick', 'toggleHistory(this)');
        hTd.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        tr.appendChild(hTd);

        // 18. Details toggle
        const dTd = document.createElement('td');
        dTd.className = 'toggle-btn';
        dTd.setAttribute('onclick', 'toggleDetails(this)');
        dTd.innerHTML = '<span>Show</span><br><span class="arrow">▼</span>';
        tr.appendChild(dTd);

        // 19. Hidden data cells
        const hiddenFields = [
            ['abstract', paper.abstract || ''],
            ['keywords', paper.keywords || ''],
            ['authors', paper.authors || ''],
            ['user_trace', paper.user_trace || '']
        ];
        for (const [field, val] of hiddenFields) {
            const td = document.createElement('td');
            td.className = 'hidden-data-cell';
            td.setAttribute('data-field', field);
            td.style.display = 'none';
            td.textContent = val;
            tr.appendChild(td);
        }
        for (const field of APP_CONFIG.editable_fields || []) {
            const td = document.createElement('td');
            td.className = 'hidden-data-cell';
            td.setAttribute('data-field', field.json_path.replace(/\./g, '_'));
            td.style.display = 'none';
            td.textContent = getPath(c, field.json_path) || '';
            tr.appendChild(td);
        }

        return tr;
    }

    function buildPlaceholderRow(className) {
        const tr = document.createElement('tr');
        tr.className = className;
        const td = document.createElement('td');
        td.colSpan = totalCols;
        td.className = 'detail-content-placeholder';
        tr.appendChild(td);
        const tdHidden = document.createElement('td');
        tdHidden.style.display = 'none';
        tdHidden.colSpan = 5;
        tr.appendChild(tdHidden);
        return tr;
    }

    // --- Public API ---
    function renderPaper(paper, isExport) {
        if (!totalCols) computeTotalCols();
        return [
            buildMainRow(paper, isExport),
            buildPlaceholderRow('detail-row'),
            buildPlaceholderRow('history-row')
        ];
    }

    function renderBatch(papers, isExport) {
        if (!totalCols) computeTotalCols();
        const frag = document.createDocumentFragment();
        for (const paper of papers) {
            const rows = renderPaper(paper, isExport);
            for (const r of rows) frag.appendChild(r);
        }
        return frag;
    }

    return { renderPaper, renderBatch, computeTotalCols, getTotalCols: () => totalCols, renderStatus, renderVerifiedBy, renderChangedBy, formatRelevance, getPath, getBool, esc };
})();