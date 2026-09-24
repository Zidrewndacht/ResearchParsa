# web/importer.py
# v1.5
# Domain-agnostic BibTeX/CSV importer for the ResearchParsa database.
# The database schema relies on JSON blobs for classification data, 
# which is entirely driven by the active domain_config.yaml.

import csv
import os
import re
import sqlite3

import bibtexparser
from bibtexparser.model import Entry

# from shared import config

def parse_authors(authors_str):
    if not authors_str: return ""
    return "; ".join(a.strip() for a in authors_str.split(' and '))

def parse_keywords(keywords_str):
    if not keywords_str: return ""
    return "; ".join(k.strip() for k in keywords_str.split(','))

def clean_latex_braces(text):
    """Remove unescaped curly braces from text, often left in titles by bibtexparser."""
    if not text:
        return text
    # Remove braces that are not part of a LaTeX command (simple heuristic)
    # This removes { and } that are not preceded by a backslash.
    # It might not be perfect for all edge cases but handles common ones.
    cleaned = re.sub(r'(?<!\\)\{', '', text)
    return re.sub(r'(?<!\\)\}', '', cleaned)

def clean_latex_commands(text):
    """Remove common LaTeX commands and formatting from text."""
    if not text: return text

    # Remove unescaped braces
    text = re.sub(r'(?<!\\)\{', '', text)
    text = re.sub(r'(?<!\\)\}', '', text)
    # Replace LaTeX dash commands with regular dash
    text = re.sub(r'\\textendash', '-', text)
    text = re.sub(r'\\textemdash', '-', text)
    text = re.sub(r'\\endash', '-', text)
    text = re.sub(r'\\emdash', '-', text)
    
    # Remove other common LaTeX commands
    text = re.sub(r'\\textellipsis', '...', text)
    text = re.sub(r'\\ldots', '...', text)
    text = re.sub(r'\\dots', '...', text)
    
    # Remove any remaining LaTeX commands (pattern: backslash followed by letters)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def parse_pages(pages_str):
    """
    Normalize pages string to "start - end" format and return start, end, and count.
    Handles formats like '276--279', '276-279', '276', '276+', etc.
    Returns:
        tuple: (normalized_pages_str, page_count) or (None, None)
    """
    if not pages_str:
        return None, None

    # Clean LaTeX commands first
    pages_str = clean_latex_commands(pages_str).strip()

    # Match common formats including double hyphens
    # Covers: "123--456", "123-456", "123–456", "123—456"
    match = re.match(r'^(\d+)\s*[-–—]*\s*(\d+)?$', pages_str.replace('--', '-'))
    if match:
        start_page = int(match.group(1))
        end_page = int(match.group(2)) if match.group(2) else start_page
        normalized = f"{start_page} - {end_page}"
        count = end_page - start_page + 1
        return normalized, count
    else:
        # Handle "123+" format
        if re.match(r'^\d+\+$', pages_str):
            page = int(pages_str[:-1])
            return f"{page} - {page}", 1
        elif pages_str.isdigit():
            # Single page
            page = int(pages_str)
            return f"{page} - {page}", 1
        else:
            # Fallback: return as-is if parsing fails
            return pages_str, None

