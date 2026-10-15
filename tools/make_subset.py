#!/usr/bin/env python3
"""
make_subset.py

Create a reproducible random subset of the ResearchParsa `papers` table.

Important:
  Only entries with type 'article' or 'inproceedings' are considered.
  All other types are removed before sampling.

Default stratification preserves the ontopic/offtopic distribution of the
eligible source papers.

Off-topic definition defaults to the same rule used by the web UI's
hide_offtopic filter:

    classification.is_offtopic == true
    AND main_certainty.is_offtopic == 'solid'

Everything else is treated as on-topic.

Uses only the Python standard library.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict


PLACEHOLDER_TITLE = (
    "Database is missing or empty. Import BibTeX or restore from a backup to start working"
)

# Only these BibTeX entry types are allowed in the subset.
# This filter is applied BEFORE sampling.
ALLOWED_TYPES = {"article", "inproceedings"}

TRUE_STRINGS = {"1", "true", "yes", "on"}
FALSE_STRINGS = {"0", "false", "no", "off"}
NULL_STRINGS = {"", "null", "none", "unknown"}


def parse_json_blob(raw):
    """Parse a JSON blob column safely."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def tri_state(value):
    """
    Normalize an LLM/database boolean-ish value into:
      'true', 'false', 'null', or 'unusable'
    """
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"

    if isinstance(value, (int, float)):
        if value == 1:
            return "true"
        if value == 0:
            return "false"
        return "unusable"

    if isinstance(value, str):
        s = value.strip().lower()
        if s in TRUE_STRINGS:
            return "true"
        if s in FALSE_STRINGS:
            return "false"
        if s in NULL_STRINGS:
            return "null"
        return "unusable"

    return "unusable"


def label_paper(classification, certainty, label_mode):
    """
    Assign each paper to a sampling stratum.

    Modes:
      app:
        Matches the web UI hide_offtopic rule.
        offtopic = solid true
        everything else = ontopic

      majority:
        Uses the stored averaged classification directly.
        true  -> offtopic
        false -> ontopic
        null/unusable -> unknown

      strict:
        Requires solid certainty for both true and false.
        solid true  -> offtopic
        solid false -> ontopic
        otherwise   -> unknown
    """
    verdict = tri_state(classification.get("is_offtopic"))
    cert = str((certainty or {}).get("is_offtopic", "")).strip().lower()

    if label_mode == "app":
        return "offtopic" if verdict == "true" and cert == "solid" else "ontopic"

    if label_mode == "majority":
        if verdict == "true":
            return "offtopic"
        if verdict == "false":
            return "ontopic"
        return "unknown"

    # strict
    if verdict == "true" and cert == "solid":
        return "offtopic"
    if verdict == "false" and cert == "solid":
        return "ontopic"
    return "unknown"


def deterministic_sample(ids, k, seed):
    """
    Deterministically sample k IDs without replacement.

    Uses SHA-256 ordering instead of Python's random module so the result
    is stable across machines and Python runs.
    """
    if k <= 0:
        return []
    if k >= len(ids):
        return list(ids)

    def sort_key(paper_id):
        return hashlib.sha256(f"{seed}:{paper_id}".encode("utf-8")).hexdigest()

    return sorted(ids, key=sort_key)[:k]


def proportional_allocation(group_sizes, n):
    """
    Allocate n samples across groups proportionally to group sizes.

    Uses the largest remainder method so the total is exactly n.
    """
    total = sum(group_sizes.values())
    if total == 0:
        return {}
    if n >= total:
        return dict(group_sizes)

    raw = {g: size * n / total for g, size in group_sizes.items() if size > 0}
    floors = {g: int(raw[g]) for g in raw}
    counts = dict(floors)
    remainder = n - sum(counts.values())

    # Largest remainder, deterministic tie-break by group name.
    order = sorted(raw, key=lambda g: (-(raw[g] - floors[g]), g))

    i = 0
    while remainder > 0:
        g = order[i % len(order)]
        if counts.get(g, 0) < group_sizes[g]:
            counts[g] = counts.get(g, 0) + 1
            remainder -= 1
        i += 1

    for g in group_sizes:
        counts.setdefault(g, 0)

    return counts


def percent(count, total):
    if not total:
        return 0.0
    return round(100.0 * count / total, 2)


