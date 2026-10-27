# queue/state.py
import json
import os
import threading
from collections import deque

from shared import config, db
from shared.pdf_extractor import extract_pdf_markdown

from .logging_utils import (
    LOG_DIR,
    Colors,
    _color_prefix,
    _color_queue_mode,
    log,
    log_file_pdf_extraction,
    log_file_queue_status,
)

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
TASK_CLASSIFY = "classify"
TASK_VERIFY = "verify"
TASK_RECLASSIFY = "reclassify"
TASK_SCREEN = "screen"

# Score stamped on screened-off-topic sets so recalculate_main_set derives verified=True.
SCREENING_VERIFIED_SCORE = 10

# Relevance gate: only papers with relevance <= this are persisted as screened-off-topic.
# Anything above is logged as valid but left for full classification.
SCREENING_MAX_RELEVANCE = 2

# ============================================================================
# QUEUE STATE (Thread-Safe)
# ============================================================================
class QueueState:
    def __init__(self):
        self.lock = threading.Lock()
        self.task_queue = deque()
        self.in_flight = {TASK_CLASSIFY: 0, TASK_VERIFY: 0, TASK_RECLASSIFY: 0, TASK_SCREEN: 0}
        self.completion_event = threading.Event()
        self.completion_event.set()  # Start set so dispatcher doesn't block on empty queue
        self.shutdown = False
    
    def enqueue(self, task):
        with self.lock:
            self.task_queue.append(task)
        self.completion_event.set()  # Wake dispatcher
    
    def peek_queue(self):
        with self.lock:
            return self.task_queue[0] if self.task_queue else None
    
    def dequeue(self):
        with self.lock:
            return self.task_queue.popleft() if self.task_queue else None
    
    def increment_in_flight(self, task_type):
        with self.lock:
            self.in_flight[task_type] += 1
    
    def decrement_in_flight(self, task_type):
        with self.lock:
            self.in_flight[task_type] -= 1
        self.completion_event.set()  # CRITICAL: Wake dispatcher on ANY completion
    
    def get_total_in_flight(self):
        with self.lock:
            return sum(self.in_flight.values())
    
    def get_in_flight(self, task_type):
        with self.lock:
            return self.in_flight[task_type]
    
    def request_shutdown(self):
        self.shutdown = True
        self.completion_event.set()
    
    def is_shutdown(self):
        return self.shutdown
state = QueueState()

def log_queue_status():
    total_in_flight = state.get_total_in_flight()
    classify_in_flight = state.get_in_flight(TASK_CLASSIFY)
    verify_in_flight = state.get_in_flight(TASK_VERIFY)
    reclassify_in_flight = state.get_in_flight(TASK_RECLASSIFY)
    screen_in_flight = state.get_in_flight(TASK_SCREEN)
    queue_size = len(state.task_queue)

    if classify_in_flight == total_in_flight and classify_in_flight > 0:
        mode = f"HOMOGENEOUS_CLASSIFY (limit={config.MAX_CONCURRENT_WORKERS_CLASSIFY})"
    elif verify_in_flight == total_in_flight and verify_in_flight > 0:
        mode = f"HOMOGENEOUS_VERIFY (limit={config.MAX_CONCURRENT_WORKERS_VERIFY})"
    elif reclassify_in_flight == total_in_flight and reclassify_in_flight > 0:
        mode = f"HOMOGENEOUS_RECLASSIFY (limit={config.MAX_CONCURRENT_WORKERS_RECLASSIFY})"
    elif screen_in_flight == total_in_flight and screen_in_flight > 0:
        mode = f"HOMOGENEOUS_SCREEN (limit={config.MAX_CONCURRENT_WORKERS_SCREEN})"
    else:
        mode = f"MIXED (min_threshold={config.MIN_CONCURRENT_WORKERS})"

    log(f"{_color_prefix('QUEUE STATUS:', Colors.QUEUE_STATUS)} queue_size={queue_size} \t in_flight={total_in_flight} \t classify={classify_in_flight} \t verify={verify_in_flight} \t reclassify={reclassify_in_flight} \t screen={screen_in_flight} \t mode={_color_queue_mode(mode)}")
    log_file_queue_status(queue_size, total_in_flight, classify_in_flight, verify_in_flight, reclassify_in_flight, screen_in_flight, mode)

