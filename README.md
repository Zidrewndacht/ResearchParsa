# ResearchParsa

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21816041.svg)](https://doi.org/10.5281/zenodo.21816041)

Live Demo (read-only HTML export -- note the link may be for a way outdated version when looking at a dev branch): [ResearchParsa](https://zidrewndacht.github.io/ResearchParsa).  

> *The frontend was mostly tested with Mozilla Firefox and works well. The HTML export had known performance issues in Chromium‑based browsers in 2025 and wasn't extensively performance-tested since. No problems are expected after the refactor to SPA-style frontend. If the page lags or stops responding on reasonably modern hardware, please use Firefox instead.*

ResearchParsa is a domain-agnostic tool for managing, classifying, and analyzing bibliographic databases of academic papers. It imports BibTeX/CSV files into an SQLite database and provides a rich, dynamically generated web interface for browsing, filtering, editing, and performing **LLM‑driven classification and verification**.

By defining your domain's taxonomy, filters, and prompt templates in a YAML configuration file, the system adapts its data model, UI columns, and statistical dashboards to any specific research field. It is designed to streamline systematic literature reviews by offering advanced search, traceable AI‑enriched metadata, and automated LaTeX table generation.

*Note: [ResearchParsa-Lite](https://github.com/Zidrewndacht/ResearchParsa-lite), minimal, generic PDF organizer/annotator is now deprecated as full ResearchParsa is now fit for any generic research domain.*

## Features

- **Domain-Agnostic Configuration**  
  Define your research domain's taxonomy, custom fields, filter types (tri-state, inclusion), and LLM prompt templates via `domain_config.yaml`. The UI, database JSON blobs, and statistics engine adapt dynamically to your schema.

- **LLM‑Powered Classification & Verification**  
  A separate **queue manager** (`queue_manager.py`) coordinates communication with an **OpenAI‑compatible LLM server** (specifically designed and tested for **Qwen3.5~3.8 via vLLM**).  
  - Each paper is classified **three times independently** to calculate certainty and detect conflicts.  
  - A **verifier** LLM scores the classification accuracy and provides reasoning traces. The backend automatically extracts and logs Qwen's native thinking traces (`reasoning_content`) for auditing.
  - An advanced **"Consensus" mode** iteratively re-classifies disputed papers until the verifier agrees or a limit is reached.

- **Quick Screening & Meta‑Audits**  
  - **Quick Screening (`/screen`)**: A fast, thinking-disabled triage route designed to flag obviously off-topic papers before expensive full-classification, saving significant compute.
  - **Agent Trace Review**: A per-paper meta-audit button ("Auto Audit traces" in the History view) that sends the complete reasoning logs of the three parallel classifiers to the LLM to identify hallucinations, prompt misreadings, or contradictions. It appends a `trace_review` entry to the main log and **does not** alter the paper's classification.

- **Dedicated Agreement Report**  
  A whole-dataset dashboard (accessible via the Batch Tasks menu) that visualizes pipeline health, contradiction outliers, relevance correlations, and consensus progress over time. It generates Wilson 95% Confidence Intervals and provides one-click LaTeX table exports for your manuscript. Outlier rows are deep-linked: clicking one opens the main table in a new tab, narrowed to that single paper. A companion **Queue Manager Log Viewer** link sits beside it.

- **Interactive Web Interface**  
  A Flask-based application built around a **virtual scroller** that renders only the visible window of rows, keeping large datasets responsive. It provides:
  - **Inline cell editing**: click a tri-state cell to cycle `✔️ → ❌ → ❔`, or a `verified_by` cell to cycle `👤 → ❔`, with AJAX autosave.
  - **Certainty visualization**: solid emojis for full agreement, translucent emojis (80% / 60% opacity) for partial agreement, and a `⚠️` overlay for direct Yes/No conflicts.
  - **Edit Lock** (`🔒`/`🔓` in the header): prevents accidental clicks on definitive cells. Persisted in `localStorage` and defaults to **locked**; hover tooltips remain active when locked.
  - **State preservation**: active filters, sort column, and up to 10 expanded detail/history rows survive reload via URL parameters (`open_details`, `open_history`), enabling bookmarkable views.
  - **`focus_paper` deep links**: narrow the table to a single paper, smooth-scroll to it, apply a pulsing highlight, and auto-open its history row.
  - **Duplicate detection**: rows sharing a journal or title are shaded and counted in the footer.
  - **Live footer counts**: visible / loaded / total / duplicate totals, plus per-field counts (how many visible papers have each inferred field set to `✔️`, `❌`, `❔`, or `⚠️`), and a `\longtable` copy button for the current filtered view.

- **Traceability & History**  
  Every AI classification, verification, screening, consensus round, agent audit, and user edit is logged. The "History" view provides per-set (Set 1/2/3) and averaged logs with:
  - LLM reasoning traces and verification summaries.
  - Change highlighting (cells modified between consecutive runs).
  - Certainty overlays matching the main table.
  - Colour-coded log-entry types (`classifier`, `verifier`, `consensus`, `user`, `screener`, `trace_review`).
  - Inline **invalid-reason** messages on rejected runs.

- **Advanced Filtering & Search**  
  Server-side filters (year, page count) and dynamic client-side filtering based on your domain configuration:
  - **Tri-state checkboxes** cycle through `All → Only Yes → Only No`.
  - **Inclusion checkboxes** union the selected groups.
  - **Hide Off-topic**, **Hide Approved**, and a debounced **global search** that indexes IDs, titles, authors, abstracts, keywords, user comments, journals, DOIs, years, page counts, types, ISSNs, and all configured `editable_fields`.

- **Statistics & LaTeX Export**  
  A dedicated "Statistics" modal presents dynamic charts and lists based on the **currently visible** papers, including journals, conferences, keywords (word cloud + list), authors, research areas, configurable "Mentioned X" slot lists, and per-year line charts. Chart toggles include Pie↔Bar, feature grouping, cumulative, and stacked modes; legend labels can be clicked to show/hide individual series. Includes one-click generation of LaTeX `\tabularx` (per-list copy buttons) and `\longtable` (whole-table copy button) code, ready to paste into your manuscript.

- **PDF Management & Annotation**  
  Upload, store, and view PDFs. An integrated **PDF.js** annotator lets you highlight and add notes, **auto-saved** to the server after 5 seconds of inactivity; a green toast confirms each autosave. PDF states (`📕` PDF, `📗` annotated, `💰` paywalled, `❔` none) are re-reconciled against the filesystem every time a PDF is served, so out-of-band changes self-heal. Automated paywall tracking flags a paper as `💰` when a user comment contains "paywalled" and no PDF is attached.

- **Data Export & Archiving**  
  - **Static HTML Export**: A self-contained, compressed HTML file with full offline filtering, sorting, history, detail, and charting capabilities — ideal for sharing or archiving. Two options are exposed in the Export menu: **Lite export** (strips thinking traces) and **Skip abstracts**. The export is rendered read-only; server-only actions (upload, save, classify, verify, backup/restore, BibTeX import, edit lock) are stripped. It self-decompresses client-side via an inline Pako loader.
  - **XLSX Export**: Formatted Excel spreadsheets with conditional formatting and multi-sheet audit logs.
  - **Backup & Restore**: Complete Zstandard-compressed archives (`.parsa.tzst`) containing the database, all original/annotated PDFs, an HTML export, an XLSX export, the active `domain_config.yaml`, and any user-edited prompt-template fragments. Restoring is preceded by a safety backup (`backup_before_restore.parsa.tzst`) and hot-reloads the domain config.

(videos below are outdated as they represent an older version that lacked history and multi-set classification, among other features. But it provides a quick introduction to the overall user interface)

https://github.com/user-attachments/assets/a37ee7b6-27e8-459a-a092-be67ee769b5e

https://github.com/user-attachments/assets/3a12f927-1050-485e-b6f7-5df151685a58

## Usage

1.  **Running the Application**:
    - Ensure Python 3.12+ is installed.
    - Download this repository and run `!browse_db.bat` on Windows (or the corresponding `.sh` scripts on Linux/macOS). A Virtual Environment with the required dependencies will be automatically created.
    - The application will be available at `http://127.0.0.1:5001` (or your configured port).
    - To enable AI classification, start `!queue_manager.bat` and your OpenAI-compatible LLM endpoint (tested with local vLLM; cloud-based reasoning APIs are also possible but remain untested). Browsing and editing an existing database does not require the queue manager.

2.  **Domain & Database Setup**:
    - Configure your domain taxonomy, UI theme, and LLM prompts in `domain_config.yaml`, and general settings in `config.yaml`.
    - The four user-editable prompt fragments (`classify_instructions`, `classify_output_template`, `few_shot_examples`, `screening_template`) live under `prompt_templates/`; the fixed base templates stay under `prompt_templates/base_templates/` and are shared across domains.
    - Import a BibTeX (`.bib`) or IEEE Xplore CSV file directly from the web interface. If no database exists, the app initializes a fresh domain-agnostic schema plus a placeholder row that is removed the first time a real paper is imported.

3.  **LLM Integration**:
    - Start a local **vLLM** OpenAI-compatible inference server (strongly recommended for high-throughput batch processing and native thinking-trace support).
    - The system is currently designed and tested specifically for **Qwen3.5~3.8** models. *(Note: While it may work with other cloud-based APIs or reasoning models, they remain untested).*
    - Configure the server URL, API keys, and any `llm_params` / `screening_llm_params` overrides in `config.yaml`.
    - Use the **Batch Tools** menu in the web UI to trigger classifications, verifications, quick screenings, or consensus runs across your dataset.
    - The Batch Tools menu also links to the **Queue Manager Log Viewer** (`/queue_logs`), which streams the queue manager's own logs — useful for diagnosing stalled workers or admission-control behaviour during large runs.

4.  **Interactive Help & Shortcuts**:
    - Click the **?** button in the top‑right corner for a detailed guide on symbols and UI features.
    - The **🔒/🔓** edit lock in the table header prevents accidental clicks on cells; it defaults to **locked** and remembers your choice across sessions (`localStorage`). Hover tooltips remain active when locked.
    - The whole visible/filtered table can be copied as a LaTeX `\longtable` from the footer's `\longtable` button, preserving the current filter/sort order.
    - **Keyboard Shortcuts**:
      - `F1`: Open Help/About modal
      - `F3`: Focus Search bar
      - `F4`: Open Statistics modal
      - `Ctrl+S` / `Cmd+S`: Save changes in an expanded detail row
      - `Esc`: Close active modals

5.  **CLI Tools for Meta-Analysis**:
    For researchers generating LaTeX tables and statistical summaries for manuscripts, the `meta/` directory contains standalone CLI tools:
    - **`agreement_3sets_cli_v1.4.py`**: Generates 3-run agreement statistics (Perfect, Uncertain, Contradiction), stratified by relevance and off-topic status, outputting Elsevier-formatted LaTeX tables with Wilson 95% Confidence Intervals, plus a companion `_macros.tex` file of `\newcommand` shortcuts for your manuscript. The same statistics are exposed via the Agreement Report in Batch Tools.
    - **`agreement_human_cli_v1.4.py`**: Compares the AI database against a user-modified database to generate "Human-AI Alignment Summary" tables (Exact Match, Conflict, AI Overconfidence, etc.).

6.  **Architecture & Concurrency**:
    - **Smart Admission Control**: The Queue Manager features a "Homogeneous vs. Mixed" concurrency logic. It groups identical task types together to prevent vLLM context-switching penalties, maximizing throughput during large batch operations.
    - **Per-paper recalc serialization**: `recalculate_main_set` uses `BEGIN IMMEDIATE` so simultaneous completions from sets 1/2/3 cannot clobber each other's averaged classification.
    - **Production vs. Dev**: Both `browse_db.py` and `queue_manager.py` use **Waitress** for production serving, and Flask's dev server for debugging (controlled by `DEBUG_MODE` in `config.py`).

<details>
<summary>Frontend Feature Reference</summary>

> A field-by-field guide to UI behaviours that aren't obvious from the main Features list. Useful for reviewers, contributors, and anyone filing issues against the front end.

### Table chrome

- **Virtual scrolling**: `virtual_scroll.js` renders only the paper-groups in/near the viewport, plus a small buffer. Expanded detail and history rows are collapsed before removal and re-opened instantly (no animation) when scrolled back in.
- **Direction-aware sticky header**: the header collapses out of the way when you scroll down and re-expands only after ~120 px of sustained upward scroll. Row offsets (`--hdr-h1` through `--hdr-h4`) are measured once at boot so rows 2–4 stack correctly while pinned.
- **Scroll-progress slit**: a thin gradient bar in the 5th header row tracks `scrollTop / (scrollHeight − clientHeight)`.
- **Duplicate shading**: rows whose `deannualized_conference || journal` (or whose `title`) appear ≥ 2 times in the current filtered view are shaded. Journal shading uses an HSL ramp keyed to the duplicate count; title shading is a fixed pale red. The footer shows `Duplicate: N`.
- **Footer counts**: visible / loaded / total, plus one count cell per inferred field (how many visible papers have that field set to `✔️`, `❌`, `❔`, or `⚠️`). The `\longtable` copy button sits in the footer.
- **URL state**: `open_details` and `open_history` hold up to 10 comma-separated paper IDs. Filters, sort, and search are also serialized into the URL by `updateUrlWithClientFilters` / `updateUrlWithDetailState`.

### Inline editing

- **Tri-state cells**: click to cycle `✔️ → ❌ → ❔`. Saved via `/update_paper`. A yellow flash confirms the change.
- **`verified_by` cells**: click to cycle `👤 → ❔` (and `🖥️ → 👤`). Only `user` and `null` are persisted; the model's `🖥️` state comes from the LLM-averaging step and cannot be re-set manually.
- **Text-presence fields** (`render_type: text_presence`): render `✔️` if the underlying string is non-empty, `❌` otherwise. Set through the detail-row form, not by clicking the cell.
- **Edit lock**: 🔒/🔓 in the header. When locked, editable cells still show their tooltips but suppress hover visuals and ignore clicks. Persisted under `parsa_edit_locked` in `localStorage`; defaults to locked.
- **Ctrl+S / Cmd+S**: while a detail-row input has focus, this saves the whole form (equivalent to clicking "Save Changes").

### Detail row

- **BibTeX copy**: server-rendered via `bibtex_filter` in the live app; client-rendered via `exportRenderers._generateBibtex` in HTML exports.
- **ID copy**: three buttons — raw, `\cite{id}`, and `\citeN{id}`.
- **Clickable authors / keywords**: clicking a name in the detail row populates the search box and re-applies filters.

### History row

- **Tabs**: Main, Set 1, Set 2, Set 3. Switching is pure client-side.
- **Change highlighting**: cells whose value differs from the previous valid entry are tinted.
- **Certainty overlays**: same 100/80/60/⚠️ scheme as the main table.
- **Invalid-reason surfacing**: `valid: false` entries carry an `invalid_reason` shown on hover and inline.
- **Auto Audit traces**: sends the paper's full 3-set log stream to the LLM for a free-form review. The result is appended as a `trace_review` log entry and shown in the Main tab. Does not alter classification.

### Statistics modal

- **Lists** are computed from the currently visible (client-filtered) papers, not the whole DB.
- **Keyword word cloud**: d3-cloud; toggle between cloud and list.
- **Configurable slot lists**: `editable_fields[*].stats_list` in `domain_config.yaml` drives the two "Mentioned X" lists and their `\tabularx` copy buttons.
- **Chart toggles**: Pie↔Bar (`#pieToggle`), feature grouping (`#featureGroupToggle`), cumulative (`#cumulativeToggle`), stacked (`#stackingToggle`). Legend labels are clickable to show/hide individual series.
- **Charts included**: publication-type pie, survey-vs-primary pie, techniques distribution, features distribution, per-year publication types, per-year survey-vs-primary, per-year techniques, per-year features, relevance histogram, verifier-score histogram, SMT-vs-THT pie, dataset-scope pie.

### Export / import

- **Lite export**: strips thinking traces from the embedded data; a fallback message takes their place in the history view.
- **Skip abstracts**: omits abstracts from the exported detail rows and from the search haystack.
- **Loader page**: the static export is delivered as a gzip-compressed base64 blob inside a small loader HTML. The loader inflates it via inline Pako and calls `document.open()/write()/close()` to swap in the real page.
- **Read-only by design**: the static export strips server-only actions (upload, save, classify, verify, backup/restore, BibTeX import, edit lock). Only local filtering, sorting, search, chart toggles, and history/detail expansion remain interactive.
- **PDF links**: point to `data/pdf/<filename>` or `data/pdf_annotated/<filename>`, so PDFs open in the browser's native viewer only when the export directory preserves the backup's `data/pdf` / `data/pdf_annotated` layout.
- **Backup contents**: DB, both PDF directories, an HTML export (full, not lite), an XLSX export, `domain_config.yaml`, and user-edited prompt fragments. Restore is preceded by a `backup_before_restore.parsa.tzst` safety archive and hot-reloads the running domain config.

### PDF viewer

- **Entry**: click `📕`/`📗` in the PDF column to open the built-in PDF.js viewer. Click `❔` to upload a PDF.
- **Autosave**: 5-second debounce on `annotationeditorstateschanged`. A green "Annotations auto-saved ✓" toast confirms each save.
- **State reconciliation**: `/serve_pdf/<id>` checks the filesystem on every request and rewrites `pdf_state` if it has drifted (e.g., annotated PDF deleted externally).

</details>

---


## Licensing
This project uses a modular licensing approach to balance open scientific research with the protection of our product development efforts:

*   **Core Backend & Scientific Artifacts:** The backend pipeline, queue manager, analysis scripts, and reproduction data (everything outside the `/web` directory) are licensed under the **Apache License 2.0**. You are free to use, modify, and distribute these components for any purpose, including commercial applications.
*   **Web UI:** The web interface and user experience components located in the `/web` directory are licensed under the **PolyForm Noncommercial License 1.0.0**. You may use, modify, and run the frontend for non-commercial purposes (including academic research, peer review, and personal use). Commercial use of the frontend requires a separate licensing agreement with the authors.

## Third-Party Software and Licenses

This project bundles several third-party open-source libraries. While the core ResearchParsa application is licensed as described above, these bundled libraries retain their original licenses:

*   **PDF.js** (`web/static/pdfjs/`): Licensed under the Apache License 2.0 (Mozilla Foundation). Our custom autosave integration (`autosave.js`) is also released under Apache 2.0 to maintain compatibility.
*   **Chart.js, D3.js, Pako, etc.** (`web/static/libs/`): Licensed under their respective MIT/ISC licenses.
*   **Inter Tight & Twemoji Mozilla Fonts** (`web/static/css/fonts/`): Licensed under the SIL Open Font License and CC-BY 4.0, respectively.

---

## Acknowledgments

Developed by [**Luis Alfredo da Silva**](https://zidrewndacht.github.io/), to assist his Master’s degree research at [**Universidade do Estado de Santa Catarina (UDESC)**](https://www.udesc.br/cct).

At least the following open‑source libraries (and their dependencies) are used:

**Backend**  
[Python](https://www.python.org/), [Flask](https://flask.palletsprojects.com/), [SQLite3](https://www.sqlite.org/), [bibtexparser](https://pypi.org/project/bibtexparser/)

**Frontend**  
[HTML5](https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/HTML5), [CSS3](https://developer.mozilla.org/en-US/docs/Web/CSS), [Vanilla JS](https://developer.mozilla.org/en-US/docs/Web/JavaScript)

**Data Visualization**  
[Chart.js](https://www.chartjs.org/), [chartjs-plugin-datalabels](https://chartjs-plugin-datalabels.netlify.app/), [d3.js](https://d3js.org/), [d3-cloud.js](https://github.com/jasondavies/d3-cloud)

**PDF View/Annotation**  
[PDF.js](https://mozilla.github.io/pdf.js/getting_started/)

**Utilities**  
[rcssmin](https://opensource.perlig.de/rcssmin/), [rjsmin](https://opensource.perlig.de/rjsmin/), [openpyxl](https://openpyxl.readthedocs.io/), [pako](https://nodeca.github.io/pako/), [Zstandard](https://github.com/facebook/zstd)

<img width="1995" height="1579" alt="image" src="https://github.com/user-attachments/assets/5591360f-cec9-4b9f-b544-3a063402065f" />