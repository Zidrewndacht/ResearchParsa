# fix_model_field.py
"""
Emergency one-shot fix for technique.model.

Rebuilds the "model" field of every on-topic paper so it lists ALL models
discussed in the paper (the paper's own model AND every baseline/competitor
it compares against), not just the paper's own model.

How it works:
  * Selects every paper whose averaged classification has is_offtopic == false.
  * For each paper, runs the SAME instruct-mode (non-thinking) LLM call three
    times (screening_llm_params), once per set, asking for the full model list.
  * Writes each answer into that set blob's technique.model, then re-averages
    the paper the normal way (db.recalculate_main_set). Text fields combine
    across sets, so anything any of the three runs found is kept.
  * Uses the full PDF whenever one is available, falling back to the abstract.

Deliberately minimal:
  * No idempotency markers: running this twice simply redoes the papers.
  * No user-override guards: this is meant to overwrite the model field.
  * No queue manager / HTTP involved: the script does everything itself.

Usage:
  python fix_model_field.py [--db path/to/db.sqlite] [--workers N]

Best run while the queue manager is idle.
"""
import argparse
import concurrent.futures
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import config, db
from shared.pdf_extractor import extract_pdf_markdown

PROMPT_TEMPLATE = """You are extracting one specific metadata field from an academic paper. Your ONLY task is to list every model mentioned in this paper.

Definition of "model" for this task:
- Any named architecture, network, or named trained system that appears in the paper.
- Include ALL of them: the authors' own proposed model AND every baseline, reference, or competitor model they compare against, benchmark with, or discuss.
- Examples of valid names: YOLOv3/v5/v8/v11, Faster R-CNN, Mask R-CNN, ResNet-50, VGG-16, EfficientNet, SSD, RetinaNet, DETR, RT-DETR, ViT, Swin, SegFormer, U-Net, named SVM/RF setups, etc.
- If the paper develops its own ML/DL model with or without giving it a name ("our model", "the proposed network"), include the token in-house in the list.
- Respect the publication era: never list models that postdate the paper's year.
- If the paper uses or discusses no learned models at all (pure classic image processing, no ML), answer null.

Paper:
*Title:* {title}
*Keywords:* {keywords}
*Authors:* {authors}
*Publication Year:* {year}
*Publication Type:* {type}
*Publication Name:* {journal}
*Abstract / Full Paper (when available):* {abstract}
-----
Remember, your response is not being read by a human, it goes directly to an automated parser. Output only a single JSON object in plaintext without any other tags like ```json or similar:
{{"model": "comma-separated list of ALL model names found in the paper"}}
or, when no model applies:
{{"model": null}}
"""

MODEL_ALIAS = None  # resolved in main()


def get_paper_content(paper):
    """Same rule as the normal pipeline: full PDF when available, else abstract."""
    if paper.get('pdf_filename'):
        try:
            pdf_text = extract_pdf_markdown(paper.get('id'), paper.get('pdf_filename'))
        except Exception as exc:
            print(f"  [PDF] paper={paper.get('id')} extraction failed ({exc}); using abstract")
            pdf_text = None
        if pdf_text:
            return pdf_text, True
    return paper.get('abstract') or '', False


def normalize_model_value(raw):
    """Coerce the LLM answer into the field's native shape: clean string or None."""
    if isinstance(raw, (list, tuple)):
        raw = ", ".join(str(x).strip() for x in raw if str(x).strip())
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"unexpected model value: {raw!r}")
    s = raw.strip()
    if not s or s.lower() in ('null', 'none', 'n/a', '-'):
        return None
    return db.dedup_text_list(s)


