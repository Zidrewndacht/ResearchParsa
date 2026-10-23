# shared/pdf_extractor.py
"""
PDF text extraction for ResearchParsa.

Uses the PyMuPDF 2.x Document.to_markdown() API.

Returns structured Markdown text for papers that have a PDF file on disk.
Falls back silently to None when no PDF exists, the PDF cannot be opened,
or PyMuPDF is unavailable.
"""

import os
import re
from typing import Optional

try:
    import pymupdf
except Exception as exc:
    pymupdf = None
    _PYMUPDF_IMPORT_ERROR = exc
else:
    _PYMUPDF_IMPORT_ERROR = None

from shared import config

# Extraction size guards.
# Below MIN the output is almost certainly just headers/footers with no real
# content (e.g. a copyright banner); the caller will fall back to the stored
# abstract.  Above MAX we truncate — 100 000 chars (~100 kB) is far more than
# any classification prompt needs.
MIN_PDF_TEXT_CHARS = 1000
MAX_PDF_TEXT_CHARS = 100_000


_PAGE_NUMBER_RE = re.compile(
    r'^\s*(?:page\s+)?\d{1,4}\s*(?:of\s+\d{1,4})?\s*$',
    re.IGNORECASE
)

_BOILERPLATE_PATTERNS = [
    # IEEE
    re.compile(r'^\s*©\s*\d{4}\s*IEEE\b.*$', re.IGNORECASE),
    re.compile(r'^\s*978[-–]\d[\d\-–]+\s*/\s*\d{2,4}\s*/.*$', re.IGNORECASE),
    re.compile(r'^\s*DOI\s*[:：]\s*10\.\d{4,}/.*$', re.IGNORECASE),
    re.compile(r'^\s*Authorized\s+licensed\s+use\s+limited\s+to.*$', re.IGNORECASE),
    re.compile(r'^\s*Downloaded\s+on\s+.*\s+from\s+IEEE\s+Xplore.*$', re.IGNORECASE),
    re.compile(r'^\s*IEEE\s+(Access|Transactions|Journal|Conference|Proceedings)\b.*$', re.IGNORECASE),

    # Springer
    re.compile(r'^\s*©\s*Springer[-–\s]*(Nature|Verlag|Science).*$', re.IGNORECASE),
    re.compile(r'^\s*Published\s+in\s+cooperation\s+with.*$', re.IGNORECASE),

    # Elsevier / ScienceDirect
    re.compile(r'^\s*©\s*\d{4}\s*Elsevier\s+B\.?V\..*$', re.IGNORECASE),
    re.compile(r'^\s*ScienceDirect\s*$', re.IGNORECASE),
    re.compile(r'^\s*Contents\s+lists\s+available\s+at.*$', re.IGNORECASE),

    # ACM
    re.compile(r'^\s*©\s*\d{4}\s*ACM\b.*$', re.IGNORECASE),
    re.compile(r'^\s*ACM\s+ISBN\s+\d[\d\-]+.*$', re.IGNORECASE),
    re.compile(
        r'^\s*Permission\s+to\s+make\s+digital\s+or\s+hard\s+copies.*$',
        re.IGNORECASE | re.DOTALL
    ),

    # General publisher / metadata boilerplate
    re.compile(r'^\s*ISSN\s*[:：]?\s*\d{4}[-–]\d{3}[\dXx]\s*$', re.IGNORECASE),
    re.compile(r'^\s*ISBN\s*[:：]?\s*[\d\-–\s]+$', re.IGNORECASE),
    re.compile(r'^\s*Vol\.\s*\d+\s*,\s*(No\.|Issue)\s*\d+.*$', re.IGNORECASE),
    re.compile(r'^\s*pp\.\s*\d+[-–]\d+\s*$', re.IGNORECASE),
    re.compile(r'^\s*Received\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*Accepted\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*Published\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*This\s+work\s+is\s+licensed\s+under.*$', re.IGNORECASE),
    re.compile(r'^\s*Creative\s+Commons\s+(Attribution|CC\s+BY).*$', re.IGNORECASE),
    re.compile(r'^\s*Digital\s+Object\s+Identifier\b.*$', re.IGNORECASE),
]


