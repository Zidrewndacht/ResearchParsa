// static/js/core/papers_store.js
/**
 * Central data store. Holds the full papers array from the server/export,
 * applies local filters and sort, and exposes windowed access for rendering.
 * All filter/sort logic operates on plain data — never on DOM.
 */
const papersStore = (() => {
    // --- State ---
    let allPapers = [];
    let filteredPapers = [];
    let indexById = new Map();

    // --- Load ---
    function load(papers) {
        allPapers = papers;
        indexById = new Map();
        for (let i = 0; i < allPapers.length; i++) {
            indexById.set(String(allPapers[i].id), i);
        }
        filteredPapers = allPapers.slice();
    }

    // --- Accessors ---
    function getAll() { return allPapers; }
    function getFiltered() { return filteredPapers; }
    function getFilteredCount() { return filteredPapers.length; }
    function getAllCount() { return allPapers.length; }
    function getPaperById(id) {
        const idx = indexById.get(String(id));
        return idx !== undefined ? allPapers[idx] : null;
    }

    // --- Filtering ---
    // Pure function: takes a paper and filter state, returns boolean.
    function paperMatchesFilters(paper, state) {
        // state: { searchTerm, hideApproved, triStateStates, inclusionStates,
        //          hideOfftopic, minPageCount, yearFrom, yearTo, isExport }
        const c = paper.classification || {};

        // Export-only server-side mirrors (year, page count, offtopic)
        if (state.isExport) {
            if (state.hideOfftopic) {   // For offtopic, we prefer to keep conflicts visible together with on-topic and unknown:
                const certMap = paper.main_certainty || {};
                const isoCert = certMap['is_offtopic'] || 'solid';
                if (isoCert !== 'conflict' && _getBool(c, 'is_offtopic') === true) return false;
            }
            if (state.minPageCount > 0) {
                const pc = paper.page_count;
                if (pc !== null && pc !== undefined && pc !== '' && parseInt(pc, 10) < state.minPageCount) return false;
            }
            if (state.yearFrom || state.yearTo) {
                const yr = paper.year;
                if (yr === null || yr === undefined) return false;
                if (state.yearFrom && yr < state.yearFrom) return false;
                if (state.yearTo && yr > state.yearTo) return false;
            }
        }

        // Search
        if (state.searchTerm) {
            const haystack = _buildSearchHaystack(paper);
            if (!haystack.includes(state.searchTerm)) return false;
        }

        // Tri-state filters
        const cert = paper.main_certainty || {};
        for (const [key, cfg] of Object.entries(TRI_STATE_FILTERS)) {
            const st = state.triStateStates[key];
            if (st === 'all') continue;
            const certainty = cert[cfg.field] || 'solid';
            const val = _getBool(c, cfg.field);
            // Conflicted fields are "not true" (matches v1.4.4 DOM behavior where ⚠️ ≠ ✔️)
            const isTrue = (val === true) && (certainty !== 'conflict');
            if (st === 'only_true' && !isTrue) return false;
            if (st === 'only_false' && isTrue) return false;
        }

        // Hide approved
        if (state.hideApproved) {
            const cert = paper.main_certainty || {};
            const vCert = cert['verified'] || 'solid';
            const v = paper.verified;
            // Conflicted verified → shows ⚠️ in v1.4.4, not ✔️ → not hidden
            if (vCert !== 'conflict' && (v === 1 || v === true || v === '1' || v === 'true')) return false;
        }

        // Inclusion filters
        const activeGroups = Object.keys(state.inclusionStates).filter(k => state.inclusionStates[k]);
        if (activeGroups.length > 0) {
            let matchesAny = false;
            for (const g of activeGroups) {
                const fields = INCLUSION_FILTERS[g];
                if (!fields) continue;
                for (const fPath of fields) {
                    if (_fieldIsTrue(c, cert, fPath)) { matchesAny = true; break; }
                }
                if (matchesAny) break;
            }
            if (!matchesAny) return false;
                    }

        return true;
        }

    function applyFilters(state) {
        filteredPapers = allPapers.filter(p => paperMatchesFilters(p, state));
    }

    // --- Sorting ---
    // Pure comparator factory. Returns a comparison function.
    function makeComparator(sortBy, direction) {
        const dir = direction === 'DESC' ? -1 : 1;

        return (a, b) => {
            let va = _extractSortValue(a, sortBy);
            let vb = _extractSortValue(b, sortBy);
            let cmp = 0;

            if (va instanceof Date && vb instanceof Date) {
                if (isNaN(va)) cmp = isNaN(vb) ? 0 : 1;
                else if (isNaN(vb)) cmp = -1;
                else cmp = va - vb;
            } else if (typeof va === 'string' && typeof vb === 'string') {
                cmp = va.localeCompare(vb, undefined, { sensitivity: 'base' });
            } else {
                if (va > vb) cmp = 1;
                else if (va < vb) cmp = -1;
            }

            if (cmp === 0) {
                const ia = String(a.id), ib = String(b.id);
                if (ia > ib) cmp = 1;
                else if (ia < ib) cmp = -1;
            }
            return cmp * dir;
        };
    }

    function applySort(sortBy, direction) {
        if (!sortBy) return;
        filteredPapers.sort(makeComparator(sortBy, direction));
    }

    // --- In-place update (after AJAX save) ---
    function updatePaper(id, patch) {
        const idx = indexById.get(String(id));
        if (idx === undefined) return;
        const paper = allPapers[idx];
        Object.assign(paper, patch);
    }

    // --- Helpers ---
    function _getBool(obj, path) {
        if (!obj || !path) return null;
        const keys = path.split('.');
        let cur = obj;
        for (const k of keys) {
            if (cur && typeof cur === 'object' && k in cur) cur = cur[k];
            else return null;
        }
        if (cur === true || cur === 1 || cur === '1' || cur === 'true') return true;
        if (cur === false || cur === 0 || cur === '0' || cur === 'false') return false;
        return null;
    }

    // --- Text-presence awareness ---
    // Builds a Set of paths that are render_type === 'text_presence'
    let _textPresencePaths = null;
    function _getTextPresencePaths() {
        if (_textPresencePaths) return _textPresencePaths;
        _textPresencePaths = new Set();
        for (const group of APP_CONFIG.groups) {
            if (group.filter_type === 'inclusion' || group.filter_type === 'none') {
                for (const fd of group.fields || []) {
                    if (fd.render_type === 'text_presence') {
                        _textPresencePaths.add(`${group.json_path}.${fd.key}`);
                    }
                }
            }
        }
        return _textPresencePaths;
    }

    /**
     * Determines if a classification field should be considered "true".
     * For text_presence fields: non-empty text = true.
     * For boolean fields: standard boolean check.
     */
    function _fieldIsTrue(classification, certaintyMap, path) {
        const cert = (certaintyMap || {})[path] || 'solid';
        if (cert === 'conflict') return false;   // ⚠️ is never "true"
        if (_getTextPresencePaths().has(path)) {
            const val = _getPath(classification, path);
            return !!(val && String(val).trim());
        }
        return _getBool(classification, path) === true;
    }


    function _buildSearchHaystack(paper) {
        let s = ' ' + String(paper.id || '').toLowerCase();
        s += ' ' + (paper.title || '').toLowerCase();
        s += ' ' + (paper.authors || '').toLowerCase();
        s += ' ' + (paper.abstract || '').toLowerCase();
        s += ' ' + (paper.keywords || '').toLowerCase();
        s += ' ' + (paper.user_trace || '').toLowerCase();
        s += ' ' + (paper.journal || '').toLowerCase();
        s += ' ' + (paper.doi || '').toLowerCase();
        s += ' ' + String(paper.year || '').toLowerCase();
        s += ' ' + String(paper.page_count || '').toLowerCase();
        s += ' ' + (paper.type || '').toLowerCase();
        s += ' ' + (paper.deannualized_conference || '').toLowerCase();
        s += ' ' + (paper.issn || '').toLowerCase();
        //useless for search, intentionally left out, below. This is not a regression:
        //s += ' ' + (paper.pages || '').toLowerCase();                     
        // s += ' ' + (paper.volume || '').toLowerCase();                   
        // s += ' ' + (paper.month || '').toLowerCase();                    
        // s += ' ' + String(paper.estimated_score ?? '').toLowerCase();    
        // s += ' ' + (paper.verified_by || '').toLowerCase();              
        // s += ' ' + (paper.changed_by || '').toLowerCase();               
        // s += ' ' + (paper.changed_formatted || '').toLowerCase();        
        // s += ' ' + (paper.pdf_state || '').toLowerCase();                
        // relevance lives in classification
        const c = paper.classification || {};
        const rel = _getPath(c, 'relevance');
        if (rel !== null && rel !== undefined) s += ' ' + String(rel).toLowerCase();
        // editable field hidden values
        for (const field of APP_CONFIG.editable_fields || []) {
            const v = _getPath(c, field.json_path);
            if (v) s += ' ' + String(v).toLowerCase();
        }
        return s;
    }

    function _getPath(obj, path) {
        if (!obj || !path) return null;
        const keys = path.split('.');
        let cur = obj;
        for (const k of keys) {
            if (cur && typeof cur === 'object' && k in cur) cur = cur[k];
            else return null;
        }
        return cur;
    }

    function _extractSortValue(paper, sortBy) {
        const c = paper.classification || {};
        const cert = paper.main_certainty || {};

        switch (sortBy) {
            case 'changed': {
                const txt = paper.changed_formatted || '';
                const m = txt.match(/(\d{2})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
                return m ? new Date(2000 + +m[3], +m[2] - 1, +m[1], +m[4], +m[5], +m[6]) : new Date(NaN);
            }
            case 'year': return paper.year || 0;
            case 'page_count': return parseInt(paper.page_count, 10) || 0;
            case 'estimated_score': return paper.estimated_score || 0;
            case 'user_override_count': return paper.user_override_count || 0;
            case 'relevance': return parseFloat(_getPath(c, 'relevance')) || 0;
            case 'pdf-link': {
                const st = paper.pdf_state;
                if (st === 'annotated') return 3;
                if (st === 'PDF') return 2;
                if (st === 'none') return 1;
                return 0; // paywalled
            }
            case 'verified_by': {
                const vb = paper.verified_by;
                if (vb === 'user') return 2;
                if (!vb || vb === '') return 1;
                return 0;
            }
            case 'changed_by': {
                const cb = paper.changed_by;
                if (cb === 'user') return 2;
                if (!cb || cb === '') return 1;
                return 0;
            }
            case 'type': return (paper.type || '').toLowerCase();
            case 'user_comment_state': {
                const has = paper.user_trace && String(paper.user_trace).trim();
                return has ? 2 : 0;
            }
            case 'journal': return (paper.deannualized_conference || paper.journal || '').toLowerCase();
            case 'title': return (paper.title || '').toLowerCase();
            default: {
                // Editable status sort (tri-state / inclusion boolean / text-presence fields)
                // For text_presence fields: non-empty text = ✔️ (true), empty/null = ❌ (false)
                let val;
                if (_getTextPresencePaths().has(sortBy)) {
                    const textVal = _getPath(c, sortBy);
                    val = !!(textVal && String(textVal).trim());
                } else {
                    val = _getBool(c, sortBy);
                }
                const certainty = cert[sortBy] || 'solid';
                if (certainty === 'conflict') return 3.25;
                const base = val === true ? 2 : (val === false ? 1 : 0);
                const certBonus = certainty === 'solid' ? 0 :
                                  certainty === '80' ? -0.25 :
                                  certainty === '60' ? -0.5 : -0.75;
                return base * 2 + certBonus;
            }
        }
    }

    return {
        load, getAll, getFiltered, getFilteredCount, getAllCount,
        getPaperById, applyFilters, applySort, updatePaper,
        paperMatchesFilters, makeComparator,
        fieldIsTrue: _fieldIsTrue
    };
})();