def main():
    ap = argparse.ArgumentParser(
        description="Create a reproducible random subset of ResearchParsa papers."
    )

    ap.add_argument(
        "--db",
        required=True,
        help="Source SQLite database, e.g. data/db.sqlite",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="New SQLite database to create, e.g. data/subset.sqlite",
    )
    ap.add_argument(
        "--n",
        type=int,
        required=True,
        help="Number of papers to select, e.g. 500",
    )
    ap.add_argument(
        "--seed",
        default="20260104",
        help="Seed for reproducible sampling",
    )
    ap.add_argument(
        "--label-mode",
        choices=["app", "majority", "strict"],
        default="app",
        help=(
            "app = UI hide_offtopic rule, solid true vs everything else; "
            "majority = classification.is_offtopic true/false/null; "
            "strict = solid true/false only, otherwise unknown"
        ),
    )
    ap.add_argument(
        "--unknown",
        choices=["keep", "drop", "ontopic", "offtopic"],
        default="keep",
        help="What to do with unknown labels in majority/strict modes",
    )
    ap.add_argument(
        "--no-stratify",
        action="store_true",
        help="Do simple reproducible random sampling without preserving label proportions",
    )
    ap.add_argument(
        "--include-placeholder",
        action="store_true",
        help=(
            "Include the placeholder row if present. "
            "Note: placeholder is usually type 'misc' and will still be excluded "
            "by the article/inproceedings filter."
        ),
    )
    ap.add_argument(
        "--ids-out",
        help="Optional path to also write selected paper IDs, one per line",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite --out if it exists",
    )

    args = ap.parse_args()

    if args.n < 0:
        sys.exit("--n must be >= 0")

    src_path = os.path.abspath(args.db)
    out_path = os.path.abspath(args.out)

    if not os.path.exists(src_path):
        sys.exit(f"Source database not found: {src_path}")

    if src_path == out_path:
        sys.exit("--out must be different from --db")

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if os.path.exists(out_path):
        if not args.force:
            sys.exit(f"Output file already exists: {out_path} (use --force to overwrite)")
        os.remove(out_path)

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    src.execute("PRAGMA busy_timeout = 30000")

    try:
        if not src.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers'"
        ).fetchone():
            sys.exit("Source database has no 'papers' table")

        rows = src.execute(
            """
            SELECT id, type, title, classification, main_certainty
            FROM papers
            ORDER BY id
            """
        ).fetchall()

    except sqlite3.Error as e:
        sys.exit(f"Could not read source database: {e}")

    groups = defaultdict(list)
    id_to_label = {}

    skipped_non_allowed_type = 0
    skipped_placeholder = 0

    for row in rows:
        paper_id = str(row["id"])
        entry_type = (row["type"] or "").strip().lower()
        title = row["title"] or ""

        # IMPORTANT: keep only article and inproceedings entries BEFORE sampling.
        if entry_type not in ALLOWED_TYPES:
            skipped_non_allowed_type += 1
            continue

        # Extra safety, although the type filter already excludes the usual placeholder.
        if not args.include_placeholder and title == PLACEHOLDER_TITLE:
            skipped_placeholder += 1
            continue

        classification = parse_json_blob(row["classification"])
        certainty = parse_json_blob(row["main_certainty"])

        label = label_paper(classification, certainty, args.label_mode)

        if label == "unknown":
            if args.unknown == "drop":
                continue
            if args.unknown == "ontopic":
                label = "ontopic"
            elif args.unknown == "offtopic":
                label = "offtopic"

        groups[label].append(paper_id)
        id_to_label[paper_id] = label

    for label in groups:
        groups[label].sort()

    population = {label: len(ids) for label, ids in groups.items()}
    total_available = sum(population.values())

    if total_available == 0:
        sys.exit(
            "No eligible papers found. "
            "Only entries with type 'article' or 'inproceedings' are eligible."
        )

    if args.n > total_available:
        sys.exit(f"--n={args.n} is larger than eligible paper count {total_available}")

    if args.no_stratify:
        all_ids = sorted(id_to_label.keys())
        selected_ids = deterministic_sample(all_ids, args.n, args.seed)
    else:
        counts = proportional_allocation(population, args.n)
        selected_ids = []

        for label in sorted(groups):
            sampled = deterministic_sample(
                groups[label],
                counts.get(label, 0),
                f"{args.seed}:{label}",
            )
            selected_ids.extend(sampled)

    selected_ids = sorted(set(selected_ids))

    if len(selected_ids) != args.n:
        sys.exit(
            f"Internal error: selected {len(selected_ids)} papers, expected {args.n}"
        )

    sample_counts = {}
    for paper_id in selected_ids:
        label = id_to_label[paper_id]
        sample_counts[label] = sample_counts.get(label, 0) + 1

    if args.ids_out:
        ids_out_path = os.path.abspath(args.ids_out)
        ids_out_dir = os.path.dirname(ids_out_path)
        if ids_out_dir:
            os.makedirs(ids_out_dir, exist_ok=True)

        with open(ids_out_path, "w", encoding="utf-8") as f:
            for paper_id in selected_ids:
                f.write(paper_id + "\n")

    dst = sqlite3.connect(out_path)

    try:
        schema = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='papers'"
        ).fetchone()[0]

        index_sqls = [
            row[0]
            for row in src.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name='papers' AND sql IS NOT NULL"
            )
        ]

        dst.execute("PRAGMA journal_mode = WAL")
        dst.execute(schema)

        cols = [r[1] for r in src.execute("PRAGMA table_info(papers)")]
        quoted_cols = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join("?" for _ in cols)
        insert_sql = f"INSERT INTO papers ({quoted_cols}) VALUES ({placeholders})"

        chunk_size = 500

        for i in range(0, len(selected_ids), chunk_size):
            chunk = selected_ids[i : i + chunk_size]
            in_placeholders = ", ".join("?" for _ in chunk)
            select_sql = (
                f"SELECT {quoted_cols} FROM papers WHERE id IN ({in_placeholders})"
            )

            for row in src.execute(select_sql, chunk):
                dst.execute(insert_sql, tuple(row))

        for sql in index_sqls:
            dst.execute(sql)

        dst.commit()

    finally:
        dst.close()
        src.close()

    summary = {
        "source_db": src_path,
        "output_db": out_path,
        "seed": str(args.seed),
        "allowed_types": sorted(ALLOWED_TYPES),
        "label_mode": args.label_mode,
        "unknown_handling": args.unknown,
        "stratified": not args.no_stratify,
        "requested_n": args.n,
        "selected_n": len(selected_ids),
        "skipped_non_allowed_type": skipped_non_allowed_type,
        "skipped_placeholder": skipped_placeholder,
        "population": population,
        "population_percent": {
            label: percent(count, total_available)
            for label, count in population.items()
        },
        "sample": sample_counts,
        "sample_percent": {
            label: percent(count, len(selected_ids))
            for label, count in sample_counts.items()
        },
    }

    if args.ids_out:
        summary["ids_out"] = os.path.abspath(args.ids_out)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()