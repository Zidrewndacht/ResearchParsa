// static/js/stats/stats_domain.js
/**
 * Domain-specific statistics logic (SLR/SMS Automation).
 */
registerStatsHook('collectData', collectDomainYearlyData);
registerStatsHook('renderCharts', renderDomainCharts);

// --- Color Definitions ---
// Fills reuse the original palette's lightness range (~47–72%) so the
// black (#444) datalabels counters stay legible; dark tones are kept for
// borders / line charts only.
const techniquesColors = [
    'hsla(347, 60%, 69%, 0.95)', 'hsla(204, 62%, 57%, 0.95)', 'hsla(52, 80%, 47%, 0.95)',
    'hsla(180, 32%, 52%, 0.95)', 'hsla(260, 60%, 66%, 0.95)', 'hsla(25, 70%, 63%, 0.95)',
    'hsla(0, 0%, 68%, 0.95)'
];
const techniquesBorderColors = [
    'hsla(347, 70%, 39%, 0.75)', 'hsla(204, 82%, 28%, 0.75)', 'hsla(42, 100%, 28%, 0.75)',
    'hsla(180, 48%, 28%, 0.75)', 'hsla(260, 100%, 40%, 0.75)', 'hsla(30, 100%, 33%, 0.75)',
    'hsla(0, 0%, 38%, 0.75)'
];
// Kitchenham stages: each pair shares its group's hue, exactly like the
// original features palette (members of a color group share one color).
// Group base indices (0, 2, 4, 6) = blue / green / pink / purple.
const stagesColorsOriginalOrder = [
    'hsla(204, 88%, 70%, 0.95)', 'hsla(204, 88%, 70%, 0.95)',
    'hsla(130, 27%, 60%, 0.95)', 'hsla(130, 27%, 60%, 0.95)',
    'hsla(347, 70%, 72%, 0.95)', 'hsla(347, 70%, 72%, 0.95)',
    'hsla(284, 88%, 70%, 0.95)', 'hsla(284, 88%, 70%, 0.95)'
];
const stagesBorderColorsOriginalOrder = [
    'hsla(219, 100%, 40%, 0.75)', 'hsla(219, 100%, 40%, 0.75)',
    'hsla(144, 83%, 28%, 0.75)', 'hsla(144, 83%, 28%, 0.75)',
    'hsla(347, 70%, 39%, 0.75)', 'hsla(347, 70%, 39%, 0.75)',
    'hsla(284, 82%, 47%, 0.75)', 'hsla(284, 82%, 47%, 0.75)'
];
const stageDetailsColors = [
    'hsla(204, 62%, 57%, 0.95)', 'hsla(180, 32%, 52%, 0.95)', 'hsla(260, 60%, 66%, 0.95)',
    'hsla(25, 70%, 63%, 0.95)', 'hsla(0, 0%, 68%, 0.95)'
];
const stageDetailsBorderColors = [
    'hsla(204, 82%, 28%, 0.75)', 'hsla(180, 48%, 28%, 0.75)', 'hsla(260, 100%, 40%, 0.75)',
    'hsla(30, 100%, 33%, 0.75)', 'hsla(0, 0%, 38%, 0.75)'
];
const smsSpecificColors = [
    'hsla(284, 88%, 70%, 0.95)', 'hsla(260, 60%, 66%, 0.95)',
    'hsla(347, 60%, 69%, 0.95)', 'hsla(52, 80%, 47%, 0.95)'
];
const smsSpecificBorderColors = [
    'hsla(284, 82%, 47%, 0.75)', 'hsla(260, 100%, 40%, 0.75)',
    'hsla(347, 70%, 39%, 0.75)', 'hsla(42, 100%, 28%, 0.75)'
];