# ============================================================================
# SET STATE DERIVATION
# ============================================================================
# A set is in exactly one of these states. The state is derived from the
# CURRENT blob (set_N_llm) plus the most recent valid log entry that WROTE
# that blob. Superseded history is irrelevant.
#
#   pending           - is_offtopic is null → classification is awaited
#   screened_offtopic - latest blob-producing entry is a screener
#   classified        - full classification, but not verified / score < 7
#   done              - full classification verified with score >= 7
#
# Invariants this encodes:
#   * Screening never persists is_offtopic=false and never persists null.
#     Only is_offtopic=true is written to the blob by the screener. If a
#     blob has is_offtopic=null, it is pending classification, regardless
#     of any screener history entry.
#   * A paper is considered finished iff all three sets are screened_offtopic
#     OR all three sets are done. Any mix requires per-set action.

SET_STATE_PENDING           = 'pending'
SET_STATE_SCREENED_OFFTOPIC = 'screened_offtopic'
SET_STATE_CLASSIFIED        = 'classified'
SET_STATE_DONE              = 'done'

# Score threshold for "verified => done". Mirrors ConsensusStateMachine.
_VERIFIED_MIN_SCORE = 7


def _latest_blob_source(paper, set_num):
    """
    Return the origin of the current set_N_llm blob by walking set_N_llm_log
    backwards to the most recent valid entry that wrote a blob.

    Blob-producing entry types: 'screener', 'classifier', 'consensus'.
    'verifier' entries only patch verified/estimated_score on the existing
    blob, so they are skipped.

    Returns 'screener', 'classifier', or None if no blob-producing entry
    exists yet.
    """
    raw_log = paper.get(f'set_{set_num}_llm_log')
    try:
        log = json.loads(raw_log) if raw_log else []
    except Exception:
        log = []
    for entry in reversed(log):
        if not entry.get('valid'):
            continue
        t = entry.get('type')
        if t == 'screener':
            return 'screener'
        if t in ('classifier', 'consensus'):
            return 'classifier'
        # 'verifier' or unknown -> keep walking back to the blob's origin
    return None


def get_set_state(paper, set_num):
    """
    Derive the current logical state of set `set_num` for the given paper row.

    `paper` must contain the set_N_llm and set_N_llm_log columns (strings),
    as returned by db.get_paper_by_id() or a SELECT of those columns.
    """
    raw = paper.get(f'set_{set_num}_llm')
    try:
        blob = json.loads(raw) if raw else {}
    except Exception:
        blob = {}

    # Pending gate must come BEFORE source detection: the screener can log a
    # valid entry without persisting a blob (is_offtopic=false/null path), so
    # a null is_offtopic blob is always pending regardless of screener history.
    if blob.get('is_offtopic') is None:
        return SET_STATE_PENDING

    if _latest_blob_source(paper, set_num) == 'screener':
        # Screener only ever persists is_offtopic=true.
        return SET_STATE_SCREENED_OFFTOPIC

    # Full classification. Normalize legacy stringified booleans so the
    # decision matches the /consensus SQL gate that previously existed.
    verified = blob.get('verified')
    if isinstance(verified, str):
        s = verified.strip().lower()
        if s in ('true', '1', 'yes', 'on'):
            verified = True
        elif s in ('false', '0', 'no', 'off'):
            verified = False

    if verified is not True:
        return SET_STATE_CLASSIFIED

    score = blob.get('estimated_score')
    if score is not None:
        try:
            if float(score) < _VERIFIED_MIN_SCORE:
                return SET_STATE_CLASSIFIED
        except (TypeError, ValueError):
            return SET_STATE_CLASSIFIED

    return SET_STATE_DONE


def is_manual_user_override(paper):
    """
    True iff the main classification.is_offtopic is null AND that null was
    written by the user. A null produced by an unresolved conflict is NOT a
    manual override — those are handled by the normal per-set rules.
    """
    try:
        main_class = json.loads(paper.get('classification') or '{}')
    except Exception:
        main_class = {}
    if main_class.get('is_offtopic') is not None:
        return False
    return (paper.get('changed_by') or '').strip().lower() == 'user'

