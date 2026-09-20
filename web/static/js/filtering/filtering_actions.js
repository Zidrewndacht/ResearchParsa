// static/js/filtering_actions.js
/** Clipboard utilities and LaTeX export actions.
 *  Shared between server-based full page and client-only HTML export. */

/**
 * Copies the provided paper ID to the clipboard in the specified format.
 */
function copyPaperId(paperId, buttonElement, format = 'raw') {
    if (!paperId) {
        console.warn('Paper ID is empty or undefined.');
        alert('Paper ID is empty and cannot be copied.');
        return;
    }
    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = 'Copied!';
    let textToCopy = paperId;
    if (format === 'cite') {
        textToCopy = `\\cite{${paperId}}`;
    } else if (format === 'citen') {
        textToCopy = `\\citen{${paperId}}`;
    }
    navigator.clipboard.writeText(textToCopy)
        .then(() => {
            setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000);
        })
        .catch(err => {
            console.error(`Failed to copy: `, err);
            alert(`Failed to copy to clipboard.`);
            buttonElement.innerHTML = originalText;
        });
}

/**
 * Copies the provided BibTeX string to the clipboard.
 */
function copyBibtex(bibtexString, buttonElement) {
    if (bibtexString) {
        const originalText = buttonElement.textContent;
        buttonElement.textContent = 'Copied!';
        navigator.clipboard.writeText(bibtexString)
            .then(() => {
                setTimeout(() => { buttonElement.textContent = originalText; }, 2000);
            })
            .catch(err => {
                console.error('Failed to copy BibTeX: ', err);
                alert('Failed to copy BibTeX to clipboard.');
                buttonElement.textContent = originalText;
            });
    } else {
        console.warn('BibTeX content is empty.');
        alert('BibTeX content is empty and cannot be copied.');
    }
}

/**
 * Generates a LaTeX longtable based on the currently visible (filtered) rows.
 */

function copyLatexLongtable() {
    const buttonElement = document.getElementById('longtable-btn');
    const originalText = buttonElement.innerHTML;
    const papers = papersStore.getFiltered();
    if (papers.length === 0) {
        alert('No visible rows found to generate LaTeX table.');
        return;
    }

    let latexContent = `
% Ensure packages are loaded in your preamble:
% \\usepackage{longtable}
% \\usepackage{xcolor}
% \\usepackage{pdflscape} % For landscape pages
% \\usepackage[margin=1.5cm]{geometry} % Set smaller margins for the table area
\\begin{landscape} % Start landscape environment
% ----------------------------------------------------------
\\chapter{Lista completa de artigos julgados como relevantes através do ResearchParsa}
% ----------------------------------------------------------
\\definecolor{tableshade}{HTML}{EEEEEE}
\\scriptsize % Use smaller font to fit more data
\\begin{longtable}{p{2cm}p{8cm}p{5cm}c c p{6cm}}
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row
\\endfirsthead
\\multicolumn{6}{c}{{\\bfseries \\tablename\\ \\thetable{} -- continuação dá página anterior}} \\\\
\\rowcolor{tableshade}
\\textbf{Tipo} & \\textbf{Título} & \\textbf{Autores} & \\textbf{Ano} & \\textbf{Páginas} & \\textbf{Periódico/Conferência} \\\\
\\hline % Line only under the header row on subsequent pages
\\endhead
\\hline % Line before the footer
\\multicolumn{6}{|r|}{{Continua na próxima página}} \\\\
\\hline % Line after the footer text
\\endfoot
\\hline % Line before the last footer
\\endlastfoot
`;
    papers.forEach((paper, index) => {
        const sanitize = s => typeof s !== 'string' ? String(s || '') : s;
        const type = sanitize(paper.type);
        const title = sanitize(paper.title);
        const authors = sanitize(paper.authors);
        const year = sanitize(paper.year);
        const pages = sanitize(paper.page_count);
        const venue = sanitize(paper.deannualized_conference || paper.journal);
        const rowColor = (index % 2 === 0) ? '' : '\\rowcolor{tableshade} ';
        latexContent += `${rowColor}${type} & ${title} & ${authors} & ${year} & ${pages} & ${venue} \\\\\n`;
    });
    latexContent += `\\hline\n\\end{longtable}\n\\end{landscape}\n`;
    navigator.clipboard.writeText(latexContent)
        .then(() => { buttonElement.innerHTML = 'Copied!'; setTimeout(() => { buttonElement.innerHTML = originalText; }, 2000); })
        .catch(() => { alert('Failed to copy LaTeX table.'); buttonElement.innerHTML = originalText; });
}