// --- Field Mappings ---
const FIELD_LABELS = {
    'review_focus.slr': 'SLR Focus', 'review_focus.sms': 'SMS Focus',
    'automation.kitchenham_stages.planning_protocol': 'Planning/Protocol',
    'automation.kitchenham_stages.identification_of_research': 'Search/Identification',
    'automation.kitchenham_stages.selection_of_studies': 'Selection',
    'automation.kitchenham_stages.quality_assessment': 'Quality Assessment',
    'automation.kitchenham_stages.data_extraction': 'Data Extraction',
    'automation.kitchenham_stages.data_synthesis': 'Data Synthesis',
    'automation.kitchenham_stages.reporting_dissemination': 'Reporting',
    'automation.kitchenham_stages.living_update': 'Living/Update',
    'automation.stage_details.query_generation': 'Query Generation',
    'automation.stage_details.citation_chasing': 'Citation Chasing',
    'automation.stage_details.deduplication': 'Deduplication',
    'automation.stage_details.title_abstract_screening': 'TI/AB Screening',
    'automation.stage_details.full_text_screening': 'Full-Text Screening',
    'automation.sms_specific.keywording_topic_modeling': 'Keyword/Topic Modeling',
    'automation.sms_specific.classification_scheme': 'Classification Scheme',
    'automation.sms_specific.mapping_visualization': 'Mapping/Visualization',
    'automation.sms_specific.bibliometric_analysis': 'Bibliometric Analysis',
    'technique.rule_based': 'Rule-Based',
    'technique.traditional_ml': 'Traditional ML',
    'technique.deep_learning': 'Deep Learning',
    'technique.llm_or_transformer': 'LLM/Transformer',
    'technique.information_retrieval': 'IR/Search',
    'technique.active_learning_or_human_loop': 'Active/HITL',
    'technique.hybrid': 'Hybrid',
    'technique.available_dataset': 'Datasets',
    'technique.available_code': 'Code'
};

const TECHNIQUE_FIELDS = [
    'technique.rule_based', 'technique.traditional_ml', 'technique.deep_learning',
    'technique.llm_or_transformer', 'technique.information_retrieval',
    'technique.active_learning_or_human_loop', 'technique.hybrid'
];
const TECHNIQUE_FIELD_COLOR_MAP = {
    'technique.rule_based': 0, 'technique.traditional_ml': 1, 'technique.deep_learning': 2,
    'technique.llm_or_transformer': 3, 'technique.information_retrieval': 4,
    'technique.active_learning_or_human_loop': 5, 'technique.hybrid': 6
};

const STAGE_FIELDS = [
    'automation.kitchenham_stages.planning_protocol',
    'automation.kitchenham_stages.identification_of_research',
    'automation.kitchenham_stages.selection_of_studies',
    'automation.kitchenham_stages.quality_assessment',
    'automation.kitchenham_stages.data_extraction',
    'automation.kitchenham_stages.data_synthesis',
    'automation.kitchenham_stages.reporting_dissemination',
    'automation.kitchenham_stages.living_update'
];
const STAGE_FIELD_INDEX_MAP = {
    'automation.kitchenham_stages.planning_protocol': 0,
    'automation.kitchenham_stages.identification_of_research': 1,
    'automation.kitchenham_stages.selection_of_studies': 2,
    'automation.kitchenham_stages.quality_assessment': 3,
    'automation.kitchenham_stages.data_extraction': 4,
    'automation.kitchenham_stages.data_synthesis': 5,
    'automation.kitchenham_stages.reporting_dissemination': 6,
    'automation.kitchenham_stages.living_update': 7
};

const STAGE_DETAIL_FIELDS = [
    'automation.stage_details.query_generation',
    'automation.stage_details.citation_chasing',
    'automation.stage_details.deduplication',
    'automation.stage_details.title_abstract_screening',
    'automation.stage_details.full_text_screening'
];
const STAGE_DETAIL_FIELD_INDEX_MAP = {
    'automation.stage_details.query_generation': 0,
    'automation.stage_details.citation_chasing': 1,
    'automation.stage_details.deduplication': 2,
    'automation.stage_details.title_abstract_screening': 3,
    'automation.stage_details.full_text_screening': 4
};

const SMS_SPECIFIC_FIELDS = [
    'automation.sms_specific.keywording_topic_modeling',
    'automation.sms_specific.classification_scheme',
    'automation.sms_specific.mapping_visualization',
    'automation.sms_specific.bibliometric_analysis'
];
const SMS_SPECIFIC_FIELD_INDEX_MAP = {
    'automation.sms_specific.keywording_topic_modeling': 0,
    'automation.sms_specific.classification_scheme': 1,
    'automation.sms_specific.mapping_visualization': 2,
    'automation.sms_specific.bibliometric_analysis': 3
};

// Stage grouping for the optional grouped view
const stageColorGroups = {
    0: { label: 'Planning & Search', fields: ['automation.kitchenham_stages.planning_protocol', 'automation.kitchenham_stages.identification_of_research'] },
    2: { label: 'Screening & QA', fields: ['automation.kitchenham_stages.selection_of_studies', 'automation.kitchenham_stages.quality_assessment'] },
    4: { label: 'Extraction & Synthesis', fields: ['automation.kitchenham_stages.data_extraction', 'automation.kitchenham_stages.data_synthesis'] },
    6: { label: 'Reporting & Living', fields: ['automation.kitchenham_stages.reporting_dissemination', 'automation.kitchenham_stages.living_update'] }
};

