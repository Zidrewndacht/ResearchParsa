#!/usr/bin/env python3
"""
make_subset.py

Create a reproducible random subset of the ResearchParsa `papers` table.

Guarantees
----------
* Only `article` and `inproceedings` entries are eligible.
  This filter is applied BEFORE stratification, quota checks and sampling.
* Exactly --n papers are written, or the script fails with a clear error.
* Sampling is deterministic for a given --seed (SHA-256 ordering).

Sampling modes
--------------
1. Proportional (default)
     --n 2000
   Preserves the eligible source on-topic / off-topic ratio.

2. Quota mode (fixed on-topic stratum)
     --n 2000 --ontopic 200
   Exactly 200 on-topic papers. The remaining 1800 are allocated
   proportionally across the OTHER strata.

     --ontopic 200 --offtopic 1800
   Both strata fixed; --n is inferred as 2000.

3. Unstratified
     --n 2000 --no-stratify
   Simple reproducible random sample of the eligible papers.

Off-topic definition (default, matches the UI hide_offtopic filter)
-----------------------------------------------------------------
    classification.is_offtopic == true
    AND main_certainty.is_offtopic == 'solid'

Everything else counts as on-topic. Use --label-mode strict with
--unknown drop if you only want confidently classified papers.

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

# Applied BEFORE sampling. Nothing else can ever reach the output database.
ALLOWED_TYPES = {"article", "inproceedings"}

TRUE_STRINGS = {"1", "true", "yes", "on"}
FALSE_STRINGS = {"0", "false", "no", "off"}
NULL_STRINGS = {"", "null", "none", "unknown"}


# --------------------------------------------------------------------------
# Label handling
# --------------------------------------------------------------------------

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
    """Normalize a boolean-ish LLM value to 'true' / 'false' / 'null' / 'unusable'."""
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
    Assign a paper to a sampling stratum.

    app:      solid true -> offtopic; everything else -> ontopic
              (matches the UI's hide_offtopic rule)
    majority: true -> offtopic, false -> ontopic, else unknown
    strict:   solid true -> offtopic, solid false -> ontopic, else unknown
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


# --------------------------------------------------------------------------
# Reproducible sampling
# --------------------------------------------------------------------------

def deterministic_sample(ids, k, seed):
    """
    Deterministically sample k IDs without replacement.

    SHA-256 ordering is used instead of Python's random module so results
    are stable across machines, Python versions and runs.
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
    Allocate n across groups in proportion to their sizes.

    Largest-remainder method with deterministic tie-breaking, so the sum
    is exactly n and no group is over-allocated.
    """
    total = sum(group_sizes.values())
    if total == 0:
        return {}
    if n >= total:
        return dict(group_sizes)
    if n <= 0:
        return {g: 0 for g in group_sizes}

    raw = {g: size * n / total for g, size in group_sizes.items() if size > 0}
    floors = {g: int(raw[g]) for g in raw}
    counts = dict(floors)
    remainder = n - sum(counts.values())

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


def resolve_targets(population, n, ontopic_wanted, offtopic_wanted):
    """
    Return (targets, mode).

    Quota mode is active if either --ontopic or --offtopic was supplied.
    Fixed quotas are honored EXACTLY; the remaining budget is distributed
    proportionally over all other strata (including 'unknown', if present).

    A quota of 0 is meaningful and is honored (it is not treated as 'unset').
    """
    has_quota = ontopic_wanted is not None or offtopic_wanted is not None

    if not has_quota:
        if n > sum(population.values()):
            sys.exit(
                f"--n={n} exceeds the eligible population "
                f"({sum(population.values())}) after the type filter."
            )
        return proportional_allocation(population, n), "proportional"

    targets = {}
    fixed_total = 0

    for label, wanted in (("ontopic", ontopic_wanted), ("offtopic", offtopic_wanted)):
        if wanted is None:
            continue
        if wanted < 0:
            sys.exit(f"--{label} must be >= 0, got {wanted}")

        available = population.get(label, 0)
        if wanted > available:
            sys.exit(
                f"--{label}={wanted} cannot be satisfied: only {available} "
                f"eligible '{label}' papers exist after filtering "
                f"(label-mode and --unknown handling applied). "
                f"Requested subset size is --n={n}."
            )

        targets[label] = wanted
        fixed_total += wanted

    if fixed_total > n:
        sys.exit(
            f"Fixed quotas sum to {fixed_total}, which exceeds --n={n}."
        )

    remaining = n - fixed_total
    other = {
        label: count
        for label, count in population.items()
        if label not in targets and count > 0
    }
    other_total = sum(other.values())

    if remaining > 0:
        if other_total < remaining:
            sys.exit(
                f"Cannot reach --n={n}: fixed quotas consume {fixed_total}, "
                f"but the remaining strata contain only {other_total} papers. "
                "Lower --n, lower a quota, or change --unknown / --label-mode."
            )
        targets.update(proportional_allocation(other, remaining))

    for label in population:
        targets.setdefault(label, 0)

    return targets, "quota"


def percent(count, total):
    return round(100.0 * count / total, 2) if total else 0.0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Create a reproducible random subset of ResearchParsa papers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --db data/db.sqlite --out sub.sqlite --n 2000\n"
            "  %(prog)s --db data/db.sqlite --out sub.sqlite --n 2000 --ontopic 200\n"
            "  %(prog)s --db data/db.sqlite --out sub.sqlite --ontopic 200 --offtopic 1800\n"
            "  %(prog)s --db data/db.sqlite --out sub.sqlite --n 500 --no-stratify\n"
        ),
    )

    ap.add_argument("--db", required=True, help="Source SQLite database")
    ap.add_argument("--out", required=True, help="New SQLite database to create")

    ap.add_argument(
        "--n",
        type=int,
        default=None,
        help="Total subset size. Optional if both --ontopic and --offtopic are given.",
    )
    ap.add_argument(
        "--ontopic",
        type=int,
        default=None,
        help=(
            "Exact number of on-topic papers. Enables quota mode. "
            "Remaining budget goes to the other strata. 0 is honored."
        ),
    )
    ap.add_argument(
        "--offtopic",
        type=int,
        default=None,
        help="Exact number of off-topic papers. Enables quota mode. 0 is honored.",
    )

    ap.add_argument("--seed", default="20260104", help="Reproducibility seed")

    ap.add_argument(
        "--label-mode",
        choices=["app", "majority", "strict"],
        default="app",
        help=(
            "app = UI hide_offtopic rule (solid true vs everything else); "
            "majority = raw averaged true/false/null; "
            "strict = solid true/false only, otherwise unknown"
        ),
    )
    ap.add_argument(
        "--unknown",
        choices=["keep", "drop", "ontopic", "offtopic"],
        default="keep",
        help="How to handle unknown labels in majority/strict modes",
    )

    ap.add_argument(
        "--no-stratify",
        action="store_true",
        help="Simple reproducible random sampling; cannot be combined with quotas",
    )
    ap.add_argument(
        "--include-placeholder",
        action="store_true",
        help="Include the placeholder row if present (usually excluded by the type filter anyway)",
    )
    ap.add_argument("--ids-out", help="Also write selected paper IDs, one per line")
    ap.add_argument("--force", action="store_true", help="Overwrite --out if it exists")

    args = ap.parse_args()

    # ---- Resolve total size ------------------------------------------------
    if args.ontopic is None and args.offtopic is None:
        if args.n is None:
            ap.error("--n is required unless --ontopic/--offtopic quotas are supplied")
        n = args.n
    else:
        if args.no_stratify:
            ap.error("--no-stratify cannot be combined with --ontopic/--offtopic")

        if args.ontopic is not None and args.offtopic is not None:
            implied = args.ontopic + args.offtopic
            if args.n is not None and args.n != implied:
                ap.error(
                    f"--n={args.n} conflicts with --ontopic + --offtopic = {implied}"
                )
            n = implied
        else:
            if args.n is None:
                ap.error(
                    "--n is required when only one of --ontopic/--offtopic is given "
                    "(the other stratum receives the remainder)."
                )
            n = args.n

    if n < 0:
        ap.error("--n must be >= 0")

    # ---- Paths -------------------------------------------------------------
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
            sys.exit(f"Output already exists: {out_path} (use --force to overwrite)")
        os.remove(out_path)

    # ---- Read + filter + stratify -----------------------------------------
    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    src.execute("PRAGMA busy_timeout = 30000")

    groups = defaultdict(list)
    id_to_label = {}
    skipped_non_allowed_type = 0
    skipped_placeholder = 0
    skipped_unknown = 0

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

        for row in rows:
            paper_id = str(row["id"])
            entry_type = (row["type"] or "").strip().lower()
            title = row["title"] or ""

            # HARD FILTER: only these two types are eligible, before sampling.
            if entry_type not in ALLOWED_TYPES:
                skipped_non_allowed_type += 1
                continue

            if not args.include_placeholder and title == PLACEHOLDER_TITLE:
                skipped_placeholder += 1
                continue

            classification = parse_json_blob(row["classification"])
            certainty = parse_json_blob(row["main_certainty"])
            label = label_paper(classification, certainty, args.label_mode)

            if label == "unknown":
                if args.unknown == "drop":
                    skipped_unknown += 1
                    continue
                if args.unknown == "ontopic":
                    label = "ontopic"
                elif args.unknown == "offtopic":
                    label = "offtopic"

            groups[label].append(paper_id)
            id_to_label[paper_id] = label

    except sqlite3.Error as e:
        sys.exit(f"Could not read source database: {e}")
    finally:
        if not groups and "src" in locals():
            src.close()

    for label in groups:
        groups[label].sort()

    population = {label: len(ids) for label, ids in groups.items()}
    total_available = sum(population.values())

    if total_available == 0:
        sys.exit(
            "No eligible papers found. Only 'article' and 'inproceedings' "
            "entries are eligible."
        )

    # ---- Sample ------------------------------------------------------------
    if args.no_stratify:
        if n > total_available:
            sys.exit(f"--n={n} exceeds the eligible population {total_available}")
        targets = None
        mode = "random"
        selected_ids = deterministic_sample(sorted(id_to_label), n, args.seed)
    else:
        targets, mode = resolve_targets(
            population, n, args.ontopic, args.offtopic
        )
        selected_ids = []
        for label in sorted(groups):
            selected_ids.extend(
                deterministic_sample(
                    groups[label],
                    targets.get(label, 0),
                    f"{args.seed}:{label}",
                )
            )

    selected_ids = sorted(set(selected_ids))

    if len(selected_ids) != n:
        sys.exit(f"Internal error: selected {len(selected_ids)}, expected {n}")

    sample_counts = defaultdict(int)
    for paper_id in selected_ids:
        sample_counts[id_to_label[paper_id]] += 1

    # ---- Optional ID manifest ---------------------------------------------
    if args.ids_out:
        ids_path = os.path.abspath(args.ids_out)
        ids_dir = os.path.dirname(ids_path)
        if ids_dir:
            os.makedirs(ids_dir, exist_ok=True)
        with open(ids_path, "w", encoding="utf-8") as f:
            for paper_id in selected_ids:
                f.write(paper_id + "\n")

    # ---- Write output database --------------------------------------------
    output_type_counts = {}

    try:
        schema = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='papers'"
        ).fetchone()[0]

        index_sqls = [
            r[0]
            for r in src.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name='papers' AND sql IS NOT NULL"
            )
        ]

        dst = sqlite3.connect(out_path)
        try:
            dst.execute("PRAGMA journal_mode = WAL")
            dst.execute(schema)

            cols = [r[1] for r in src.execute("PRAGMA table_info(papers)")]
            quoted_cols = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join("?" for _ in cols)
            insert_sql = f"INSERT INTO papers ({quoted_cols}) VALUES ({placeholders})"

            chunk_size = 500
            for i in range(0, len(selected_ids), chunk_size):
                chunk = selected_ids[i : i + chunk_size]
                in_ph = ", ".join("?" for _ in chunk)
                select_sql = (
                    f"SELECT {quoted_cols} FROM papers WHERE id IN ({in_ph})"
                )
                for row in src.execute(select_sql, chunk):
                    dst.execute(insert_sql, tuple(row))

            for sql in index_sqls:
                dst.execute(sql)

            dst.commit()

            # Defense in depth: verify the written database really only
            # contains the two allowed entry types.
            output_type_counts = {
                r[0]: r[1]
                for r in dst.execute(
                    "SELECT LOWER(TRIM(COALESCE(type, ''))), COUNT(*) "
                    "FROM papers GROUP BY 1"
                )
            }
            unexpected = set(output_type_counts) - ALLOWED_TYPES
            if unexpected:
                raise RuntimeError(
                    f"Type filter violated in output: {sorted(unexpected)}"
                )

            written_count = dst.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            if written_count != n:
                raise RuntimeError(
                    f"Output contains {written_count} papers, expected {n}"
                )
        finally:
            dst.close()
    finally:
        src.close()

    # ---- Report ------------------------------------------------------------
    summary = {
        "source_db": src_path,
        "output_db": out_path,
        "seed": str(args.seed),
        "allowed_types": sorted(ALLOWED_TYPES),
        "label_mode": args.label_mode,
        "unknown_handling": args.unknown,
        "mode": mode,
        "quota_request": {
            "ontopic": args.ontopic,
            "offtopic": args.offtopic,
        },
        "requested_n": n,
        "written_n": written_count,
        "skipped_non_allowed_type": skipped_non_allowed_type,
        "skipped_placeholder": skipped_placeholder,
        "skipped_unknown": skipped_unknown,
        "eligible_population": population,
        "eligible_population_percent": {
            label: percent(count, total_available)
            for label, count in population.items()
        },
        "targets": targets,
        "sample": dict(sample_counts),
        "sample_percent": {
            label: percent(count, written_count)
            for label, count in sample_counts.items()
        },
        "output_type_counts": output_type_counts,
    }

    if args.ids_out:
        summary["ids_out"] = os.path.abspath(args.ids_out)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()