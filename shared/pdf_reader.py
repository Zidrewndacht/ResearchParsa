# shared/pdf_reader.py
"""
PDF text extraction using PyMuPDF 2.0+.
Converts PDF pages to structured markdown using the native Document.to_markdown() API,
then strips publisher template boilerplate, page numbers, and repeated headers/footers.
"""

import os
import re
from typing import Optional

import pymupdf  # PyMuPDF >= 2.0

from shared import config

# ---------------------------------------------------------------------------
# Boilerplate patterns (publisher templates, legal text, etc.)
# ---------------------------------------------------------------------------
_BOILERPLATE_PATTERNS = [
    # IEEE
    re.compile(r'^\s*©\s*\d{4}\s*IEEE\b.*$', re.IGNORECASE),
    re.compile(r'^\s*978[-–]\d[\d\-–]+\s*/\s*\d{2,4}\s*/.*$', re.IGNORECASE),
    re.compile(r'^\s*DOI\s*[:：]\s*10\.\d{4,}/.*$', re.IGNORECASE),
    re.compile(r'^\s*Authorized\s+licensed\s+use\s+limited\s+to.*$', re.IGNORECASE),
    re.compile(r'^\s*Downloaded\s+on\s+.*\s+from\s+IEEE\s+Xplore.*$', re.IGNORECASE),
    # Springer
    re.compile(r'^\s*©\s*Springer[-–\s]*(Nature|Verlag|Science).*$', re.IGNORECASE),
    # Elsevier / ScienceDirect
    re.compile(r'^\s*©\s*\d{4}\s*Elsevier\s+B\.?V\..*$', re.IGNORECASE),
    re.compile(r'^\s*ScienceDirect\s*$', re.IGNORECASE),
    re.compile(r'^\s*Contents\s+lists\s+available\s+at.*$', re.IGNORECASE),
    # ACM
    re.compile(r'^\s*©\s*\d{4}\s*ACM\b.*$', re.IGNORECASE),
    re.compile(r'^\s*Permission\s+to\s+make\s+digital\s+or\s+hard\s+copies.*$', re.IGNORECASE | re.DOTALL),
    # General
    re.compile(r'^\s*ISSN\s*[:：]?\s*\d{4}[-–]\d{3}[\dXx]\s*$', re.IGNORECASE),
    re.compile(r'^\s*ISBN\s*[:：]?\s*[\d\-–\s]+$', re.IGNORECASE),
    re.compile(r'^\s*Vol\.\s*\d+\s*,\s*(No\.|Issue)\s*\d+.*$', re.IGNORECASE),
    re.compile(r'^\s*pp\.\s*\d+[-–]\d+\s*$', re.IGNORECASE),
    re.compile(r'^\s*Received\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*Accepted\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*Published\s+\d{1,2}\s+\w+\s+\d{4}.*$', re.IGNORECASE),
    re.compile(r'^\s*This\s+work\s+is\s+licensed\s+under.*$', re.IGNORECASE),
    re.compile(r'^\s*Creative\s+Commons\s+(Attribution|CC\s+BY).*$', re.IGNORECASE),
]

_PAGE_NUMBER_RE = re.compile(r'^\s*(?:page\s+)?\d{1,4}\s*(?:of\s+\d{1,4})?\s*$', re.IGNORECASE)

def _is_boilerplate_line(text: str) -> bool:
    """Check if a line matches known publisher/template boilerplate."""
    stripped = text.strip()
    if not stripped:
        return True
    if _PAGE_NUMBER_RE.match(stripped):
        return True
    for pat in _BOILERPLATE_PATTERNS:
        if pat.match(stripped):
            return True
    return False

def extract_pdf_markdown(paper_id: str) -> Optional[str]:
    """
    Extract the text content of a paper's PDF as structured markdown.
    Uses PyMuPDF 2.0's native Document.to_markdown() which handles layout 
    analysis, multi-column text, and tables automatically.
    """
    pdf_filename = f"{paper_id}.pdf"
    original_path = os.path.join(config.PDF_STORAGE_DIR, pdf_filename)
    annotated_path = os.path.join(config.ANNOTATED_PDF_STORAGE_DIR, pdf_filename)

    pdf_path = None
    if os.path.isfile(original_path):
        pdf_path = original_path
    elif os.path.isfile(annotated_path):
        pdf_path = annotated_path

    if pdf_path is None:
        return None

    try:
        # PyMuPDF 2.0 API: open document and call to_markdown()
        doc = pymupdf.open(pdf_path)
        
        # Extract markdown. We disable image embedding to keep the text payload 
        # small for the LLM context window.
        raw_md = doc.to_markdown(embed_images=False)
        doc.close()
        
    except Exception as e:
        print(f"[PDF] Extraction error for {pdf_path}: {e}")
        return None

    if not raw_md:
        return None

    # Post-process to strip publisher boilerplate and page numbers
    # that the layout engine might have faithfully reproduced.
    cleaned_lines = []
    for line in raw_md.split('\n'):
        if _is_boilerplate_line(line):
            continue
        cleaned_lines.append(line)

    full_text = '\n'.join(cleaned_lines)
    
    # Collapse excessive blank lines
    full_text = re.sub(r'\n{4,}', '\n\n\n', full_text)
    full_text = full_text.strip()

    return full_text if full_text else None

def has_pdf(paper_id: str) -> bool:
    """Check whether a readable PDF exists for the given paper."""
    pdf_filename = f"{paper_id}.pdf"
    original_path = os.path.join(config.PDF_STORAGE_DIR, pdf_filename)
    annotated_path = os.path.join(config.ANNOTATED_PDF_STORAGE_DIR, pdf_filename)
    return os.path.isfile(original_path) or os.path.isfile(annotated_path)