def clean_bibtex_key(text: str) -> str:
    """Clean text to create a valid BibTeX key."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s-]+', '_', text)
    text = text.strip('_')
    if text and not text[0].isalpha():
        text = 'key_' + text
    text = text[:50]
    return text

def clean_authors(authors_str: str) -> str:
    """Convert authors from semicolon-separated format to BibTeX format."""
    if not authors_str:
        return ""
    authors = authors_str.split(';')
    cleaned_authors = []
    for author in authors:
        author = author.strip()
        if ',' in author:
            parts = author.split(',')
            if len(parts) >= 2:
                last_name = parts[0].strip()
                first_name = parts[1].strip()
                cleaned_authors.append(f"{last_name}, {first_name}")
            else:
                cleaned_authors.append(author)
        else:
            name_parts = author.split()
            if len(name_parts) >= 2:
                last_name = name_parts[-1]
                first_name = ' '.join(name_parts[:-1])
                cleaned_authors.append(f"{last_name}, {first_name}")
            else:
                cleaned_authors.append(author)
    return " and ".join(cleaned_authors)

def clean_title(title: str) -> str:
    """Clean title for BibTeX format."""
    if not title:
        return ""
    title = title.replace('{', '\\{').replace('}', '\\}')
    title = title.replace('#', '\\#')
    title = title.replace('$', '\\$')
    title = title.replace('%', '\\%')
    title = title.replace('&', '\\&')
    title = title.replace('_', '\\_')
    title = title.replace('^', '\\^')
    title = title.replace('~', '\\~')
    return title

def escape_bibtex_field(text: str) -> str:
    """Escape special characters in BibTeX fields."""
    if not text:
        return ""
    text = text.replace('{', '\\{').replace('}', '\\}')
    text = text.replace('#', '\\#')
    text = text.replace('$', '\\$')
    text = text.replace('%', '\\%')
    text = text.replace('&', '\\&')
    text = text.replace('_', '\\_')
    text = text.replace('^', '\\^')
    text = text.replace('~', '\\~')
    text = text.replace('\\', '\\textbackslash{}')
    return text

def extract_month_from_date(date_str: str) -> str:
    """Extract month from date string like '30 May 2025'."""
    if not date_str:
        return ""
    try:
        # Split and try to extract month
        parts = date_str.split()
        if len(parts) >= 2:
            month_str = parts[1].lower()
            month_map = {
                'january': 'jan', 'february': 'feb', 'march': 'mar', 'april': 'apr',
                'may': 'may', 'june': 'jun', 'july': 'jul', 'august': 'aug',
                'september': 'sep', 'october': 'oct', 'november': 'nov', 'december': 'dec',
                'jan': 'jan', 'feb': 'feb', 'mar': 'mar', 'apr': 'apr',
                'jun': 'jun', 'jul': 'jul', 'aug': 'aug', 'sep': 'sep',
                'oct': 'oct', 'nov': 'nov', 'dec': 'dec'
            }
            return month_map.get(month_str, "")
    except Exception:
        pass
    return ""

def convert_csv_to_bibtex(csv_file_path: str) -> list[str]:
    """Convert a single CSV file to BibTeX entries."""
    bibtex_entries = []
    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row_idx, row in enumerate(reader):
            try:
                # Create a unique key for the entry
                title = row.get("Document Title", "")
                authors = row.get("Authors", "")
                if authors:
                    first_author = authors.split(';')[0].strip() if ';' in authors else authors.strip()
                    first_author_name = first_author.split()[-1] if first_author.split() else "Unknown"
                else:
                    first_author_name = "Unknown"
                year = row.get("Publication Year", "0000")
                title_part = clean_bibtex_key(title[:20]) if title else "title"
                key = f"{first_author_name}{year}{title_part}"
                
                # Ensure key is unique
                original_key = key
                counter = 1
                while any(entry.startswith(f"@article{{{key}") or
                          entry.startswith(f"@inproceedings{{{key}") or
                          entry.startswith(f"@conference{{{key}") or
                          entry.startswith(f"@book{{{key}") for entry in bibtex_entries):
                    key = f"{original_key}{counter}"
                    counter += 1
              
                # Determine entry type using the Document Identifier field
                doc_identifier = row.get("Document Identifier", "").strip().lower()
                if "conference" in doc_identifier:
                    entry_type = "inproceedings"
                elif "journal" in doc_identifier:
                    entry_type = "article"
                else:
                    # Fallback: try to determine from Publication Title if Document Identifier is not available
                    pub_title = row.get("Publication Title", "").lower()
                    if "conference" in pub_title or "inproceeding" in pub_title or "proceeding" in pub_title:
                        entry_type = "inproceedings"
                    elif "journal" in pub_title or "trans" in pub_title:
                        entry_type = "article"
                    else:
                        entry_type = "article"
                
                # Start building the BibTeX entry
                bibtex_entry = f"@{entry_type}{{{key},\n"
                if title:
                    bibtex_entry += f"  title = {{{clean_title(title)}}},\n"
                if authors:
                    bibtex_entry += f"  author = {{{clean_authors(authors)}}},\n"
                    
                pub_title = row.get("Publication Title", "")
                if pub_title:
                    if entry_type == "inproceedings":
                        bibtex_entry += f"  booktitle = {{{escape_bibtex_field(pub_title)}}},\n"
                    else:
                        bibtex_entry += f"  journal = {{{escape_bibtex_field(pub_title)}}},\n"
                        
                if year and year != "0000":
                    bibtex_entry += f"  year = {{{year}}},\n"
                    
                date_added = row.get("Date Added To Xplore", "")
                if date_added:
                    month = extract_month_from_date(date_added)
                    if month:
                        bibtex_entry += f"  month = {{{month}}},\n"
                        
                volume = row.get("Volume", "").strip()
                if volume:
                    bibtex_entry += f"  volume = {{{volume}}},\n"
                    
                issue = row.get("Issue", "").strip()
                if issue:
                    bibtex_entry += f"  number = {{{issue}}},\n"
                    
                start_page = row.get("Start Page", "").strip()
                end_page = row.get("End Page", "").strip()
                if start_page and end_page:
                    bibtex_entry += f"  pages = {{{start_page}--{end_page}}},\n"
                elif start_page:
                    bibtex_entry += f"  pages = {{{start_page}}},\n"
                    
                doi = row.get("DOI", "").strip()
                if doi:
                    bibtex_entry += f"  doi = {{{doi}}},\n"
                    
                issn = row.get("ISSN", "").strip()
                if issn:
                    bibtex_entry += f"  issn = {{{issn}}},\n"
                    
                isbn = row.get("ISBNs", "").strip()
                if isbn:
                    bibtex_entry += f"  isbn = {{{isbn}}},\n"
                    
                publisher = row.get("Publisher", "").strip()
                if publisher:
                    bibtex_entry += f"  publisher = {{{escape_bibtex_field(publisher)}}},\n"
                    
                abstract = row.get("Abstract", "").strip()
                if abstract:
                    bibtex_entry += f"  abstract = {{{escape_bibtex_field(abstract)}}},\n"
                    
                ieee_terms = row.get("IEEE Terms", "").strip()
                if ieee_terms:
                    # Convert semicolon-separated terms to comma-separated keywords
                    keywords = ieee_terms.replace(';', ',').replace('|', ',')
                    bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                    
                author_keywords = row.get("Author Keywords", "").strip()
                if author_keywords:
                    if ieee_terms:  # If we already have keywords, append to them
                        all_keywords = f"{ieee_terms}, {author_keywords}"
                        all_keywords = all_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(all_keywords)}}},\n"
                    else:
                        keywords = author_keywords.replace(';', ',').replace('|', ',')
                        bibtex_entry += f"  keywords = {{{escape_bibtex_field(keywords)}}},\n"
                        
                pdf_link = row.get("PDF Link", "").strip()
                if pdf_link:
                    bibtex_entry += f"  url = {{{pdf_link}}},\n"
                    
                citation_count = row.get("Article Citation Count", "").strip()
                if citation_count and citation_count != "0":
                    bibtex_entry += f"  note = {{Citations: {citation_count}}},\n"
                    
                if row.get("Document Identifier"):
                    doc_id = row.get("Document Identifier", "").strip()
                    if doc_id:
                        bibtex_entry += f"  file = {{{doc_id}}},\n"
                        
                ref_count = row.get("Reference Count", "").strip()
                if ref_count:
                    bibtex_entry += f"  references = {{{ref_count}}},\n"
                    
                funding = row.get("Funding Information", "").strip()
                if funding:
                    bibtex_entry += f"  funding = {{{escape_bibtex_field(funding)}}},\n"
                    
                mesh_terms = row.get("Mesh_Terms", "").strip()
                if mesh_terms:
                    bibtex_entry += f"  mesh = {{{escape_bibtex_field(mesh_terms)}}},\n"
                    
                bibtex_entry += "}\n"
                bibtex_entries.append(bibtex_entry)
            except Exception as e:
                print(f"Error processing row {row_idx + 2} in {csv_file_path}: {e}")
                continue
    return bibtex_entries

def pre_clean_latex_macros(text):
    """
    Remove/normalize common LaTeX macros before bibtexparser sees them.

    This is important because bibtexparser's old homogenize_latex_encoding
    helper can crash on macros like \textellipsis.
    """
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    if not text:
        return text

    replacements = {
        r'\textellipsis': '...',
        r'\ldots': '...',
        r'\dots': '...',
        r'\textendash': '-',
        r'\textemdash': '-',
        r'\endash': '-',
        r'\emdash': '-',
        r'\textquotedblleft': '"',
        r'\textquotedblright': '"',
        r'\&': '&',
        r'\%': '%',
        r'\_': '_',
        r'\#': '#',
        r'\$': '$',
        r'\{': '{',
        r'\}': '}',
        r'\^': '^',
        r'\~': '~',
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def clean_import_text(value):
    """
    Clean a BibTeX/LaTeX field for storage in the DB.

    This replaces the brittle bibtexparser homogenize_latex_encoding behavior
    with a deterministic local cleaner.
    """
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    value = pre_clean_latex_macros(value)
    value = clean_latex_commands(value)

    # Remove backslashes before non-letter escapes, e.g. \' -> '
    value = re.sub(r'\\([^a-zA-Z])', r'\1', value)

    return value.strip()

def normalize_title_for_comparison(title):
    """Normalize title for duplicate detection by removing case, extra whitespace, and common variations."""
    if not title:
        return ""
    
    # Convert to lowercase
    normalized = title.lower()
    
    # Remove extra whitespace and normalize spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common punctuation variations that don't change meaning
    # Replace various dash types with standard space
    normalized = re.sub(r'[-–—]', ' ', normalized)
    
    # Remove extra spaces created by dash replacement
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common leading/trailing punctuation
    normalized = normalized.strip(' .,;:')
    
    return normalized

def import_bibtex(bib_file, db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file '{db_path}' does not exist.")

    # v2 is orders of magnitude faster and fault-tolerant.
    print("[Import] Parsing BibTeX file...", flush=True)
    with open(bib_file, 'r', encoding='utf-8', errors='replace') as f:
        bib_string = f.read()
        
    library = bibtexparser.parse_string(bib_string)
    
    # Filter only actual entries (ignores comments, preambles, and malformed blocks)
    entries = [b for b in library.blocks if isinstance(b, Entry)]
    total_entries = len(entries)
    
    print(f"[Import] Parsed {total_entries} BibTeX entries.", flush=True)

    if total_entries == 0:
        print("Import completed: 0 records imported, 0 duplicates skipped", flush=True)
        return

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-64000")

        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
        if not cursor.fetchone():
            raise RuntimeError("The 'papers' table is missing.")

        placeholder_title = (
            "Database is missing or empty. Import BibTeX or restore from a backup to start working"
        )

        print("[Import] Locating placeholder row...", flush=True)
        cursor.execute("SELECT id FROM papers WHERE title = ?", (placeholder_title,))
        row = cursor.fetchone()
        placeholder_id = str(row[0]) if row else None

        print("[Import] Loading existing records for in-memory duplicate detection...", flush=True)
        existing_ids = set()
        existing_dois = set()
        existing_lower_titles = set()
        existing_normalized_title_year = set()

        cursor.execute("SELECT id, doi, title, year FROM papers")
        for pid, doi, title, year in cursor.fetchall():
            if pid is not None:
                pid_str = str(pid)
                if placeholder_id is not None and pid_str == placeholder_id:
                    continue
                existing_ids.add(pid_str)

            if doi:
                existing_dois.add(str(doi).strip().lower())

            if title and str(title) != placeholder_title:
                title_str = str(title)
                lower_title = title_str.strip().lower()
                if lower_title:
                    existing_lower_titles.add(lower_title)

                normalized_title = normalize_title_for_comparison(title_str)
                if normalized_title:
                    existing_normalized_title_year.add((normalized_title, year))

        print(
            f"[Import] Duplicate state loaded: "
            f"ids={len(existing_ids)} | "
            f"dois={len(existing_dois)} | "
            f"titles={len(existing_lower_titles)}",
            flush=True
        )

        schema_cols = [
            "id", "type", "title", "authors", "year", "month", "journal", "volume", 
            "pages", "page_count", "doi", "issn", "abstract", "keywords", 
            "deannualized_conference", "user_trace", "changed", "changed_by", 
            "verified", "verified_by", "estimated_score", "user_override_count", 
            "pdf_filename", "pdf_state", "main_certainty", "classification", 
            "set_1_llm", "set_2_llm", "set_3_llm", "set_1_llm_log", 
            "set_2_llm_log", "set_3_llm_log", "llm_log"
        ]

        insert_sql = f"""
            INSERT INTO papers ({", ".join(schema_cols)})
            VALUES ({", ".join(f":{col}" for col in schema_cols)})
        """

        batch = []
        batch_size = 1000
        processed_count = 0
        duplicate_count = 0       
        skipped_count = 0

        # Safe rectangle characters with ASCII fallback
        fill_char, empty_char = "█", "░"
        try:
            fill_char.encode(sys.stdout.encoding or 'utf-8')
            empty_char.encode(sys.stdout.encoding or 'utf-8')
        except Exception:
            fill_char, empty_char = "#", "."

        def print_progress(current):
            percent = int(current * 100 / total_entries)
            filled = int(50 * current / total_entries)
            bar = fill_char * filled + empty_char * (50 - filled)
            print(
                f"\rProgress:    [{bar}] {percent}% ({current}/{total_entries})",
                end='',
                flush=True
            )

        print(f"Starting import of {total_entries} entries...", flush=True)

        for idx, block in enumerate(entries, start=1):
            entry_type = str(block.entry_type or '').lower()
            
            # Skip entire proceedings (they are just metadata about the conference, not actual papers)
            if entry_type == 'proceedings':
                skipped_count += 1
                if idx % 100 == 0 or idx == total_entries:
                    print_progress(idx)
                continue

            # Normalize conference to inproceedings
            if entry_type == 'conference':
                entry_type = 'inproceedings'

            # v2 stores fields as objects; convert to a lowercase-keyed dict
            fields = {str(f.key).lower(): str(f.value) for f in block.fields}

            title = clean_latex_commands(fields.get('title', ''))
            doi_raw = clean_latex_commands(fields.get('doi', ''))
            doi_key = doi_raw.lower()

            year_str = str(fields.get('year', '') or '').strip()
            year = int(year_str) if year_str.isdigit() else None

            duplicate_found = False

            if doi_key and doi_key in existing_dois:
                duplicate_found = True

            if not duplicate_found and title:
                lower_title = title.strip().lower()
                normalized_title = normalize_title_for_comparison(title)

                if lower_title and lower_title in existing_lower_titles:
                    duplicate_found = True
                elif normalized_title and (normalized_title, year) in existing_normalized_title_year:
                    duplicate_found = True

            if not duplicate_found:
                original_id = str(block.key or '').strip()
                if not original_id:
                    original_id = clean_bibtex_key(title or "paper")

                final_id = original_id
                counter = 1
                while final_id in existing_ids:
                    final_id = f"{original_id}_{counter}"
                    counter += 1

                raw_pages = str(fields.get('pages', '') or '')
                normalized_pages, computed_page_count = parse_pages(raw_pages)

                numpages_str = str(fields.get('numpages', '') or '').strip()
                if numpages_str.isdigit():
                    page_count = int(numpages_str)
                else:
                    page_count = computed_page_count

                data = {col: None for col in schema_cols}

                data['id'] = final_id
                data['type'] = entry_type or 'misc'
                data['title'] = title
                data['authors'] = parse_authors(clean_latex_commands(fields.get('author', '')))
                data['year'] = year
                data['month'] = clean_latex_commands(fields.get('month', ''))
                data['journal'] = (
                    clean_latex_commands(fields.get('journal', ''))
                    or clean_latex_commands(fields.get('booktitle', ''))
                )
                data['volume'] = clean_latex_commands(fields.get('volume', ''))
                data['pages'] = normalized_pages
                data['page_count'] = page_count
                data['doi'] = doi_raw or None
                data['issn'] = clean_latex_commands(fields.get('issn', ''))
                data['abstract'] = clean_latex_commands(fields.get('abstract', ''))
                data['keywords'] = parse_keywords(clean_latex_commands(fields.get('keywords', '')))

                data['user_override_count'] = 0
                data['pdf_state'] = 'none'
                data['main_certainty'] = '{}'
                data['classification'] = '{}'
                data['set_1_llm_log'] = '[]'
                data['set_2_llm_log'] = '[]'
                data['set_3_llm_log'] = '[]'
                data['llm_log'] = '[]'

                # Update in-memory state immediately to catch duplicates inside the same file
                existing_ids.add(final_id)
                if doi_key:
                    existing_dois.add(doi_key)
                if title:
                    lower_title = title.strip().lower()
                    if lower_title:
                        existing_lower_titles.add(lower_title)
                    normalized_title = normalize_title_for_comparison(title)
                    if normalized_title:
                        existing_normalized_title_year.add((normalized_title, year))

                batch.append(data)
                processed_count += 1

                if len(batch) >= batch_size:
                    cursor.executemany(insert_sql, batch)
                    batch.clear()

            if idx % 100 == 0 or idx == total_entries:
                print_progress(idx)

        if batch:
            cursor.executemany(insert_sql, batch)
            batch.clear()

        if processed_count > 0 and placeholder_id is not None:
            cursor.execute("DELETE FROM papers WHERE id = ?", (placeholder_id,))
            print(f"\nRemoved placeholder record with id={placeholder_id}", flush=True)

        print("\n[Import] Committing transaction...", flush=True)
        conn.commit()

        print(
            f"Import completed: {processed_count} records imported, "
            f"{duplicate_count} duplicates skipped, "
            f"{skipped_count} proceedings skipped",
            flush=True
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()