def process_set(paper_id, set_num):
    """One instruct-mode extraction, written into one set blob.
    Returns (success, value_written)."""
    try:
        paper = db.get_paper_by_id(paper_id)
        if not paper:
            return False, None
        abstract_text, _pdf_used = get_paper_content(paper)
        prompt = PROMPT_TEMPLATE.format(
            title=paper.get('title', '') or '',
            abstract=abstract_text,
            keywords=paper.get('keywords', '') or '',
            authors=paper.get('authors', '') or '',
            year=paper.get('year', '') or '',
            type=paper.get('type', '') or '',
            journal=paper.get('journal', '') or '',
        )
        content, _model_name, _trace = config.send_prompt_to_llm(
            prompt,
            model_name=MODEL_ALIAS,
            llm_params=config.SCREENING_LLM_PARAMS,
        )
        if content is None:
            print(f"  [FAIL] paper={paper_id} set={set_num}: LLM call failed")
            return False, None
        try:
            llm_data = json.loads(content)
        except json.JSONDecodeError:
            print(f"  [FAIL] paper={paper_id} set={set_num}: non-JSON answer: {content[:200]!r}")
            return False, None
        if not isinstance(llm_data, dict) or 'model' not in llm_data:
            print(f"  [FAIL] paper={paper_id} set={set_num}: missing 'model' key: {content[:200]!r}")
            return False, None
        value = normalize_model_value(llm_data.get('model'))

        with db.get_db() as conn:
            cur = conn.cursor()
            row = cur.execute(
                f"SELECT set_{set_num}_llm FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            raw = row[0] if row else None
            try:
                blob = json.loads(raw) if raw else {}
            except Exception:
                blob = {}
            tech = blob.get('technique')
            if not isinstance(tech, dict):
                # screened-offtopic or pending set -> nothing to patch
                return False, None
            tech['model'] = value
            cur.execute(
                f"UPDATE papers SET set_{set_num}_llm = ? WHERE id = ?",
                (json.dumps(blob), paper_id),
            )
        return True, value
    except Exception as exc:
        print(f"  [FAIL] paper={paper_id} set={set_num}: {exc}")
        return False, None


def main():
    global MODEL_ALIAS
    parser = argparse.ArgumentParser(description="ResearchParsa - emergency technique.model fix")
    parser.add_argument('--db', default=config.DATABASE_FILE, help='Path to SQLite database')
    parser.add_argument('--workers', type=int, default=None,
                        help='Concurrent LLM calls (default: max_concurrent_workers_screen)')
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    config.DATABASE_FILE = db_path
    db.init_db(db_path)

    if not config.SCREENING_LLM_PARAMS:
        sys.exit("Fatal: screening_llm_params not configured; this fix must run through the instruct pipeline.")

    MODEL_ALIAS = config.get_model_alias(config.LLM_SERVER_URL)
    workers = args.workers or config.MAX_CONCURRENT_WORKERS_SCREEN or 8

    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT id FROM papers
            WHERE LOWER(COALESCE(CAST(json_extract(classification, '$.is_offtopic') AS TEXT), '')) IN ('0', 'false')
            ORDER BY id
        """).fetchall()
    paper_ids = [r['id'] for r in rows]
    if not paper_ids:
        print("No on-topic papers found. Nothing to do.")
        return

    total = len(paper_ids)
    print(f"[Fix] {total} on-topic paper(s) x 3 instruct-mode calls, concurrency={workers}")
    print(f"[Fix] DB: {db_path}")

    sets_ok = sets_failed = papers_done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {pid: [ex.submit(process_set, pid, sn) for sn in (1, 2, 3)] for pid in paper_ids}
        try:
            for i, pid in enumerate(paper_ids, 1):
                results = [f.result() for f in futures[pid]]
                ok = [r for r in results if r[0]]
                if ok:
                    db.recalculate_main_set(pid, changed_by="ModelFix_Script")
                sets_ok += len(ok)
                sets_failed += 3 - len(ok)
                papers_done += 1
                found = " | ".join(r[1] for r in ok if r[1]) or "-"
                print(f"[{i}/{total}] paper={pid} patched={len(ok)}/3 models: {found}")
        except KeyboardInterrupt:
            print("\nInterrupted. Cancelling queued calls, waiting for in-flight ones...")
            for futs in futures.values():
                for f in futs:
                    f.cancel()
            print(f"Saved {papers_done}/{total} papers so far. Re-run the script to do the rest "
                  f"(already-done papers are simply redone).")
            sys.exit(1)

    print(f"[Fix] Done. papers={papers_done}/{total} set_runs_ok={sets_ok} set_runs_failed={sets_failed}")


if __name__ == '__main__':
    main()