def _find_pdf_path(paper_id, pdf_filename=None) -> Optional[str]:
    """
    Locate the PDF file on disk.

    Priority:
      1. pdf_filename from the database, if present
      2. fallback to "{paper_id}.pdf"

    For each candidate filename, the original PDF directory is checked
    before the annotated PDF directory.
    """
    filenames = []

    if pdf_filename:
        filenames.append(str(pdf_filename))

    if paper_id is not None and str(paper_id).strip() != "":
        default_filename = f"{paper_id}.pdf"
        if default_filename not in filenames:
            filenames.append(default_filename)

    if not filenames:
        return None

    directories = (
        config.PDF_STORAGE_DIR,
        config.ANNOTATED_PDF_STORAGE_DIR,
    )

    for filename in filenames:
        for directory in directories:
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                return path

    return None


def _is_boilerplate_line(stripped_line: str) -> bool:
    """Return True for obvious publisher/template/page-number boilerplate."""
    if _PAGE_NUMBER_RE.match(stripped_line):
        return True

    for pattern in _BOILERPLATE_PATTERNS:
        if pattern.match(stripped_line):
            return True

    return False

def _clean_extracted_text(text: str) -> Optional[str]:
    """Strip boilerplate and references from raw extracted text."""
    if not text or not text.strip():
        return None

    # Cut at References / Bibliography
    ref_patterns = [
        re.compile(r'^#{1,6}\s*[*_]*(References|Bibliography|Citations)[*_]*\s*$', re.IGNORECASE | re.MULTILINE),
        re.compile(r'^\s*(References|Bibliography|Citations)\s*$', re.IGNORECASE | re.MULTILINE),
    ]
    for pattern in ref_patterns:
        match = pattern.search(text)
        if match:
            text = text[:match.start()]
            break

    # Remove HTML artifacts if any leaked through
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = text.replace('<br>', '\n')

    # Line-by-line boilerplate removal
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
        if _is_boilerplate_line(stripped):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    return cleaned or None

def extract_pdf_markdown(paper_id, pdf_filename=None) -> Optional[str]:
    """
    Extract text content from the paper's PDF.
    Uses simple per-page text extraction (fast, <100ms per page).
    """
    pdf_path = _find_pdf_path(paper_id, pdf_filename)
    if not pdf_path:
        return None

    if pymupdf is None:
        print(f"[PDF] pymupdf unavailable, skipping {pdf_path}: {_PYMUPDF_IMPORT_ERROR}")
        return None

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        print(f"[PDF] Failed to open {pdf_path}: {exc}")
        return None

    try:
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text("text"))
        raw_text = "\n\n".join(pages_text)
    except Exception as exc:
        print(f"[PDF] Extraction failed for {pdf_path}: {exc}")
        return None
    finally:
        doc.close()

    cleaned = _clean_extracted_text(raw_text)

    if cleaned is None:
        return None

    # Reject suspiciously small extractions (likely just copyright banners
    # or conference headers with no actual paper content).
    if len(cleaned) < MIN_PDF_TEXT_CHARS:
        print(f"[PDF] Extracted text too small ({len(cleaned)} chars), "
              f"treating as empty for {pdf_path}")
        return None

    # Clamp to maximum size, cutting at a paragraph boundary when possible,
    # and leave an explicit marker so the downstream prompt can reason about
    # the cutoff instead of treating it as the natural end of the paper.
    if len(cleaned) > MAX_PDF_TEXT_CHARS:
        cut = cleaned.rfind('\n\n', 0, MAX_PDF_TEXT_CHARS)
        if cut == -1:
            cut = cleaned.rfind('\n', 0, MAX_PDF_TEXT_CHARS)
        if cut == -1:
            cut = MAX_PDF_TEXT_CHARS
        cleaned = cleaned[:cut].rstrip()
        cleaned += (
            "\n\n[NOTE: The full paper text was truncated at this point due to length limits. "
            "The remaining sections were not included in this excerpt.]"
        )

    return cleaned