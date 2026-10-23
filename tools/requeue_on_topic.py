"""
requeue_on_topic.py

Mark every currently ON-TOPIC (or conflicted/visible) paper for full reclassification.
OFF-TOPIC papers (as defined by the frontend's hide_offtopic logic) are never touched.

Mechanism (matches the app's planner contract):
    classification.is_offtopic == null AND changed_by == 'user'
        => manual user override
        => classify all three sets from scratch, ignoring set history.

This script performs a SURGICAL read-modify-write:
    - Sets classification.is_offtopic to null (preserving all other fields).
    - Removes is_offtopic from main_certainty (preventing "uncertain unknown" UI bugs).
    - Leaves set_N_llm, set_N_llm_log, and llm_log completely untouched.

Usage:
    python requeue_on_topic.py /path/to/papers.db             # dry run
    python requeue_on_topic.py /path/to/papers.db --apply     # real pass
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

UNUSABLE = object()

BUCKET_ORDER = (
    "on_topic", "off_topic", "already_marked",
    "unresolved", "unclassified", "invalid",
)


def is_definitively_offtopic(row):
    """
    Matches the frontend's hide_offtopic logic exactly:
    classification.is_offtopic is true AND main_certainty.is_offtopic == 'solid'
    """
    raw_class = row.get("classification")
    raw_cert = row.get("main_certainty")
    
    is_ot = None
    if raw_class:
        try:
            blob = json.loads(raw_class)
            is_ot = blob.get("is_offtopic")
        except Exception:
            pass
            
    if is_ot is None:
        return False
        
    if isinstance(is_ot, bool):
        is_ot_bool = is_ot
    elif isinstance(is_ot, str):
        is_ot_bool = is_ot.strip().lower() in ("true", "1", "yes", "on")
    elif isinstance(is_ot, (int, float)):
        is_ot_bool = bool(is_ot)
    else:
        is_ot_bool = False
        
    if not is_ot_bool:
        return False
        
    cert_val = None
    if raw_cert:
        try:
            cert_blob = json.loads(raw_cert)
            cert_val = cert_blob.get("is_offtopic")
        except Exception:
            pass
            
    return cert_val == "solid"


def bucket_of(row):
    """Classify the PAPER-LEVEL verdict."""
    raw = row.get("classification")
    if raw is None or not str(raw).strip():
        return "unclassified"

    try:
        blob = json.loads(raw)
    except (TypeError, ValueError):
        return "invalid"
    if not isinstance(blob, dict):
        return "invalid"

    if "is_offtopic" not in blob:
        return "unclassified"

    if is_definitively_offtopic(row):
        return "off_topic"

    # Not definitively off-topic
    is_ot_raw = blob.get("is_offtopic")
    if is_ot_raw is None:
        who = (row.get("changed_by") or "").strip().lower()
        return "already_marked" if who == "user" else "unresolved"

    return "on_topic"


def open_db(path, readonly=False):
    if readonly:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                               uri=True, timeout=30, isolation_level=None)
    else:
        conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def snapshot_backup(path):
    """Consistent backup via the SQLite backup API (WAL-safe)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(f"{path.stem}.before-on-topic-requeue-{stamp}{path.suffix}")
    src = sqlite3.connect(str(path), timeout=30)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="Path to the papers SQLite database")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write the sentinel (default: dry run)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of papers (canary run)")
    ap.add_argument("--verbose", action="store_true", help="Print every affected id")
    args = ap.parse_args()

    db = args.db.expanduser().resolve()
    if not db.is_file():
        ap.error(f"database not found: {db}")
    if args.limit is not None and args.limit <= 0:
        ap.error("--limit must be positive")

    # ---- 1. Scan a snapshot; no write transaction held -------------------
    conn = open_db(db, readonly=True)
    try:
        cursor = conn.execute(
            "SELECT id, classification, changed_by, main_certainty FROM papers ORDER BY id"
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    counts = Counter()
    targets = []
    for row in rows:
        bucket = bucket_of(row)
        counts[bucket] += 1
        if bucket == "on_topic":
            targets.append(row["id"])

    print(f"Scanned {len(rows)} papers")
    for bucket in BUCKET_ORDER:
        print(f"  {bucket:<16} {counts[bucket]:>7}")

    if counts["invalid"]:
        print("WARNING: unreadable/invalid main blobs were skipped, not modified.")

    if args.limit is not None:
        targets = targets[:args.limit]
        print(f"  --limit applied: {len(targets)} candidates")

    if not targets:
        print("Nothing to requeue.")
        return 0

    if args.verbose:
        for pid in targets:
            print(f"  requeue paper {pid}")
    else:
        print("  examples: " + ", ".join(str(p) for p in targets[:10]))

    if not args.apply:
        print(f"\nDRY RUN — {len(targets)} papers would be marked. "
              f"Re-run with --apply to write.")
        return 0

    # ---- 2. Backup, then one short write transaction --------------------
    backup_path = snapshot_backup(db)
    print(f"\nBackup: {backup_path}")

    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = open_db(db, readonly=False)
    marked = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for pid in targets:
            # Read current blobs
            row = conn.execute(
                "SELECT classification, main_certainty FROM papers WHERE id = ?", 
                (pid,)
            ).fetchone()
            
            if not row:
                raise RuntimeError(f"paper {pid} disappeared mid-pass")

            # 1. Surgically update classification blob
            try:
                class_blob = json.loads(row["classification"]) if row["classification"] else {}
            except Exception:
                class_blob = {}
            
            class_blob["is_offtopic"] = None  # Reset off-topic, preserve all other fields
            
            # 2. Surgically update main_certainty blob
            try:
                cert_blob = json.loads(row["main_certainty"]) if row["main_certainty"] else {}
            except Exception:
                cert_blob = {}
                
            cert_blob.pop("is_offtopic", None)  # Remove certainty to prevent "solid unknown" UI bugs

            # 3. Write back
            conn.execute(
                """UPDATE papers 
                   SET classification = ?, 
                       main_certainty = ?, 
                       changed = ?, 
                       changed_by = 'user' 
                   WHERE id = ?""",
                (json.dumps(class_blob), json.dumps(cert_blob), stamp, pid)
            )
            marked += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"Marked {marked} papers for classification.")
    print("Next: run your /consensus pass (or /classify mode=remaining).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)