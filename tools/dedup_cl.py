#!/usr/bin/env python3
# dedup_cleanup.py
"""
One-shot, silent cleanup of an existing ResearchParsa SQLite database.

Removes duplicate items from comma/semicolon-separated text fields
(model names, "other defects", etc.) wherever they are stored:

  * papers.classification / papers.last_llm_classification
  * papers.set_1_llm / set_2_llm / set_3_llm
  * the JSON "output" payload of every entry in papers.llm_log and
    papers.set_1..3_llm_log (free-form 'trace_review' reports skipped)

Deliberately does NOT touch:
  * audit columns (changed, changed_by, verified, verified_by, ...)
  * reasoning traces, user comments, keywords/authors metadata
  * rows whose content does not actually change

Pure standard library; does not import the application. Safe to run while
the web app / queue manager are up (WAL + busy timeout). Idempotent: a
second run changes nothing.

Usage:
    python dedup_cleanup.py [--db PATH] [--no-backup] [-v]
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys

_LIST_SEP_RE = re.compile(r'[,;]')
_WS_RE = re.compile(r'\s+')

# Log entry types whose "output" is free-form prose, not a classification blob.
_PROSE_LOG_TYPES = {'trace_review'}

BLOB_COLUMNS = (
    'classification',
    'last_llm_classification',
    'set_1_llm',
    'set_2_llm',
    'set_3_llm',
)
LOG_COLUMNS = (
    'llm_log',
    'set_1_llm_log',
    'set_2_llm_log',
    'set_3_llm_log',
)


def dedup_text_list(value):
    """Same semantics as shared/db.py: item-level, case-insensitive dedup."""
    if not isinstance(value, str):
        return value
    if ',' not in value and ';' not in value:
        return value
    seen = set()
    items = []
    for raw_item in _LIST_SEP_RE.split(value):
        item = _WS_RE.sub(' ', raw_item).strip().rstrip(',.').strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            items.append(item)
    return ', '.join(items)


def clean_obj(obj):
    """Recursively dedup all string leaves of a parsed JSON structure."""
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(v) for v in obj]
    if isinstance(obj, str):
        return dedup_text_list(obj)
    return obj


def _clean_blob(raw):
    """Return cleaned JSON text, or None if unchanged/unparseable."""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    cleaned = clean_obj(obj)
    if cleaned == obj:
        return None
    return json.dumps(cleaned)


def _clean_log(raw):
    """Clean the JSON 'output' payload of each log entry. Never touches traces."""
    if not raw:
        return None
    try:
        entries = json.loads(raw)
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    changed = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get('type') in _PROSE_LOG_TYPES:
            continue
        out_raw = entry.get('output')
        if not isinstance(out_raw, str) or not out_raw.strip():
            continue
        try:
            out_obj = json.loads(out_raw)
        except Exception:
            continue
        if not isinstance(out_obj, (dict, list)):
            continue
        cleaned_out = clean_obj(out_obj)
        if cleaned_out != out_obj:
            entry['output'] = json.dumps(cleaned_out)
            changed = True
    return json.dumps(entries) if changed else None


def main():
    parser = argparse.ArgumentParser(
        description="Silently deduplicate comma-separated text fields in a ResearchParsa database.")
    parser.add_argument('--db', default=None, help='Path to SQLite database '
                        '(default: $PARSA_DATABASE_FILE or <script_dir>/data/db.sqlite)')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip writing the .dedup-bak copy')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print a one-line summary (silent by default)')
    args = parser.parse_args()

    if args.db:
        db_path = os.path.abspath(args.db)
    else:
        db_path = os.environ.get('PARSA_DATABASE_FILE') or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'data', 'db.sqlite')
        db_path = os.path.abspath(db_path)

    if not os.path.exists(db_path):
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 1

    # Flush WAL so a plain file copy is a complete backup.
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    if not args.no_backup:
        shutil.copy2(db_path, db_path + '.dedup-bak')

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    touched_papers = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        cols = ', '.join(('id',) + BLOB_COLUMNS + LOG_COLUMNS)
        rows = cur.execute(f"SELECT {cols} FROM papers").fetchall()
        for row in rows:
            updates = {}
            for col in BLOB_COLUMNS:
                cleaned = _clean_blob(row[col])
                if cleaned is not None:
                    updates[col] = cleaned
            for col in LOG_COLUMNS:
                cleaned = _clean_log(row[col])
                if cleaned is not None:
                    updates[col] = cleaned
            if updates:
                touched_papers += 1
                assignments = ', '.join(f"{c} = ?" for c in updates)
                cur.execute(f"UPDATE papers SET {assignments} WHERE id = ?",
                            list(updates.values()) + [row['id']])
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"error: cleanup failed, database left unchanged: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if args.verbose:
        print(f"dedup complete: {touched_papers} paper(s) rewritten")
    return 0


if __name__ == '__main__':
    sys.exit(main())