def plan_classify_actions(paper):
    """
    Planner for /classify mode=remaining (one-shot classification pass).

    Contract for this route:
      * Produces only classification tasks.
      * Never chains into verification or reclassification.
      * Never touches a set that already carries a real classification.

    Rules:
      1. Manual user override -> classify all three sets from scratch.
      2. All three sets screened_offtopic -> paper is done, no actions.
      3. All three sets done (classified+verified) -> paper is done, no actions.
      4. Otherwise (mixed / incomplete):
           - pending           -> classify
           - screened_offtopic -> promote to full classification (paper is mixed,
                                  so screening cannot be trusted for this set)
           - classified        -> skip (verification is /verify's concern;
                                       re-classifying would discard the blob
                                       and this route does not verify)
           - done              -> skip

    The second tuple element mirrors plan_consensus_actions. ClassificationStateMachine
    always produces a fresh classification, so it does not consume the flag; it is
    returned for symmetry and future-proofing.
    """
    if is_manual_user_override(paper):
        return [(n, True) for n in (1, 2, 3)]

    states = {n: get_set_state(paper, n) for n in (1, 2, 3)}

    if all(s == SET_STATE_SCREENED_OFFTOPIC for s in states.values()):
        return []
    if all(s == SET_STATE_DONE for s in states.values()):
        return []

    actions = []
    for n in (1, 2, 3):
        s = states[n]
        if s == SET_STATE_PENDING:
            actions.append((n, False))
        elif s == SET_STATE_SCREENED_OFFTOPIC:
            actions.append((n, True))
        # SET_STATE_CLASSIFIED and SET_STATE_DONE -> left alone.
    return actions

def plan_consensus_actions(paper):
    """
    Return a list of (set_num, force_initial_classify) tuples describing
    exactly which sets need work under the /consensus semantics.

    Rules (single source of truth):
      1. Manual user override (main is_offtopic is null AND changed_by=='user'):
         classify all three sets from scratch, unconditionally. History on
         individual sets is ignored by design.
      2. All three sets screened_offtopic -> paper is done, no actions.
      3. All three sets done              -> paper is done, no actions.
      4. Otherwise (mixed / incomplete):
           - done    -> never touched
           - screened-> promoted to full classification (force=True)
           - classified (not verified / score<7) -> passed to the consensus
             loop as-is; it will emit TASK_VERIFY or TASK_RECLASSIFY as needed
           - pending -> classified from scratch
    """
    if is_manual_user_override(paper):
        return [(n, True) for n in (1, 2, 3)]

    states = {n: get_set_state(paper, n) for n in (1, 2, 3)}

    if all(s == SET_STATE_SCREENED_OFFTOPIC for s in states.values()):
        return []
    if all(s == SET_STATE_DONE for s in states.values()):
        return []

    actions = []
    for n in (1, 2, 3):
        s = states[n]
        if s == SET_STATE_DONE:
            continue
        if s == SET_STATE_SCREENED_OFFTOPIC:
            actions.append((n, True))
        else:  # SET_STATE_CLASSIFIED or SET_STATE_PENDING
            actions.append((n, False))
    return actions

# ============================================================================
# PDF CONTENT HELPER
# ============================================================================

# Prompt dumps are gated on DEBUG_MODE (see shared/config.py) to avoid
# writing full paper text to disk during production runs.
PDF_PROMPT_DUMP_ENABLED = config.DEBUG_MODE

