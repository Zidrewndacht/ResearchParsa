// static/js/stats/stats_core.js
let latestCounts = {};
let latestYearlyData = {};
let isStacked = false;
let isCumulative = false;
let showPieCharts = false;

const PUB_TYPE_MAP = {
    'article': 'Journal', 'inproceedings': 'Conference', 'proceedings': 'Conference',
    'conference': 'Conference', 'techreport': 'Report', 'book': 'Book',
    'mastersthesis': 'Thesis', 'phdthesis': 'Thesis'
};

function mapPubType(type) {
    if (!type) return 'Other';
    return PUB_TYPE_MAP[type.toLowerCase().trim()] || type;
}

function calculateCumulativeData(originalDataArray) {
    if (!originalDataArray || originalDataArray.length === 0) return [];
    const cumulativeData = [];
    let sum = 0;
    for (let i = 0; i < originalDataArray.length; i++) {
        sum += originalDataArray[i];
        cumulativeData.push(sum);
    }
    return cumulativeData;
}

const statsHooks = { collectData: [], renderCharts: [] };
function registerStatsHook(hookName, fn) {
    if (!statsHooks[hookName]) statsHooks[hookName] = [];
    statsHooks[hookName].push(fn);
}

function updateCounts() {
    const counts = {};
    APP_CONFIG.groups.forEach(group => {
        if (group.filter_type === 'tri_state') counts[group.json_path] = 0;
        else if (['inclusion', 'none'].includes(group.filter_type)) {
            group.fields.forEach(f => counts[`${group.json_path}.${f.key}`] = 0);
        }
    });
    Object.assign(counts, { 
        pdf_present: 0, pdf_annotated: 0, pdf_paywalled: 0, 
        is_offtopic: 0, verified: 0, changed_by: 0, verified_by: 0, 
        user_comment_state: 0, model: 0 
    });

    const papers = papersStore.getFiltered();
    const visiblePaperCount = papers.length;
    const loadedPaperCount = papersStore.getAllCount();
    const yearlySurveyImpl = {};
    const yearlyPubTypes = {};

    for (const paper of papers) {
        const c = paper.classification || {};
        
        if (paper.pdf_state === 'PDF' || paper.pdf_state === 'annotated') {
            counts.pdf_present++;
            if (paper.pdf_state === 'annotated') counts.pdf_annotated++;
        } else if (paper.pdf_state === 'paywalled') counts.pdf_paywalled++;

        if (tableRenderer.getBool(c, 'is_offtopic') === true) counts.is_offtopic++;
        if (paper.verified === 1 || paper.verified === true) counts.verified++;
        if (paper.changed_by === 'user') counts.changed_by++;
        if (paper.verified_by === 'user') counts.verified_by++;
        if (paper.user_trace && String(paper.user_trace).trim()) counts.user_comment_state++;

        APP_CONFIG.groups.forEach(group => {
            if (group.filter_type === 'tri_state') {
                if (papersStore.fieldIsTrue(c, paper.main_certainty, group.json_path)) counts[group.json_path]++;
            } else if (['inclusion', 'none'].includes(group.filter_type)) {
                group.fields.forEach(f => {
                    if (papersStore.fieldIsTrue(c, paper.main_certainty, `${group.json_path}.${f.key}`)) counts[`${group.json_path}.${f.key}`]++;
                });
            }
        });

        const modelVal = tableRenderer.getPath(c, 'technique.model') || tableRenderer.getPath(c, 'model') || tableRenderer.getPath(c, 'model_name');
        if (modelVal) counts.model += String(modelVal).split(/[,;]/).map(m => m.trim()).filter(m => m !== '').length;

        const year = paper.year;
        if (year && !isNaN(year)) {
            if (!yearlySurveyImpl[year]) yearlySurveyImpl[year] = { surveys: 0, impl: 0 };
            if (!yearlyPubTypes[year]) yearlyPubTypes[year] = {};
            const isSurvey = papersStore.fieldIsTrue(c, paper.main_certainty, 'is_survey');
            isSurvey ? yearlySurveyImpl[year].surveys++ : yearlySurveyImpl[year].impl++;
            const rawType = (paper.type || '').toLowerCase();
            if (rawType) {
                const mappedType = mapPubType(rawType);
                yearlyPubTypes[year][mappedType] = (yearlyPubTypes[year][mappedType] || 0) + 1;
            }
        }
    }

    latestCounts = counts;
    latestYearlyData = { surveyImpl: yearlySurveyImpl, pubTypes: yearlyPubTypes };

    if (document.body.id === 'html-export') {
        const visibleCountCell = document.getElementById('visible-count-cell');
        if (visibleCountCell) visibleCountCell.innerHTML = `<strong>${visiblePaperCount}</strong> paper${visiblePaperCount !== 1 ? 's' : ''}`;
    } else {
        const loadedEl = document.getElementById('loaded-papers-count');
        const visibleEl = document.getElementById('visible-papers-count');
        if (loadedEl) loadedEl.textContent = loadedPaperCount;
        if (visibleEl) visibleEl.textContent = visiblePaperCount;
    }

    const updateCountCell = (field, count) => {
        const cell = document.querySelector(`[data-count-field="${field}"]`) || document.getElementById(`count-${field.replace(/\./g, '_')}`);
        if (!cell) return;
        if (field === 'pdf_present') {
            cell.textContent = counts.pdf_present;
            cell.title = `Stored PDFs: ${counts.pdf_present}, Annotated: ${counts.pdf_annotated}, Paywalled: ${counts.pdf_paywalled}.`;
        } else {
            cell.textContent = count;
        }
    };
    updateCountCell('pdf_present', counts.pdf_present);
    updateCountCell('is_offtopic', counts.is_offtopic);
    updateCountCell('verified', counts.verified);
    updateCountCell('changed_by', counts.changed_by);
    updateCountCell('verified_by', counts.verified_by);
    updateCountCell('user_comment_state', counts.user_comment_state);
    APP_CONFIG.groups.forEach(group => {
        if (group.filter_type === 'tri_state') updateCountCell(group.json_path, counts[group.json_path]);
        else if (['inclusion', 'none'].includes(group.filter_type)) {
            group.fields.forEach(f => updateCountCell(`${group.json_path}.${f.key}`, counts[`${group.json_path}.${f.key}`]));
        }
    });
}