// --- Data Collection Hook ---
function collectDomainYearlyData(papers) {
    const yearlyTechniques = {};
    const yearlyStages = {};
    const yearlyStageDetails = {};
    const yearlySmsSpecific = {};
    const yearlyReviewFocus = {};

    for (const paper of papers) {
        const year = paper.year;
        if (!year || isNaN(year)) continue;
        const c = paper.classification || {};
        const cert = paper.main_certainty || {};

        // Techniques
        if (!yearlyTechniques[year]) {
            yearlyTechniques[year] = {};
            TECHNIQUE_FIELDS.forEach(f => yearlyTechniques[year][f] = 0);
        }
        TECHNIQUE_FIELDS.forEach(field => {
            if (papersStore.fieldIsTrue(c, cert, field)) yearlyTechniques[year][field]++;
        });

        // Kitchenham Stages
        if (!yearlyStages[year]) {
            yearlyStages[year] = {};
            STAGE_FIELDS.forEach(f => yearlyStages[year][f] = 0);
        }
        STAGE_FIELDS.forEach(field => {
            if (papersStore.fieldIsTrue(c, cert, field)) yearlyStages[year][field]++;
        });

        // Stage Details
        if (!yearlyStageDetails[year]) {
            yearlyStageDetails[year] = {};
            STAGE_DETAIL_FIELDS.forEach(f => yearlyStageDetails[year][f] = 0);
        }
        STAGE_DETAIL_FIELDS.forEach(field => {
            if (papersStore.fieldIsTrue(c, cert, field)) yearlyStageDetails[year][field]++;
        });

        // SMS Specific
        if (!yearlySmsSpecific[year]) {
            yearlySmsSpecific[year] = {};
            SMS_SPECIFIC_FIELDS.forEach(f => yearlySmsSpecific[year][f] = 0);
        }
        SMS_SPECIFIC_FIELDS.forEach(field => {
            if (papersStore.fieldIsTrue(c, cert, field)) yearlySmsSpecific[year][field]++;
        });

        // Review Focus (SLR vs SMS)
        if (!yearlyReviewFocus[year]) {
            yearlyReviewFocus[year] = { slr: 0, sms: 0 };
        }
        if (papersStore.fieldIsTrue(c, cert, 'review_focus.slr')) yearlyReviewFocus[year].slr++;
        if (papersStore.fieldIsTrue(c, cert, 'review_focus.sms')) yearlyReviewFocus[year].sms++;
    }

    latestYearlyData.techniques = yearlyTechniques;
    latestYearlyData.stages = yearlyStages;
    latestYearlyData.stageDetails = yearlyStageDetails;
    latestYearlyData.smsSpecific = yearlySmsSpecific;
    latestYearlyData.reviewFocus = yearlyReviewFocus;
}

// ======================================================================
// Distribution chart data preparation
// ======================================================================