def _dump_pdf_prompt(paper_id, set_num, task_type, prompt_text):
    """Write the full assembled prompt to a debug file for inspection."""
    if not PDF_PROMPT_DUMP_ENABLED:
        return
    try:
        from datetime import datetime, timezone
        dump_dir = os.path.join(LOG_DIR, 'pdf_prompts')
        os.makedirs(dump_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{task_type}_paper{paper_id}_set{set_num}_{timestamp}.txt"
        path = os.path.join(dump_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(prompt_text)
        log(f"{_color_prefix('PDF DUMP:', Colors.DB)} {path}")
    except Exception as e:
        log(f"{_color_prefix('PDF DUMP ERROR:', Colors.ERROR)} {e}")


def _get_paper_content_for_prompt(paper):
    """
    Return (abstract_text, pdf_used).

    If the paper has a readable PDF, return extracted PDF Markdown.
    Otherwise return the normal abstract.

    pdf_used is True only when PDF text is actually injected into the prompt.
    """
    import os  # ensure available for _dump_pdf_prompt

    abstract_text = paper.get('abstract') or ''
    paper_id = paper.get('id')

    if not paper.get('pdf_filename'):
        return abstract_text, False

    try:
        pdf_text = extract_pdf_markdown(
            paper_id,
            paper.get('pdf_filename')
        )
    except Exception as exc:
        log(f"{_color_prefix('PDF:', Colors.ERROR)} paper={paper_id} extraction exception: {exc}")
        log_file_pdf_extraction(paper_id, pdf_used=False, error=str(exc))
        return abstract_text, False

    if pdf_text:
        log(f"{_color_prefix('PDF:', Colors.DB)} paper={paper_id} using PDF content ({len(pdf_text)} chars)")
        log_file_pdf_extraction(paper_id, pdf_used=True, text_length=len(pdf_text))
        return pdf_text, True

    log(f"{_color_prefix('PDF:', Colors.ERROR)} paper={paper_id} extraction returned empty, falling back to abstract")
    log_file_pdf_extraction(paper_id, pdf_used=False, error="extraction returned empty")
    return abstract_text, False

# ============================================================================
# STATE MACHINES
# ============================================================================
class ClassificationStateMachine:
    """State machine for classifying a SINGLE set of a single paper."""
    def __init__(self, paper_id, set_num, prompt_template, model_alias):
        self.paper_id = paper_id
        self.set_num = set_num
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.completion_callback = None
        self.lock = threading.Lock()
        self.pdf_used = False
        
    def get_prompts(self):
        """Generate exactly 1 classification task for this specific paper/set."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return []

        abstract_text, self.pdf_used = _get_paper_content_for_prompt(paper)

        prompt = self.prompt_template.format(
            title=paper.get('title', ''),
            abstract=abstract_text,
            keywords=paper.get('keywords', ''),
            authors=paper.get('authors', ''),
            year=paper.get('year', ''),
            type=paper.get('type', ''),
            journal=paper.get('journal', '')
        )

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, 'classify', prompt)

        task = {
            'task_type': TASK_CLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_classify",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }
        return [task]

    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when this single set classification completes."""
        if success and llm_data:
            is_valid, invalid_reason = config.validate_llm_output(llm_data, 'classify')
            if is_valid:
                effective_model = f"(PDF) {model_name}" if self.pdf_used else model_name
                db.update_set_cache(self.paper_id, set_num, llm_data, effective_model, reasoning_trace, json_result, valid=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Classify_Set{set_num}")
            else:
                log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={set_num} reason={invalid_reason}")
                db.update_set_log_only(self.paper_id, set_num, "classifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            db.update_set_log_only(self.paper_id, set_num, "classifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
        if self.completion_callback:
            self.completion_callback(self.paper_id, set_num, success)


class VerificationStateMachine:
    """State machine for verifying a SINGLE set of a single paper."""
    def __init__(self, paper_id, set_num, prompt_template, model_alias):
        self.paper_id = paper_id
        self.set_num = set_num
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.completion_callback = None
        self.lock = threading.Lock()
        self.pdf_used = False

    def get_prompts(self):
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return []

        abstract_text, self.pdf_used = _get_paper_content_for_prompt(paper)

        # Load the EXACT raw LLM output from the cached DB blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        format_data = {
            'title': paper.get('title', ''),
            'abstract': abstract_text,
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            # Pass the ENTIRE raw dictionary as a formatted JSON string
            'previous_classification_json': json.dumps(prev_class, indent=2)
        }

        prompt = self.prompt_template.format(**format_data)

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, 'verify', prompt)

        task = {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_verify",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }
        return [task]
    


    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when this single set verification completes."""
        if success and llm_data:
            is_valid, invalid_reason = config.validate_llm_output(llm_data, 'verify')
            if is_valid:
                effective_model = f"(PDF) {model_name}" if self.pdf_used else model_name
                db.update_set_verifier(self.paper_id, set_num, llm_data, effective_model, reasoning_trace, json_result, valid=True)
                db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Verify_Set{set_num}")
            else:
                log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={set_num} reason={invalid_reason}")
                db.update_set_log_only(self.paper_id, set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            db.update_set_log_only(self.paper_id, set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
        if self.completion_callback:
            self.completion_callback(self.paper_id, set_num, success)

class ConsensusStateMachine:
    """State machine for classify-until-consensus on a single paper/set."""
    def __init__(
        self,
        paper_id,
        set_num,
        classify_template,
        verify_template,
        reclassify_template,
        model_alias,
        force_initial_classify=False
    ):
        self.paper_id = paper_id
        self.set_num = set_num
        self.classify_template = classify_template
        self.verify_template = verify_template
        self.reclassify_template = reclassify_template
        self.model_alias = model_alias
        self.iteration = 0
        self.max_iterations = config.MAX_CONSENSUS_ITERATIONS
        self.fresh_fallback = config.FRESH_CLASSIFY_FALLBACK_ITERATION
        self.current_task_type = None
        self.completion_callback = None
        self.lock = threading.Lock()
        self.force_initial_classify = force_initial_classify
        self.pdf_used = False
        self._abstract_text = None


    def get_next_task(self):
        """Determine next task based on current paper state."""
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return None

        if self.iteration >= self.max_iterations:
            return None

        if self._abstract_text is None:
            self._abstract_text, self.pdf_used = _get_paper_content_for_prompt(paper)

        if self.force_initial_classify:
            self.force_initial_classify = False
            self.current_task_type = TASK_CLASSIFY
            return self._create_classify_task(paper)

        # 1. Load the raw LLM blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        # 2. Read UNIVERSAL audit fields to drive the state machine logic
        # (These exist in every domain by design)
        is_offtopic = prev_class.get('is_offtopic')
        verified = prev_class.get('verified')
        # Legacy-blob hardening: normalize stringified booleans on read so this
        # transition logic matches the /consensus batch SQL gate, which treats
        # verified IN (0, 'false', 'False') as unsettled. New writes are
        # normalized in db.update_set_verifier and never produce these.
        if isinstance(verified, str):
            s = verified.strip().lower()
            if s in ('true', '1', 'yes', 'on'):
                verified = True
            elif s in ('false', '0', 'no', 'off'):
                verified = False
        score = prev_class.get('estimated_score')

        if is_offtopic is None:
            self.current_task_type = TASK_CLASSIFY
            return self._create_classify_task(paper)
        elif verified is None:
            self.current_task_type = TASK_VERIFY
            return self._create_verify_task(paper)
        elif verified == False or verified == 0 or (score is not None and score < 7):
            self.iteration += 1
            if self.iteration == self.fresh_fallback:
                self.current_task_type = TASK_CLASSIFY
                return self._create_classify_task(paper)
            else:
                self.current_task_type = TASK_RECLASSIFY
                return self._create_reclassify_task(paper)
        else:
            return None

    def _create_classify_task(self, paper):
        prompt = self.classify_template.format(
            title=paper.get('title', ''),
            abstract=self._abstract_text,
            keywords=paper.get('keywords', ''),
            authors=paper.get('authors', ''),
            year=paper.get('year', ''),
            type=paper.get('type', ''),
            journal=paper.get('journal', '')
        )

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, f'consensus_classify_{self.iteration}', prompt)

        return {
            'task_type': TASK_CLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_classify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }

    def _create_verify_task(self, paper):
        """Create verification task for consensus state machine."""
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        format_data = {
            'title': paper.get('title', ''),
            'abstract': self._abstract_text,
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            # Pass the ENTIRE raw dictionary as a formatted JSON string
            'previous_classification_json': json.dumps(prev_class, indent=2)
        }

        prompt = self.verify_template.format(**format_data)

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, f'consensus_verify_{self.iteration}', prompt)

        return {
            'task_type': TASK_VERIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_verify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }

    def _create_reclassify_task(self, paper):
        """Create reclassification task for consensus state machine."""
        # 1. Load the EXACT raw LLM output from the cached DB blob
        raw_llm_data = paper.get(f'set_{self.set_num}_llm')
        try:
            prev_class = json.loads(raw_llm_data) if raw_llm_data else {}
        except Exception:
            prev_class = {}

        # 2. Extract traces dynamically from the main log
        latest_classifier_trace = ''
        latest_verifier_trace = ''
        try:
            llm_log = json.loads(paper.get('llm_log', '[]') or '[]')
            for entry in reversed(llm_log):
                if entry.get('type') in ['classifier', 'consensus', 'averaged_llm'] and entry.get('valid'):
                    latest_classifier_trace = entry.get('trace', '')
                    break
            for entry in reversed(llm_log):
                if entry.get('type') == 'verifier' and entry.get('valid'):
                    latest_verifier_trace = entry.get('trace', '')
                    break
        except Exception:
            pass

        # 3. Map directly to your validated reclassify_template.txt variables
        format_data = {
            'title': paper.get('title', ''),
            'abstract': self._abstract_text,
            'keywords': paper.get('keywords', ''),
            'authors': paper.get('authors', ''),
            'year': paper.get('year', ''),
            'type': paper.get('type', ''),
            'journal': paper.get('journal', ''),
            # Pass the EXACT raw LLM output as the JSON string.
            # No manual reconstruction needed! The LLM sees exactly what it spit out last time.
            'previous_classification_json': json.dumps(prev_class, indent=2),
            'reasoning_trace': latest_classifier_trace,
            'verifier_trace': latest_verifier_trace,
            'user_trace': paper.get('user_trace', '') or '',
        }

        prompt = self.reclassify_template.format(**format_data)

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, f'consensus_reclassify_{self.iteration}', prompt)

        return {
            'task_type': TASK_RECLASSIFY,
            'task_id': f"{self.paper_id}_set{self.set_num}_consensus_reclassify_{self.iteration}",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }

    def on_task_complete(self, success, llm_data, model_name, reasoning_trace, json_result):
        """Callback when a consensus task completes."""
        if success and llm_data:
            if self.current_task_type == TASK_CLASSIFY or self.current_task_type == TASK_RECLASSIFY:
                is_valid, invalid_reason = config.validate_llm_output(llm_data, 'classify')
                log_type = "consensus" if self.current_task_type == TASK_RECLASSIFY else "classifier"
                
                if is_valid:
                    effective_model = f"(PDF) {model_name}" if self.pdf_used else model_name
                    db.update_set_cache(self.paper_id, self.set_num, llm_data, effective_model, reasoning_trace, json_result, valid=True, log_type=log_type, reset_verification=True)
                    db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Classify_{self.iteration}")
                else:
                    log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={self.set_num} reason={invalid_reason}")
                    db.update_set_log_only(self.paper_id, self.set_num, log_type, model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
                    
            elif self.current_task_type == TASK_VERIFY:
                is_valid, invalid_reason = config.validate_llm_output(llm_data, 'verify')
                if is_valid:
                    effective_model = f"(PDF) {model_name}" if self.pdf_used else model_name
                    db.update_set_verifier(self.paper_id, self.set_num, llm_data, effective_model, reasoning_trace, json_result, valid=True)
                    db.recalculate_main_set(self.paper_id, changed_by=f"Consensus_Verify_{self.iteration}")
                else:
                    log(f"{_color_prefix('INVALID:', Colors.ERROR)} paper={self.paper_id} set={self.set_num} reason={invalid_reason}")
                    db.update_set_log_only(self.paper_id, self.set_num, "verifier", model_name, reasoning_trace, json_result, valid=False, invalid_reason=invalid_reason)
        else:
            # LLM call failed or returned non-JSON
            log_type = "error"
            if self.current_task_type == TASK_VERIFY: log_type = "verifier"
            elif self.current_task_type == TASK_RECLASSIFY: log_type = "consensus"
            else: log_type = "classifier"
            db.update_set_log_only(self.paper_id, self.set_num, log_type, model_name, reasoning_trace, json_result, valid=False, invalid_reason="LLM call failed or returned non-JSON")
            
        next_task = self.get_next_task()
        if next_task:
            state.enqueue(next_task)
        elif self.completion_callback:
            self.completion_callback(self.paper_id, self.set_num, success)

class ScreeningStateMachine:
    """Quick off-topic triage for a SINGLE set of a single paper.

    Outcome is binary by design:
      - obviously off-topic  -> write a minimal self-verified off-topic blob
      - anything else        -> leave the set untouched (still unclassified)

    Rides its own TASK_SCREEN lane (much higher concurrency than full
    classification, since these calls are tiny and thinking-disabled).
    """
    def __init__(self, paper_id, set_num, prompt_template, model_alias, llm_params):
        self.paper_id = paper_id
        self.set_num = set_num
        self.prompt_template = prompt_template
        self.model_alias = model_alias
        self.llm_params = llm_params
        self.completion_callback = None
        self.pdf_used = False

    def get_prompts(self):
        paper = db.get_paper_by_id(self.paper_id)
        if not paper:
            return []

        abstract_text, self.pdf_used = _get_paper_content_for_prompt(paper)

        prompt = self.prompt_template.format(
            title=paper.get('title', ''),
            abstract=abstract_text,
            keywords=paper.get('keywords', ''),
            authors=paper.get('authors', ''),
            year=paper.get('year', ''),
            type=paper.get('type', ''),
            journal=paper.get('journal', '')
        )

        if self.pdf_used:
            _dump_pdf_prompt(self.paper_id, self.set_num, 'screen', prompt)

        task = {
            'task_type': TASK_SCREEN,
            'task_id': f"{self.paper_id}_set{self.set_num}_screen",
            'paper_id': self.paper_id,
            'set_num': self.set_num,
            'model_alias': self.model_alias,
            'llm_params': self.llm_params,
            'pdf_used': self.pdf_used,
            'prompt': prompt,
            'state_machine': self
        }
        return [task]

    def on_set_complete(self, set_num, success, llm_data, model_name, reasoning_trace, json_result):
        if success and llm_data is not None:
            is_valid, invalid_reason = config.validate_llm_output(llm_data, 'screen')
            if is_valid:
                if llm_data.get('is_offtopic') is True:
                    # --- RELEVANCE GATE ---
                    # The screener flagged this paper. Check whether the relevance
                    # is low enough to actually skip full classification.
                    relevance = llm_data.get('relevance')
                    try:
                        rel_num = float(relevance)
                    except (TypeError, ValueError):
                        rel_num = None

                    if rel_num is not None and rel_num <= SCREENING_MAX_RELEVANCE:
                        # Below threshold: persist the screened blob (existing logic)
                        trace = reasoning_trace or "Screener ran and flagged the paper as off-topic in instruct mode (no thinking trace)"
                        paper = db.get_paper_by_id(self.paper_id)
                        raw = paper.get(f'set_{set_num}_llm') if paper else None
                        already_classified = False
                        if raw:
                            try:
                                already_classified = (json.loads(raw) or {}).get('is_offtopic') is not None
                            except Exception:
                                already_classified = False
                        if not already_classified:
                            screened = {
                                'research_area': llm_data.get('research_area'),
                                'is_offtopic': True,
                                'relevance': llm_data.get('relevance'),
                                'verified': True,
                                'estimated_score': SCREENING_VERIFIED_SCORE,
                            }
                            effective_model = f"(PDF) {model_name}" if self.pdf_used else model_name
                            db.update_set_cache(
                                self.paper_id, set_num, screened, effective_model,
                                trace, json.dumps(screened), valid=True, log_type="screener"
                            )
                            db.recalculate_main_set(self.paper_id, changed_by=f"LLM_Screen_Set{set_num}")
                    else:
                        # Above threshold: screener flagged it, but not off-topic enough.
                        # Log as VALID so /screen never retries this set.
                        # Discard the screener's classification output — the log
                        # entry is a screening mark only, not classification data.
                        trace = reasoning_trace or (
                            f"Screener flagged off-topic (relevance={rel_num}) but threshold "
                            f"is <= {SCREENING_MAX_RELEVANCE}; left for full classification."
                        )
                        db.update_set_log_only(
                            self.paper_id, set_num, "screener", model_name,
                            trace, "{}", valid=True
                        )
                else:
                    # is_offtopic is false or null.
                    # The screener's ONLY job is to flag off-topic papers.
                    # "Not off-topic" is NOT a screening decision — it is the
                    # absence of one. Discard the screener's output entirely.
                    # The set remains unclassified and proceeds to full
                    # classification via /consensus.
                    #
                    # Log as valid so /screen does not retry this set.
                    # Do NOT persist any classification blob or output.
                    trace = reasoning_trace or "Screener ran in instruct mode (no thinking trace) and did not flag the paper as off-topic; left for full classification."
                    db.update_set_log_only(
                        self.paper_id, set_num, "screener", model_name,
                        trace, "{}", valid=True
                    )
            else:
                # Refused: log the invalid screening, leave the set untouched.
                trace = reasoning_trace or f"Screener ran but returned an invalid answer; left for retry."
                log(f"{_color_prefix('INVALID:', Colors.ERROR)} screen paper={self.paper_id} set={set_num} reason={invalid_reason}")
                db.update_set_log_only(self.paper_id, set_num, "screener", model_name,
                                       trace, json_result, valid=False,
                                       invalid_reason=invalid_reason)
        else:
            trace = reasoning_trace or "Screening LLM call failed or returned non-JSON."
            db.update_set_log_only(self.paper_id, set_num, "screener", model_name,
                                   trace, json_result, valid=False,
                                   invalid_reason="Screening LLM call failed or returned non-JSON")

        if self.completion_callback:
            self.completion_callback(self.paper_id, set_num, success)