function displayStats() {
    document.documentElement.classList.add('busyCursor');
    setTimeout(() => {
        updateCounts();
        const papers = papersStore.getFiltered();
        statsHooks.collectData.forEach(fn => fn(papers));
        destroyAllCharts();
        Chart.defaults.font = { size: 12.5, family: 'Arial Narrow', weight: '300' };
        statsHooks.renderCharts.forEach(fn => fn());
        document.getElementById('statsModal').offsetHeight;
        document.getElementById('statsModal').classList.add('modal-active');
        document.documentElement.classList.remove('busyCursor');
    }, 250);
}

function displayAbout() { document.getElementById('aboutModal').offsetHeight; document.getElementById('aboutModal').classList.add('modal-active'); }
function closeSmallModal() { document.getElementById('aboutModal').classList.remove('modal-active'); }
function closeModal() { document.getElementById('statsModal').classList.remove('modal-active'); }

document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('stackingToggle').checked = false;
    document.getElementById('cumulativeToggle').checked = false;
    document.getElementById('pieToggle').checked = false;
    document.getElementById('stats-btn').addEventListener('click', function () { document.documentElement.classList.add('busyCursor'); displayStats(); });
    document.getElementById('about-btn').addEventListener('click', displayAbout);
    document.querySelector('#statsModal .close').addEventListener('click', closeModal);
    document.querySelector('#aboutModal .close').addEventListener('click', closeSmallModal);
    document.getElementById('stackingToggle').addEventListener('change', function () {
        isStacked = this.checked;
        Object.values(window.chartRegistry).forEach(chart => {
            if (chart.options.scales?.y) { chart.options.scales.y.stacked = isStacked; chart.options.scales.x.stacked = isStacked; }
            chart.data.datasets.forEach(dataset => { dataset.fill = isStacked; });
            chart.update();
        });
        reorderDatasetsForStacking();
    });
    document.getElementById('cumulativeToggle').addEventListener('change', function () {
        isCumulative = this.checked;
        statsHooks.renderCharts.forEach(fn => fn());
        if (isStacked) reorderDatasetsForStacking();
    });
    document.getElementById('pieToggle').addEventListener('change', function () {
        showPieCharts = this.checked;
        statsHooks.renderCharts.forEach(fn => fn());
    });
    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            closeModal(); closeSmallModal();
            if (document.body.id !== "html-export") {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
                if (typeof closeImportModal === 'function') closeImportModal();
            }
        }
        if (event.key === 'F1') { event.preventDefault(); displayAbout(); }
        if (event.key === 'F3') { event.preventDefault(); searchInput.focus(); }
        if (event.key === 'F4') {
            event.preventDefault(); document.documentElement.classList.add('busyCursor'); closeSmallModal();
            if (document.body.id !== "html-export") {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
                if (typeof closeImportModal === 'function') closeImportModal();
            }
            displayStats();
        }
    });
    window.addEventListener('click', function (event) {
        if (event.target === document.getElementById('statsModal') || event.target === document.getElementById('aboutModal')) { closeModal(); closeSmallModal(); }
        if (document.body.id !== 'html-export') {
            const batchModal = document.getElementById("batchModal");
            const importModal = document.getElementById("importModal");
            const exportModal = document.getElementById("exportModal");
            if (event.target === batchModal || event.target === importModal || event.target === exportModal) {
                if (typeof closeBatchModal === 'function') closeBatchModal();
                if (typeof closeImportModal === 'function') closeImportModal();
                if (typeof closeExporthModal === 'function') closeExporthModal();
            }
        }
    });
});