function prepareTechniquesData() {
    const counts = latestCounts;
    const techniquesData = TECHNIQUE_FIELDS.map(field => ({
        label: FIELD_LABELS[field] || field, value: counts[field] || 0,
        originalIndex: TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1
    }));
    techniquesData.sort((a, b) => b.value - a.value);
    return {
        labels: techniquesData.map(item => item.label),
        datasets: [{
            label: 'Techniques Count', data: techniquesData.map(item => item.value),
            backgroundColor: techniquesData.map(item => techniquesColors[item.originalIndex] || 'rgba(0,0,0,0.1)'),
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

function prepareStagesData() {
    const counts = latestCounts;
    const stageGroupToggle = document.getElementById('stageGroupToggle');
    const isGrouped = stageGroupToggle && stageGroupToggle.checked;

    if (showPieCharts) {
        let labels = [], values = [], backgroundColors = [];
        if (isGrouped) {
            Object.keys(stageColorGroups).forEach(baseColorIndex => {
                const group = stageColorGroups[baseColorIndex];
                labels.push(group.label);
                let groupSum = 0;
                group.fields.forEach(field => { groupSum += (counts[field] || 0); });
                values.push(groupSum);
                backgroundColors.push(stagesColorsOriginalOrder[parseInt(baseColorIndex)]);
            });
        } else {
            const stagesData = STAGE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                originalIndex: STAGE_FIELD_INDEX_MAP[field] !== undefined ? STAGE_FIELD_INDEX_MAP[field] : -1
            }));
            let processedData = [...stagesData].sort((a, b) => b.value - a.value);
            labels = processedData.map(item => item.label);
            values = processedData.map(item => item.value);
            backgroundColors = processedData.map(item => stagesColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
        }
        return { labels, datasets: [{ label: 'Stages Count', data: values, backgroundColor: backgroundColors, borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
    } else {
        let finalLabels = [], finalValues = [], finalColors = [];
        if (isGrouped) {
            Object.keys(stageColorGroups).forEach(baseColorIndexStr => {
                const baseColorIndex = parseInt(baseColorIndexStr);
                const group = stageColorGroups[baseColorIndex];
                const groupData = group.fields.map(field => ({
                    label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                    originalIndex: STAGE_FIELD_INDEX_MAP[field] !== undefined ? STAGE_FIELD_INDEX_MAP[field] : -1
                }));
                groupData.sort((a, b) => b.value - a.value);
                groupData.forEach(item => {
                    finalLabels.push(item.label);
                    finalValues.push(item.value);
                    finalColors.push(stagesColorsOriginalOrder[baseColorIndex]);
                });
            });
        } else {
            const stagesData = STAGE_FIELDS.map(field => ({
                label: FIELD_LABELS[field] || field, value: counts[field] || 0,
                originalIndex: STAGE_FIELD_INDEX_MAP[field] !== undefined ? STAGE_FIELD_INDEX_MAP[field] : -1
            }));
            let processedData = [...stagesData].sort((a, b) => b.value - a.value);
            finalLabels = processedData.map(item => item.label);
            finalValues = processedData.map(item => item.value);
            finalColors = processedData.map(item => stagesColorsOriginalOrder[item.originalIndex] || 'rgba(0,0,0,0.1)');
        }
        return { labels: finalLabels, datasets: [{ label: 'Stages Count', data: finalValues, backgroundColor: finalColors, borderColor: "#333", borderWidth: 1, hoverOffset: 4 }] };
    }
}

function prepareStageDetailsData() {
    const counts = latestCounts;
    const data = STAGE_DETAIL_FIELDS.map(field => ({
        label: FIELD_LABELS[field] || field, value: counts[field] || 0,
        originalIndex: STAGE_DETAIL_FIELD_INDEX_MAP[field] !== undefined ? STAGE_DETAIL_FIELD_INDEX_MAP[field] : -1
    }));
    data.sort((a, b) => b.value - a.value);
    return {
        labels: data.map(item => item.label),
        datasets: [{
            label: 'Stage Details Count', data: data.map(item => item.value),
            backgroundColor: data.map(item => stageDetailsColors[item.originalIndex] || 'rgba(0,0,0,0.1)'),
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

function prepareSmsSpecificData() {
    const counts = latestCounts;
    const data = SMS_SPECIFIC_FIELDS.map(field => ({
        label: FIELD_LABELS[field] || field, value: counts[field] || 0,
        originalIndex: SMS_SPECIFIC_FIELD_INDEX_MAP[field] !== undefined ? SMS_SPECIFIC_FIELD_INDEX_MAP[field] : -1
    }));
    data.sort((a, b) => b.value - a.value);
    return {
        labels: data.map(item => item.label),
        datasets: [{
            label: 'SMS Specific Count', data: data.map(item => item.value),
            backgroundColor: data.map(item => smsSpecificColors[item.originalIndex] || 'rgba(0,0,0,0.1)'),
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

function prepareSlrVsSmsData() {
    const counts = latestCounts;
    const slrCount = counts['review_focus.slr'] || 0;
    const smsCount = counts['review_focus.sms'] || 0;
    return {
        labels: ['SLR', 'SMS'],
        datasets: [{
            label: 'SLR vs SMS Distribution', data: [slrCount, smsCount],
            backgroundColor: ['hsla(216, 62%, 57%, 0.95)', 'hsla(280, 55%, 60%, 0.95)'],
            borderColor: "#333", borderWidth: 1, hoverOffset: 4
        }]
    };
}

// ======================================================================
// Line chart rendering
// ======================================================================

function renderDomainLineCharts() {
    // --- Techniques per Year ---
    const techniquesYearlyData = latestYearlyData.techniques || {};
    const yearsForTechniques = Object.keys(techniquesYearlyData).map(Number).sort((a, b) => a - b);
    const techniqueLineDatasets = TECHNIQUE_FIELDS.map(field => {
        const label = FIELD_LABELS[field] || field;
        let data = yearsForTechniques.map(year => techniquesYearlyData[year]?.[field] || 0);
        if (isCumulative) data = calculateCumulativeData(data);
        const originalIndex = TECHNIQUE_FIELD_COLOR_MAP[field] !== undefined ? TECHNIQUE_FIELD_COLOR_MAP[field] : -1;
        const borderColor = (originalIndex !== -1 && techniquesBorderColors[originalIndex]) ? techniquesBorderColors[originalIndex] : 'rgba(0, 0, 0, 1)';
        const backgroundColor = (originalIndex !== -1 && techniquesColors[originalIndex]) ? techniquesColors[originalIndex] : 'rgba(0, 0, 0, 0.1)';
        return { label, data, borderColor, backgroundColor, fill: isStacked, tension: 0.25 };
    });

    const techniquesCtx = document.getElementById('techniquesPerYearLineChart')?.getContext('2d');
    destroyChartInstance('techniquesPerYearLineChart');
    if (techniquesCtx && techniqueLineDatasets.length > 0) {
        registerChartInstance('techniquesPerYearLineChart', new Chart(techniquesCtx, {
            type: 'line', data: { labels: yearsForTechniques, datasets: techniqueLineDatasets },
            options: {
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: { legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } }, title: { display: false, text: 'Techniques per Year' }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${context.raw}` } } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 }, stacked: isStacked }, x: { ticks: { precision: 0 }, stacked: isStacked } }
            }
        }));
    } else if (techniquesCtx) {
        registerChartInstance('techniquesPerYearLineChart', new Chart(techniquesCtx, { type: 'line', data: { labels: [], datasets: [] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Techniques per Year (No Data)' } } } }));
    }

    // --- Kitchenham Stages per Year ---
    const stagesYearlyData = latestYearlyData.stages || {};
    const yearsForStages = Object.keys(stagesYearlyData).map(Number).sort((a, b) => a - b);
    const aggregatedStageDataByColor = {};
    Object.keys(stageColorGroups).forEach(baseColorIndex => {
        const group = stageColorGroups[baseColorIndex];
        aggregatedStageDataByColor[group.label] = yearsForStages.map(year => {
            return group.fields.reduce((sum, field) => sum + (stagesYearlyData[year]?.[field] || 0), 0);
        });
    });
    const aggregatedStageDataByColorFinal = {};
    Object.keys(aggregatedStageDataByColor).forEach(label => {
        let data = aggregatedStageDataByColor[label];
        if (isCumulative) data = calculateCumulativeData(data);
        aggregatedStageDataByColorFinal[label] = data;
    });
    const stageLineDatasets = Object.keys(stageColorGroups).map(baseColorIndex => {
        const group = stageColorGroups[baseColorIndex];
        const colorIndex = parseInt(baseColorIndex);
        const borderColor = stagesBorderColorsOriginalOrder[colorIndex] || 'rgba(0,0,0,1)';
        const backgroundColor = stagesColorsOriginalOrder[colorIndex] || 'rgba(0,0,0,0.1)';
        return { label: group.label, data: aggregatedStageDataByColorFinal[group.label], borderColor, backgroundColor, fill: isStacked, tension: 0.25 };
    });

    const stagesCtx = document.getElementById('stagesPerYearLineChart')?.getContext('2d');
    destroyChartInstance('stagesPerYearLineChart');
    if (stagesCtx && stageLineDatasets.length > 0) {
        registerChartInstance('stagesPerYearLineChart', new Chart(stagesCtx, {
            type: 'line', data: { labels: yearsForStages, datasets: stageLineDatasets },
            options: {
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: { legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } }, title: { display: false, text: 'Kitchenham Stages per Year' }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${context.raw}` } } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 }, stacked: isStacked }, x: { ticks: { precision: 0 }, stacked: isStacked } }
            }
        }));
    } else if (stagesCtx) {
        registerChartInstance('stagesPerYearLineChart', new Chart(stagesCtx, { type: 'line', data: { labels: [], datasets: [] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'Kitchenham Stages per Year (No Data)' } } } }));
    }

    // --- SLR vs SMS per Year ---
    const reviewFocusYearlyData = latestYearlyData.reviewFocus || {};
    const yearsForReviewFocus = Object.keys(reviewFocusYearlyData).map(Number).sort((a, b) => a - b);
    let slrData = yearsForReviewFocus.map(year => reviewFocusYearlyData[year]?.slr || 0);
    let smsData = yearsForReviewFocus.map(year => reviewFocusYearlyData[year]?.sms || 0);
    if (isCumulative) {
        slrData = calculateCumulativeData(slrData);
        smsData = calculateCumulativeData(smsData);
    }
    const reviewFocusDatasets = [
        { label: 'SLR', data: slrData, borderColor: 'hsl(216, 62%, 37%)', backgroundColor: 'hsla(216, 62%, 57%, 0.95)', fill: isStacked, tension: 0.25 },
        { label: 'SMS', data: smsData, borderColor: 'hsla(280, 55%, 40%, 1.00)', backgroundColor: 'hsla(280, 55%, 60%, 0.95)', fill: isStacked, tension: 0.25 }
    ];

    const reviewFocusCtx = document.getElementById('reviewFocusPerYearLineChart')?.getContext('2d');
    destroyChartInstance('reviewFocusPerYearLineChart');
    if (reviewFocusCtx && reviewFocusDatasets.length > 0) {
        registerChartInstance('reviewFocusPerYearLineChart', new Chart(reviewFocusCtx, {
            type: 'line', data: { labels: yearsForReviewFocus, datasets: reviewFocusDatasets },
            options: {
                responsive: true, maintainAspectRatio: false, devicePixelRatio: getChartDPR(),
                plugins: { legend: { position: 'top', labels: { usePointStyle: true, pointStyle: 'circle', generateLabels: cumulativeLegendLabels } }, title: { display: false, text: 'SLR vs SMS per Year' }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${context.raw}` } } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 }, stacked: isStacked }, x: { ticks: { precision: 0 }, stacked: isStacked } }
            }
        }));
    } else if (reviewFocusCtx) {
        registerChartInstance('reviewFocusPerYearLineChart', new Chart(reviewFocusCtx, { type: 'line', data: { labels: [], datasets: [] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, title: { display: true, text: 'SLR vs SMS per Year (No Data)' } } } }));
    }

    if (isStacked) reorderDatasetsForStacking();
}

// ======================================================================
// Main render entry point
// ======================================================================

function renderDomainCharts() {
    // Techniques distribution
    destroyChartInstance('techniquesChart');
    registerChartInstance('techniquesChart', renderBarOrPieChart(
        document.getElementById('techniquesPieChart')?.getContext('2d'),
        prepareTechniquesData(), 'Techniques Count',
        showPieCharts ? 'pie' : 'bar'
    ));

    // Kitchenham Stages distribution
    destroyChartInstance('stagesChart');
    registerChartInstance('stagesChart', renderBarOrPieChart(
        document.getElementById('stagesPieChart')?.getContext('2d'),
        prepareStagesData(), 'Kitchenham Stages Count',
        showPieCharts ? 'pie' : 'bar'
    ));

    // Stage Details distribution
    destroyChartInstance('stageDetailsChart');
    registerChartInstance('stageDetailsChart', renderBarOrPieChart(
        document.getElementById('stageDetailsPieChart')?.getContext('2d'),
        prepareStageDetailsData(), 'Stage Details Count',
        showPieCharts ? 'pie' : 'bar'
    ));

    // SMS Specific distribution
    destroyChartInstance('smsSpecificChart');
    registerChartInstance('smsSpecificChart', renderBarOrPieChart(
        document.getElementById('smsSpecificPieChart')?.getContext('2d'),
        prepareSmsSpecificData(), 'SMS Specific Count',
        showPieCharts ? 'pie' : 'bar'
    ));

    // SLR vs SMS
    destroyChartInstance('slrVsSmsChart');
    registerChartInstance('slrVsSmsChart', renderBarOrPieChart(
        document.getElementById('slrVsSmsPieChart')?.getContext('2d'),
        prepareSlrVsSmsData(), 'SLR vs SMS',
        showPieCharts ? 'pie' : 'bar'
    ));

    // Line charts
    renderDomainLineCharts();
}

// ======================================================================
// DOMContentLoaded — interactive toggles
// ======================================================================

document.addEventListener('DOMContentLoaded', () => {
    const stageGroupToggle = document.getElementById('stageGroupToggle');
    if (stageGroupToggle) {
        stageGroupToggle.addEventListener('change', function () {
            const ctx = document.getElementById('stagesPieChart')?.getContext('2d');
            destroyChartInstance('stagesChart');
            registerChartInstance('stagesChart', renderBarOrPieChart(
                ctx, prepareStagesData(), 'Kitchenham Stages Count',
                showPieCharts ? 'pie' : 'bar'
            ));
        });
    }
});