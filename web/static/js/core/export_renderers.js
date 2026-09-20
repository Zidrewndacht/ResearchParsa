// static/js/core/export_renderers.js
/**
 * Client-side renderers for detail and history content in HTML exports.
 * In the live app these are fetched from /get_detail_row and /get_history_row.
 * In exports, we render from embedded data.
 */
const exportRenderers = (() => {

    function renderDetailContent(paper) {
        const c = paper.classification || {};
        const esc = tableRenderer.esc;
        const getPath = tableRenderer.getPath;

        // BibTeX generation (simplified client-side)
        const bibtex = _generateBibtex(paper);

        let keywordsHtml = '';
        if (paper.keywords) {
            keywordsHtml = paper.keywords.split(';')
                .map(k => k.trim()).filter(Boolean)
                .map(k => `<span class="clickable-item" data-search-field="keywords" data-search-term="${esc(k)}">${esc(k)};</span>`)
                .join('');
        }

        let authorsHtml = '';
        if (paper.authors) {
            authorsHtml = paper.authors.split(';')
                .map(a => a.trim()).filter(Boolean)
                .map(a => `<span class="clickable-item" data-search-field="authors" data-search-term="${esc(a)}">${esc(a)};</span>`)
                .join('');
        }

        // Build form fields
        let formFieldsHtml = '';
        for (const field of APP_CONFIG.editable_fields || []) {
            const val = getPath(c, field.json_path) || '';
            formFieldsHtml += `<label>${esc(field.label)}:
                <input type="text" class="editable" name="${esc(field.json_path)}" value="${esc(val)}" disabled>
            </label>`;
        }

        const abstract = paper.abstract || 'No abstract available.';

        return `
        <div class="detail-flex-container">
          <div class="detail-content detail-abstract">
            <div class="id-section">
              <strong>ID:</strong> ${esc(paper.id)}
              <button type="button" class="id-cite-btn" onclick="copyPaperId('${esc(paper.id)}', this, 'cite')" title="Copy as \\cite{}"><em>\\cite</em></button>
              <button type="button" class="id-citen-btn" onclick="copyPaperId('${esc(paper.id)}', this, 'citen')" title="Copy as \\citeN{}"><em>\\citeN</em></button>
              <button type="button" class="id-copy-btn" onclick="copyPaperId('${esc(paper.id)}', this, 'raw')" title="Copy as plain text">Copy</button>
            </div>
            <p><strong>Abstract:</strong> ${esc(abstract)}</p>
          </div>
          <div class="detail-content detail-metadata">
            <div class="bibtex-section">
              <strong>BibTeX Citation:</strong>
              <button type="button" class="bibtex-copy-btn" onclick="copyBibtex(this.closest('.bibtex-section').querySelector('.bibtex-pre').textContent, this)">Copy</button>
              <pre class="bibtex-pre">${esc(bibtex)}</pre>
            </div>
            <div class="searchable-section">
              <span style="font-size:0.8em; color: var(--light-colored-btn-text);">Click on any keyword or author below to <strong>search</strong> for it:</span>
              <p><strong>Keywords:</strong> <span class="clickable-keywords">${keywordsHtml}</span></p>
              <p><strong>Authors:</strong> <span class="clickable-authors">${authorsHtml}</span></p>
            </div>
            <p>
              <strong>DOI:</strong> ${paper.doi ? `<a href="https://doi.org/${esc(paper.doi)}" target="_blank">${esc(paper.doi)}</a>` : ''}<br>
              <strong>ISSN:</strong> ${esc(paper.issn || 'None')}
              <strong> — Page Range/Start:</strong> ${esc(paper.pages || '')}
            </p>
          </div>
          <div class="edit-section detail-edit">
            <form id="form-${esc(paper.id)}" data-paper-id="${esc(paper.id)}">
              ${formFieldsHtml}
              <label>Page count:
                <input type="text" class="editable" name="page_count" value="${esc(paper.page_count ?? '')}" disabled>
              </label>
              <label>Relevance:
                <input type="text" class="editable" name="relevance" value="${esc(getPath(c, 'relevance') ?? '')}" placeholder="0 - 10" disabled>
              </label>
              <label>User comments:
                <textarea class="editable" name="user_trace" disabled>${esc(paper.user_trace || '')}</textarea>
              </label>
            </form>
          </div>
        </div>`;
    }

    function renderHistoryContent(paper) {
        const esc = tableRenderer.esc;
        const renderStatus = tableRenderer.renderStatus;
        const renderChangedBy = tableRenderer.renderChangedBy;
        const renderVerifiedBy = tableRenderer.renderVerifiedBy;
        const getPath = tableRenderer.getPath;
        const getBool = tableRenderer.getBool;

        const logSets = [
            { entries: paper.llm_log_entries || [], tab: 'main', label: 'Main', showCertainty: true },
            { entries: paper.set_1_llm_log_entries || [], tab: 'set1', label: 'Set 1', showCertainty: false },
            { entries: paper.set_2_llm_log_entries || [], tab: 'set2', label: 'Set 2', showCertainty: false },
            { entries: paper.set_3_llm_log_entries || [], tab: 'set3', label: 'Set 3', showCertainty: false },
        ];

        let tabsHtml = '';
        let panelsHtml = '';

        for (const ls of logSets) {
            const activeClass = ls.tab === 'main' ? ' active' : '';
            tabsHtml += `<button class="history-tab-btn${activeClass}" data-tab="${ls.tab}" data-paper-id="${esc(paper.id)}" onclick="switchHistoryTab(this)"><span>${ls.label} <span class="arrow">▼</span></span></button>`;

            // Trace panel
            let traceHtml = '';
            if (ls.entries.length > 0) {
                for (const entry of ls.entries) {
                    const typeClass = `log-type-${entry.type || 'unknown'}`;
                    const ts = _formatTimestamp(entry.timestamp);
                    const model = entry.type !== 'user' ? `<span class="log-model">Model: ${esc(entry.model || '')}</span>` : '';
                    const validHtml = entry.valid
                        ? '<span class="valid-indicator valid">✓ Valid</span>'
                        : `<span class="valid-indicator invalid" title="${esc(entry.invalid_reason || '')}">✗ Invalid</span>`;

                    let contentHtml = '';
                    if (entry.type === 'trace_review') {
                        const report = (entry.output || {}).report || '';
                        contentHtml = `<div class="trace-review-report"><pre>${esc(report)}</pre></div>`;
                        if (entry.trace) {
                            contentHtml += `<details class="trace-review-thinking"><summary>Show thinking trace</summary><div class="log-trace"><pre>${esc(entry.trace)}</pre></div></details>`;
                        }
                    } else {
                        if (entry.trace) {
                            contentHtml += `<div class="log-trace"><pre>${esc(entry.trace)}</pre></div>`;
                        }
                        if (entry.verification_data) {
                            const vd = entry.verification_data;
                            const vStatus = vd.verified === 1 ? '✓ Approved' : (vd.verified === 0 ? '✗ Rejected' : '❔ Unknown');
                            contentHtml += `<div class="log-verification-summary"><strong>Verification:</strong> ${vStatus}`;
                            if (vd.estimated_score !== null && vd.estimated_score !== undefined) {
                                contentHtml += ` | Score: ${vd.estimated_score}`;
                            }
                            contentHtml += '</div>';
                        }
                    }

                    traceHtml += `<div class="log-entry ${typeClass}">
                        <div class="log-header">
                            <span class="log-timestamp">${esc(ts)}</span>
                            <span class="log-type">${entry.type === 'trace_review' ? 'Agent Trace Review' : _capitalize(entry.type || '')}</span>
                            ${model}
                            <span class="log-validity">${validHtml}</span>
                        </div>
                        ${contentHtml}
                    </div>`;
                }
            } else {
                traceHtml = '<div class="log-entry log-type-user"><p>No classification data.</p></div>';
            }

            // History table
            let tableRowsHtml = '';
            for (const entry of ls.entries) {
                if (!['classifier', 'consensus', 'averaged_llm', 'user', 'screener'].includes(entry.type)) continue;
                if (!entry.valid) continue;
                const data = entry.output || {};
                
                // FIX: Changed from `new Set()` to `[]` so it matches the Array methods below
                const changed = entry.changed_fields || []; 
                
                const cert = ls.showCertainty ? (entry.certainty_map || {}) : {};

                tableRowsHtml += _buildHistoryTableRow(data, changed, cert, entry, ls.showCertainty);
            }

            const ns_total = _countDynamicCols();
            const historyTableWidth = 378 + ns_total * 27;

            panelsHtml += `
            <div class="history-tab-panel${activeClass}" data-tab-panel="${ls.tab}" data-paper-id="${esc(paper.id)}">
              <div class="trace-content">${traceHtml}</div>
              <div id="history-table-wrapper">
                <table class="history-table">
                  <colgroup>
                    <col style="width:27px;"><col style="width:27px;">
                    ${_buildDynamicCols()}
                    <col style="width:56px;"><col style="width:40px;"><col style="width:27px;">
                    <col style="width:32px;"><col style="width:27px;">
                  </colgroup>
                  <tbody>${tableRowsHtml}</tbody>
                </table>
              </div>
              ${ls.tab === 'main' ? `
              <div class="history-info">
                <div style="text-align:center">
                  <span>History sorted from <b>newest</b> to <b>oldest</b>.</span><br><br>
                  <span>Highlights identify cells changed between runs.</span><br>
                  <span>⚠️ indicates conflicting classifications across the 3 sets.</span><br>
                  <span>Translucent emojis indicate partial agreement.</span>
                </div>
              </div>` : ''}
            </div>`;
        }

        return `
        <div class="history-flex-container" style="--history-table-width: ${378 + _countDynamicCols() * 27}px;">
          <div class="history-tabs-nav">${tabsHtml}</div>
          <div class="history-tabs-content">${panelsHtml}</div>
        </div>`;
    }

    function _buildHistoryTableRow(data, changed, cert, entry, showCertainty) {
        const renderStatus = tableRenderer.renderStatus;
        const renderChangedBy = tableRenderer.renderChangedBy;
        const renderVerifiedBy = tableRenderer.renderVerifiedBy;
        const getPath = tableRenderer.getPath;
        const getBool = tableRenderer.getBool;
        const esc = tableRenderer.esc;

        function cellClass(path) {
            const certainty = cert[path] || 'solid';
            // FIX: Array uses .includes()
            const changedClass = changed.includes(path) ? ' cell-changed' : ''; 
            return `certainty-${certainty}${changedClass}`;
        }

        function statusCell(path) {
            const certainty = cert[path] || 'solid';
            if (certainty === 'conflict') {
                return `<td class="status-cell ${cellClass(path)}"><span class="conflict-warning">⚠️</span></td>`;
            }
            return `<td class="status-cell ${cellClass(path)}"><span class="emoji-content">${renderStatus(getBool(data, path))}</span></td>`;
        }

        let cells = '';
        // Off-topic
        cells += statusCell('is_offtopic');
        
        // Relevance
        // FIX: .includes()
        const relChanged = changed.includes('relevance') ? ' cell-changed' : ''; 
        const relVal = data.relevance !== null && data.relevance !== undefined ? tableRenderer.formatRelevance(data.relevance) : '';
        cells += `<td class="secondary-text-cell number-cell${relChanged}">${relVal}</td>`;

        // Dynamic domain cells
        for (const group of APP_CONFIG.groups) {
            if (group.filter_type === 'tri_state') {
                cells += statusCell(group.json_path);
            } else if (group.filter_type === 'inclusion' || group.filter_type === 'none') {
                for (const fd of group.fields || []) {
                    const path = `${group.json_path}.${fd.key}`;
                    if (fd.render_type === 'text_presence') {
                        const tv = getPath(data, path);
                        // FIX: .includes()
                        const changedClass = changed.includes(path) ? ' cell-changed' : ''; 
                        cells += `<td class="status-cell ${cellClass(path)}"><span class="emoji-content">${(tv && String(tv).trim()) ? '✔️' : '❌'}</span></td>`;
                    } else {
                        cells += statusCell(path);
                    }
                }
            }
        }

        // Timestamp
        const ts = _formatTimestamp(entry.timestamp);
        cells += `<td class="secondary-text-cell changed-cell">${esc(ts)}</td>`;
        // Changed by
        cells += `<td class="status-cell changed-by-cell">${renderChangedBy(entry.model || entry.type)}</td>`;

        // Verified / Score / Verified by
        if (['averaged_llm', 'screener'].includes(entry.type)) {
            cells += statusCell('verified');
            // FIX: .includes()
            const esChanged = changed.includes('estimated_score') ? ' cell-changed' : ''; 
            cells += `<td class="secondary-text-cell number-cell${esChanged}">${data.estimated_score ?? ''}</td>`;
            cells += `<td class="status-cell">${data.verified !== null && data.verified !== undefined ? '🖥️' : '❔'}</td>`;
        } else if (entry.type === 'user') {
            // FIX: .includes()
            cells += `<td class="status-cell${changed.includes('verified') ? ' cell-changed' : ''}"><span class="emoji-content">${renderStatus(data.verified)}</span></td>`;
            // FIX: .includes()
            cells += `<td class="secondary-text-cell number-cell${changed.includes('estimated_score') ? ' cell-changed' : ''}">${data.estimated_score ?? ''}</td>`;
            cells += `<td class="status-cell">${renderVerifiedBy(data.verified_by || '')}</td>`;
        } else if (entry.verification_data) {
            const vd = entry.verification_data;
            cells += `<td class="status-cell"><span class="emoji-content">${renderStatus(vd.verified)}</span></td>`;
            cells += `<td class="secondary-text-cell number-cell">${vd.estimated_score ?? ''}</td>`;
            cells += `<td class="status-cell">${renderVerifiedBy(vd.verifier_model || '')}</td>`;
        } else {
            cells += '<td class="status-cell">❔</td><td class="secondary-text-cell number-cell"></td><td class="status-cell">❔</td>';
        }

        return `<tr>${cells}</tr>`;
    }
    

    function _countDynamicCols() {
        let n = 0;
        for (const g of APP_CONFIG.groups) {
            if (g.filter_type === 'tri_state') n++;
            else if (g.filter_type === 'inclusion' || g.filter_type === 'none') n += (g.fields || []).length;
        }
        return n;
    }

    function _buildDynamicCols() {
        let html = '';
        for (const g of APP_CONFIG.groups) {
            if (g.filter_type === 'tri_state') html += '<col style="width:27px;">';
            else if (g.filter_type === 'inclusion' || g.filter_type === 'none') {
                for (const f of g.fields || []) html += '<col style="width:27px;">';
            }
        }
        return html;
    }

    function _formatTimestamp(ts) {
        if (!ts) return '';
        try {
            const dt = new Date(ts.replace('Z', '+00:00'));
            const pad = n => String(n).padStart(2, '0');
            return `${pad(dt.getDate())}/${pad(dt.getMonth() + 1)}/${String(dt.getFullYear()).slice(2)} ${pad(dt.getHours())}:${pad(dt.getMinutes())}:${pad(dt.getSeconds())}`;
        } catch { return ts; }
    }

    function _capitalize(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''; }

    function _generateBibtex(paper) {
        const type = (paper.type || 'misc').toLowerCase();
        const key = paper.id;
        const lines = [`@${type}{${key},`];
        if (paper.title) lines.push(`  title = {${paper.title}},`);
        if (paper.authors) {
            const authorsFormatted = paper.authors.split(';').map(a => a.trim()).join(' and ');
            lines.push(`  author = {${authorsFormatted}},`);
        }
        if (paper.year) lines.push(`  year = {${paper.year}},`);
        if (paper.journal) {
            if (type === 'inproceedings' || type === 'conference') lines.push(`  booktitle = {${paper.journal}},`);
            else lines.push(`  journal = {${paper.journal}},`);
        }
        if (paper.pages) lines.push(`  pages = {${paper.pages.replace(/\s*[-–—]\s*/, '--')}},`);
        if (paper.doi) lines.push(`  doi = {${paper.doi}},`);
        if (paper.issn) lines.push(`  issn = {${paper.issn}},`);
        if (paper.keywords) {
            const kw = paper.keywords.split(';').map(k => k.trim()).join(', ');
            lines.push(`  keywords = {${kw}},`);
        }
        if (lines.length > 1) lines[lines.length - 1] = lines[lines.length - 1].replace(/,$/, '');
        lines.push('}');
        return lines.join('\n');
    }

    return { renderDetailContent, renderHistoryContent };
})();