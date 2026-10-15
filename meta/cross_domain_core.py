"""
cross_domain_core.py
====================

Cross-domain (S1 vs S2) comparison support for the "constrained agentic
pipeline" paper.

Two layers live here:

  A) PURE BUILDERS -- consume the ``results`` dicts produced by
     ``agreement_core.run_analysis`` and emit
       * the ``{tab:cross_domain}`` LaTeX table (Elsevier cas-sc, 2 col),
       * the ``\\placeholder*`` macros the manuscript still needs for the
         S2 / RQ4 narrative,
       * a plain-python summary dict (reusable by paper_macros_cli / tests).

  B) A THIN LOADING SHIM (bottom of file) that resolves two DB files into
     two ``results`` dicts, adapting to whichever loader symbol
     ``agreement_core`` exposes.

Nothing in section A touches SQLite or YAML.
"""

from __future__ import annotations

import inspect
import math
import os
import sys
from typing import Any, Callable, Iterable, Sequence

try:
    from meta import agreement_core as ac
except ImportError:                                    # running from inside meta/
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import agreement_core as ac

try:
    import yaml
except ImportError:                                    # pragma: no cover
    yaml = None


# ==========================================================================
# NUMERIC / FORMATTING HELPERS
# ==========================================================================

_Z95 = 1.959963984540054

_CEILING_STEPS: tuple[float, ...] = (
    0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9,
    1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0,
)


def wilson_ci(count: int, n: int) -> tuple[float, float]:
    """Wilson score interval in percent. Delegates to agreement_core when
    available so every table in the paper shares one implementation."""
    count, n = int(count or 0), int(n or 0)
    if n <= 0:
        return (0.0, 0.0)
    fn = getattr(ac, "wilson_score_interval", None)
    if callable(fn):
        try:
            lo, hi = fn(count, n)
            return (float(lo), float(hi))
        except Exception:
            pass
    z, p = _Z95, count / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / den
    return (max(0.0, (centre - half) * 100), min(100.0, (centre + half) * 100))


def pct_of(count: int, n: int) -> float:
    return (int(count) / int(n) * 100.0) if n else 0.0


def nice_ceiling(value: float) -> float:
    """Smallest 'pretty' number >= value. 0.59 -> 0.6 (matches the
    \\placeholderContradictionCeiling used in the highlights/abstract)."""
    v = float(value)
    if v <= 0:
        return 0.1
    for s in _CEILING_STEPS:
        if v <= s + 1e-12:
            return s
    return float(math.ceil(v))


def fmt_trim(v: float) -> str:
    """0.60 -> '0.6',  12.20 -> '12.2',  87.21 -> '87.21'."""
    return f"{float(v):.2f}".rstrip("0").rstrip(".")


def _i(stratum: dict, key: str) -> int:
    return int(stratum.get(key, 0) or 0)


def _f(stratum: dict, key: str) -> float:
    return float(stratum.get(key, 0.0) or 0.0)


def _fmt_field(raw: str, label_map: dict[str, str] | None = None) -> str:
    """json path -> display label, verbatim from config when available."""
    raw = str(raw)
    if label_map and raw in label_map:
        out = label_map[raw]
    else:
        fn = getattr(ac, "format_field_name", None)
        out = fn(raw) if callable(fn) else raw.replace(".", " > ").replace("_", " ").title()
    esc = getattr(ac, "escape_latex_underscores", None)
    return esc(out) if callable(esc) else out.replace("_", r"\_")


# ==========================================================================
# FIELD-LEVEL LOOKUPS
# ==========================================================================

def _field_frame(stratum: dict):
    fr = stratum.get("field_results")
    if fr is None or getattr(fr, "empty", True):
        return None
    return fr


def find_field_row(stratum: dict, *needles: str):
    """Locate a row in field_results. Exact json-path match first, then a
    case-insensitive match on the last path segment, then substring."""
    fr = _field_frame(stratum)
    if fr is None:
        return None
    fields = fr["field"].astype(str).tolist()
    for needle in needles:
        n = str(needle).strip().lower()
        if not n:
            continue
        for f in fields:                                  # exact
            if f.lower() == n:
                return fr.loc[fr["field"] == f].iloc[0]
        for f in fields:                                  # last segment
            if f.lower().rsplit(".", 1)[-1] == n.rsplit(".", 1)[-1]:
                return fr.loc[fr["field"] == f].iloc[0]
        for f in fields:                                  # substring
            if n in f.lower():
                return fr.loc[fr["field"] == f].iloc[0]
    return None


def most_contradictory_field(stratum: dict, label_map=None) -> dict | None:
    fr = _field_frame(stratum)
    if fr is None:
        return None
    idx = fr["contradiction_pct"].idxmax()
    row = fr.loc[idx]
    raw = str(row["field"])
    n = _i(stratum, "n_papers")
    cnt = int(row.get("contradiction", 0) or 0)
    return {
        "field_raw": raw,
        "field_label": _fmt_field(raw, label_map),
        "count": cnt,
        "n": n,
        "pct": float(row.get("contradiction_pct", pct_of(cnt, n))),
        "ci": wilson_ci(cnt, n),
    }


# ==========================================================================
# A) PURE BUILDERS -- SUMMARIES
# ==========================================================================

def _metric(count: int, n: int, pct: float | None = None) -> dict:
    return {
        "count": int(count),
        "n": int(n),
        "pct": float(pct) if pct is not None else pct_of(count, n),
    }


def summarize_domain(
    results: dict,
    *,
    label_map: dict[str, str] | None = None,
    categories: Sequence[tuple[str, Sequence[str]]] | None = None,
) -> dict:
    """Flatten one domain's `results` into every number the paper needs."""
    on = results.get("on_topic_only", {}) or {}
    off = results.get("off_topic_only", {}) or {}
    allp = results.get("all_papers", {}) or {}
    meta = results.get("_meta", {}) or {}

    n_on_obs = _i(on, "n_observations")
    n_off_obs = _i(off, "n_observations")
    n_all_obs = _i(allp, "n_observations")

    def m(stratum, n_obs, count_key, pct_key=None):
        c = _i(stratum, count_key)
        p = _f(stratum, pct_key) if pct_key else None
        return _metric(c, n_obs, p if p else None)

    s: dict[str, Any] = {
        "total_papers": int(meta.get("total_papers", _i(allp, "n_papers")) or 0),
        "n_fields": int(meta.get("n_fields", 0) or 0),
        "on_topic_papers": _i(on, "n_papers"),
        "off_topic_papers": _i(off, "n_papers"),
        "undetermined_papers": len(meta.get("undetermined_ids", []) or []),
        "on_topic_obs": n_on_obs,
        "off_topic_obs": n_off_obs,
        "all_obs": n_all_obs,
        "metrics": {
            "perfect":          m(on, n_on_obs, "overall_perfect", "overall_perfect_pct"),
            "uncertain":        m(on, n_on_obs, "overall_uncertain", "overall_uncertain_pct"),
            "biased_certain":   m(on, n_on_obs, "overall_uncertain_biased_certain",
                                  "overall_uncertain_biased_certain_pct"),
            "biased_uncertain": m(on, n_on_obs, "overall_uncertain_biased_uncertain",
                                  "overall_uncertain_biased_uncertain_pct"),
            "contradiction":    m(on, n_on_obs, "overall_contradiction",
                                  "overall_contradiction_pct"),
            "contra_biased_yes": m(on, n_on_obs, "overall_contradiction_biased_yes"),
            "contra_biased_no":  m(on, n_on_obs, "overall_contradiction_biased_no"),
            "contra_chaotic":    m(on, n_on_obs, "overall_contradiction_chaotic"),
        },
        "off_metrics": {
            "perfect":       m(off, n_off_obs, "overall_perfect", "overall_perfect_pct"),
            "contradiction": m(off, n_off_obs, "overall_contradiction",
                               "overall_contradiction_pct"),
        },
        "all_metrics": {
            "contradiction": m(allp, n_all_obs, "overall_contradiction",
                               "overall_contradiction_pct"),
            "perfect":       m(allp, n_all_obs, "overall_perfect", "overall_perfect_pct"),
        },
    }

    # "Uncertain (no Y+N)" is the parent of the two biased states. If the
    # core did not report it, reconstruct it so the table always balances.
    bc = s["metrics"]["biased_certain"]["count"]
    bu = s["metrics"]["biased_uncertain"]["count"]
    if s["metrics"]["uncertain"]["count"] == 0 and (bc or bu):
        s["metrics"]["uncertain"] = _metric(bc + bu, n_on_obs)

    # ---- most contradictory field -------------------------------------
    s["most_contra"] = most_contradictory_field(on, label_map)

    # ---- named fields used by the manuscript narrative ----------------
    n_on_papers = s["on_topic_papers"]

    def named(*needles):
        row = find_field_row(on, *needles)
        if row is None:
            return None
        raw = str(row["field"])
        cnt = int(row.get("contradiction", 0) or 0)
        unc = int(row.get("uncertain", 0) or 0)
        return {
            "field_raw": raw,
            "field_label": _fmt_field(raw, label_map),
            "n": n_on_papers,
            "contra_count": cnt,
            "contra_pct": float(row.get("contradiction_pct", pct_of(cnt, n_on_papers))),
            "contra_ci": wilson_ci(cnt, n_on_papers),
            "uncertain_count": unc,
            "uncertain_pct": float(row.get("uncertain_pct", pct_of(unc, n_on_papers))),
            "perfect_count": int(row.get("perfect", 0) or 0),
            "perfect_pct": float(row.get("perfect_pct", 0.0) or 0.0),
        }

    s["is_offtopic"] = named("is_offtopic", "offtopic")
    s["hybrid"] = named("technique.hybrid", "hybrid")
    s["comp_other"] = named("features.component_other", "component_other")

    # ---- "main classification minus is_offtopic" ----------------------
    s["main_other_contra_count"] = _main_other_contradictions(on, s, categories)

    # ---- contradiction decomposition ----------------------------------
    biased = s["metrics"]["contra_biased_yes"]["count"] + s["metrics"]["contra_biased_no"]["count"]
    chaotic = s["metrics"]["contra_chaotic"]["count"]
    total_c = s["metrics"]["contradiction"]["count"]
    s["biased_contra_count"] = biased
    s["biased_contra_share"] = pct_of(biased, total_c)
    s["chaotic_contra_count"] = chaotic
    s["chaotic_contra_share"] = pct_of(chaotic, total_c)

    # ---- global contradiction ceiling across every stratum ------------
    s["max_contra_pct"] = max(
        s["metrics"]["contradiction"]["pct"],
        s["off_metrics"]["contradiction"]["pct"],
        s["all_metrics"]["contradiction"]["pct"],
    )
    return s


def _main_other_contradictions(on: dict, s: dict, categories) -> int:
    """Contradictions in the 'Main classification' category excluding
    is_offtopic. Uses the configured categories when available, else falls
    back to 'top-level (dot-free) json paths'."""
    fr = _field_frame(on)
    if fr is None:
        return 0
    off_field = (s.get("is_offtopic") or {}).get("field_raw")
    main_fields: list[str] | None = None

    if categories:
        for _cat_name, cat_fields in categories:
            if off_field and off_field in set(cat_fields):
                main_fields = list(cat_fields)
                break

    if main_fields is None:                       # heuristic fallback
        main_fields = [f for f in fr["field"].astype(str) if "." not in f]

    sub = fr[fr["field"].astype(str).isin(main_fields)]
    if off_field:
        sub = sub[sub["field"].astype(str) != off_field]
    return int(sub["contradiction"].sum()) if "contradiction" in sub else 0


def summarize_cross_domain(
    results_s1: dict,
    results_s2: dict | None,
    *,
    label_map_s1=None, label_map_s2=None,
    categories_s1=None, categories_s2=None,
) -> dict:
    s1 = summarize_domain(results_s1, label_map=label_map_s1, categories=categories_s1)
    s2 = summarize_domain(results_s2, label_map=label_map_s2, categories=categories_s2) \
        if results_s2 else None

    out: dict[str, Any] = {"s1": s1, "s2": s2}
    if s2:
        out["agreement_delta"] = abs(s1["metrics"]["perfect"]["pct"] - s2["metrics"]["perfect"]["pct"])
        out["contradiction_ceiling"] = nice_ceiling(max(s1["max_contra_pct"], s2["max_contra_pct"]))
    else:
        out["agreement_delta"] = None
        out["contradiction_ceiling"] = nice_ceiling(s1["max_contra_pct"])
    out["uncertain_total"] = s1["metrics"]["uncertain"]["pct"]
    return out


# ==========================================================================
# A) PURE BUILDERS -- {tab:cross_domain}
# ==========================================================================

_ROW_SPEC: tuple[tuple[str, str], ...] = (
    ("Perfect (YYY/NNN/UUU)",        "perfect"),
    ("Uncertain (no Y+N)",           "uncertain"),
    ("Biased Certain (YYU/NNU)",     "biased_certain"),
    ("Biased Uncertain (YUU/NUU)",   "biased_uncertain"),
    ("Contradictions (Y+N present)", "contradiction"),
)

_CONTRA_SPEC: tuple[tuple[str, str], ...] = (
    (r"\quad Biased Yes (YYN)", "contra_biased_yes"),
    (r"\quad Biased No (YNN)",  "contra_biased_no"),
    (r"\quad Chaotic (YNU)",    "contra_chaotic"),
)


def _stat_cell(mt: dict) -> str:
    return rf"{mt['pct']:.2f}\% ({mt['count']:,})"


def _ci_cell(mt: dict) -> str:
    lo, hi = wilson_ci(mt["count"], mt["n"])
    return rf"\textit{{\footnotesize [{lo:.2f}\%, {hi:.2f}\%]}}"


def build_cross_domain_table(
    xdom: dict,
    *,
    col_s1: str = r"S1 -- PCB AOI (engineered)",
    col_s2: str = r"S2 -- SLR automation (rapid)",
    caption: str | None = None,
    label: str = "tab:cross_domain",
    contradiction_breakdown: bool = True,
) -> str:
    """LaTeX for {tab:cross_domain}. On-topic stratum only, by design:
    off-topic rows measure early-exit adherence, not taxonomic reasoning."""
    s1, s2 = xdom["s1"], xdom.get("s2")
    if s2 is None:
        raise ValueError("build_cross_domain_table requires both S1 and S2 summaries")

    caption = caption or (
        "Cross-domain comparison of on-topic agreement outcomes between the "
        "primary domain (S1, iteratively engineered prompts) and the secondary "
        "domain (S2, rapidly prototyped prompts). On-topic paper--field triplets "
        "only. Percentage shown first; count of classification decisions in "
        r"parentheses. Wilson 95\% Confidence Intervals in italics."
    )

    L: list[str] = []
    L.append(r"\begin{table*}[t]")
    L.append(r"\centering")
    L.append(rf"\caption{{{caption}}}")
    L.append(rf"\label{{{label}}}")
    L.append(r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lcc@{}}")
    L.append(r"\hline")
    L.append(rf"\textbf{{Metric}} & \textbf{{{col_s1}}} & \textbf{{{col_s2}}} \\")
    L.append(r"\hline")

    # ---- corpus header block (counts only, no CI) ---------------------
    L.append(rf"Corpus size (papers) & {s1['total_papers']:,} & {s2['total_papers']:,} \\")
    L.append(rf"Taxonomy fields & {s1['n_fields']} & {s2['n_fields']} \\")
    L.append(rf"On-topic papers & {s1['on_topic_papers']:,} & {s2['on_topic_papers']:,} \\")
    L.append(rf"\textbf{{Total on-topic decisions}} & "
             rf"{s1['on_topic_obs']:,} & {s2['on_topic_obs']:,} \\")
    L.append(r"\hline")

    # ---- agreement rows -----------------------------------------------
    for i, (name, key) in enumerate(_ROW_SPEC):
        a, b = s1["metrics"][key], s2["metrics"][key]
        L.append(rf"\textbf{{{name}}} & {_stat_cell(a)} & {_stat_cell(b)} \\")
        L.append(rf"\quad \textit{{\footnotesize 95\% CI}} & {_ci_cell(a)} & {_ci_cell(b)} \\")
        L.append(r"[6pt]" if i < len(_ROW_SPEC) - 1 else r"")

    if contradiction_breakdown:
        for name, key in _CONTRA_SPEC:
            a, b = s1["metrics"][key], s2["metrics"][key]
            L.append(rf"{name} & {_stat_cell(a)} & {_stat_cell(b)} \\")
            L.append(rf"\quad \textit{{\footnotesize 95\% CI}} & {_ci_cell(a)} & {_ci_cell(b)} \\")
            L.append(r"[4pt]")

    L.append(r"\hline")

    # ---- most contradictory field -------------------------------------
    mc1, mc2 = s1.get("most_contra"), s2.get("most_contra")
    lab1 = rf"\texttt{{{mc1['field_label']}}}" if mc1 else "--"
    lab2 = rf"\texttt{{{mc2['field_label']}}}" if mc2 else "--"
    L.append(rf"\textbf{{Most contradictory field}} & {lab1} & {lab2} \\")
    if mc1 and mc2:
        c1 = _metric(mc1["count"], mc1["n"], mc1["pct"])
        c2 = _metric(mc2["count"], mc2["n"], mc2["pct"])
        L.append(rf"\quad Contradiction rate & {_stat_cell(c1)} & {_stat_cell(c2)} \\")
        L.append(rf"\quad \textit{{\footnotesize 95\% CI}} & {_ci_cell(c1)} & {_ci_cell(c2)} \\")
    L.append(r"\hline")
    L.append(r"\end{tabular*}")
    L.append(r"\end{table*}")

    return "\n".join(x for x in L if x != "") + "\n"


# ==========================================================================
# A) PURE BUILDERS -- MACROS
# ==========================================================================

def _macro(name: str, value: str, arity: int = 0) -> str:
    if arity:
        value = value.replace("#", "##")
        return rf"\newcommand{{\{name}}}[{arity}]{{{value}#1}}"
    return rf"\newcommand{{\{name}}}{{{value}}}"


def _c(v) -> str:            # count
    return f"{int(round(float(v))):,}"


def _p(v) -> str:            # percent, 2dp
    return f"{float(v):.2f}"


def _n(v) -> str:            # generic number, trimmed
    return fmt_trim(float(v))


def build_cross_domain_macros(xdom: dict, *, emit_stat_aliases: bool = False) -> list[str]:
    """Every \\placeholder* the manuscript needs for the S1-narrative detail
    rows and for the whole of S2 / RQ4."""
    s1, s2 = xdom["s1"], xdom.get("s2")
    M1 = s1["metrics"]
    out: list[str] = []

    # ---------------- S1 (primary domain) ----------------
    out += [
        _macro("placeholderOnTopicPapers",           _c(s1["on_topic_papers"])),
        _macro("placeholderOnTopicObs",              _c(s1["on_topic_obs"])),
        _macro("placeholderOnTopicPerfectPct",       _p(M1["perfect"]["pct"])),
        _macro("placeholderOnTopicUncertainPct",     _p(M1["uncertain"]["pct"])),
        _macro("placeholderOnTopicBiasedCertainPct",   _p(M1["biased_certain"]["pct"])),
        _macro("placeholderOnTopicBiasedCertainCount", _c(M1["biased_certain"]["count"])),
        _macro("placeholderOnTopicBiasedUncertainPct",   _p(M1["biased_uncertain"]["pct"])),
        _macro("placeholderOnTopicBiasedUncertainCount", _c(M1["biased_uncertain"]["count"])),
        _macro("placeholderOnTopicContraPct",        _p(M1["contradiction"]["pct"])),
        _macro("placeholderUncertainTotal",          _p(xdom["uncertain_total"])),
        _macro("placeholderContradictionCeiling",    _n(xdom["contradiction_ceiling"])),
        # contradiction decomposition
        _macro("placeholderBiasedContraCount",  _c(s1["biased_contra_count"])),
        _macro("placeholderBiasedContraShare",  _p(s1["biased_contra_share"])),
        _macro("placeholderChaoticContraCount", _c(s1["chaotic_contra_count"])),
        _macro("placeholderChaoticContraShare", _p(s1["chaotic_contra_share"])),
        _macro("placeholderOffTopicContraCount", _c(s1["off_metrics"]["contradiction"]["count"])),
        _macro("placeholderOffTopicContraPct",   _p(s1["off_metrics"]["contradiction"]["pct"])),
        _macro("placeholderMainOtherContraCount", _c(s1["main_other_contra_count"])),
    ]

    # ---------------- S1 named fields ----------------
    if s1.get("is_offtopic"):
        f = s1["is_offtopic"]
        out += [
            _macro("placeholderIsOfftopicContraCount", _c(f["contra_count"])),
            _macro("placeholderIsOfftopicContraPct",   _p(f["contra_pct"])),
            _macro("placeholderIsOfftopicUncertainPct", _p(f["uncertain_pct"])),
        ]
    if s1.get("hybrid"):
        f = s1["hybrid"]
        out += [
            _macro("placeholderHybridContraCount", _c(f["contra_count"])),
            _macro("placeholderHybridContraPct",   _p(f["contra_pct"])),
            _macro("placeholderHybridUncertainPct", _p(f["uncertain_pct"])),
        ]
    if s1.get("comp_other"):
        f = s1["comp_other"]
        out += [
            _macro("placeholderCompOtherContraCount",   _c(f["contra_count"])),
            _macro("placeholderCompOtherContraPct",     _p(f["contra_pct"])),
            _macro("placeholderCompOtherUncertainPct",  _p(f["uncertain_pct"])),
            _macro("placeholderCompOtherUncertainCount", _c(f["uncertain_count"])),
        ]

    # ---------------- S2 (secondary domain) ----------------
    if s2:
        M2 = s2["metrics"]
        out += [
            _macro("placeholderDTwoPapers",        _c(s2["total_papers"])),
            _macro("placeholderDTwoFields",        _c(s2["n_fields"])),
            _macro("placeholderDTwoObs",           _c(s2["all_obs"])),
            _macro("placeholderDTwoOnTopicPapers", _c(s2["on_topic_papers"])),
            _macro("placeholderDTwoOnTopicObs",    _c(s2["on_topic_obs"])),
            _macro("placeholderDTwoPerfectPct",        _p(M2["perfect"]["pct"])),
            _macro("placeholderDTwoPerfectCount",      _c(M2["perfect"]["count"])),
            _macro("placeholderDTwoUncertainPct",      _p(M2["uncertain"]["pct"])),
            _macro("placeholderDTwoUncertainCount",    _c(M2["uncertain"]["count"])),
            _macro("placeholderDTwoBiasedCertainPct",   _p(M2["biased_certain"]["pct"])),
            _macro("placeholderDTwoBiasedCertainCount", _c(M2["biased_certain"]["count"])),
            _macro("placeholderDTwoBiasedUncertainPct",   _p(M2["biased_uncertain"]["pct"])),
            _macro("placeholderDTwoBiasedUncertainCount", _c(M2["biased_uncertain"]["count"])),
            _macro("placeholderDTwoContraPct",      _p(M2["contradiction"]["pct"])),
            _macro("placeholderDTwoContraCount",    _c(M2["contradiction"]["count"])),
            _macro("placeholderAgreementDelta",     _n(xdom["agreement_delta"])),
        ]
        if s2.get("is_offtopic"):
            out.append(_macro("placeholderDTwoIsOfftopicContraPct",
                              _p(s2["is_offtopic"]["contra_pct"])))
        if s2.get("most_contra"):
            mc = s2["most_contra"]
            out += [
                _macro("placeholderDTwoMostContraFieldRaw", mc["field_raw"]),
                _macro("placeholderDTwoMostContraField",    mc["field_label"]),
                _macro("placeholderDTwoMostContraPct",      _p(mc["pct"])),
                _macro("placeholderDTwoMostContraCount",    _c(mc["count"])),
            ]

    # ---------------- optional \Stat*DTwo aliases ----------------
    if emit_stat_aliases and s2:
        M2 = s2["metrics"]
        out += [
            _macro("StatDTwoTotalPapers",   _c(s2["total_papers"])),
            _macro("StatDTwoTotalFields",   _c(s2["n_fields"])),
            _macro("StatDTwoOnTopicPapers", _c(s2["on_topic_papers"])),
            _macro("StatDTwoOnTopicObs",    _c(s2["on_topic_obs"])),
            _macro("StatDTwoAllObs",        _c(s2["all_obs"])),
            _macro("StatDTwoOnTopicPerfectPct",   _p(M2["perfect"]["pct"])),
            _macro("StatDTwoOnTopicPerfectCount", _c(M2["perfect"]["count"])),
            _macro("StatDTwoOnTopicUncertainPct", _p(M2["uncertain"]["pct"])),
            _macro("StatDTwoOnTopicContraPct",    _p(M2["contradiction"]["pct"])),
            _macro("StatDTwoOnTopicContraCount",  _c(M2["contradiction"]["count"])),
        ]
    return out


def write_cross_domain_outputs(
    xdom: dict,
    table_path: str,
    macros_path: str,
    *,
    col_s1: str = r"S1 -- PCB AOI (engineered)",
    col_s2: str = r"S2 -- SLR automation (rapid)",
    emit_stat_aliases: bool = False,
    quiet: bool = False,
) -> None:
    with open(table_path, "w", encoding="utf-8") as f:
        f.write("% Cross-Domain Agreement Comparison (tab:cross_domain)\n")
        f.write("% Generated by cross_domain_core.py -- DO NOT EDIT MANUALLY\n")
        f.write("% Requires: booktabs / tabular*, Elsevier cas-sc two-column\n\n")
        f.write(build_cross_domain_table(xdom, col_s1=col_s1, col_s2=col_s2))

    with open(macros_path, "w", encoding="utf-8") as f:
        f.write("% AUTO-GENERATED CROSS-DOMAIN MACROS: DO NOT EDIT MANUALLY\n")
        f.write("% Generated by cross_domain_core.py\n")
        f.write("% Load AFTER agreement_*_macros.tex (no name collisions)\n")
        f.write("\n".join(build_cross_domain_macros(
            xdom, emit_stat_aliases=emit_stat_aliases)) + "\n")

    if not quiet:
        print(f" LaTeX table saved to: {table_path}")
        print(f" LaTeX macros saved to: {macros_path}")


# ==========================================================================
# B) LOADING SHIM  (two DB files -> two `results` dicts)
# ==========================================================================

LOADER_CANDIDATES: tuple[str, ...] = (
    "load_papers_and_fields", "load_papers_with_fields", "load_data",
    "load_corpus", "load_papers", "load_from_db", "load_database", "load",
)

CATEGORIES_CANDIDATES: tuple[str, ...] = (
    "build_categories", "get_categories", "categories_from_config",
    "load_categories", "resolve_categories",
)


def load_domain_config(config_path: str | None) -> dict:
    """Same semantics as agreement_3sets_cli.load_domain_config_file."""
    cfg: dict = {}
    if config_path:
        if yaml is None:
            print("Error: PyYAML is required for --config", file=sys.stderr)
        else:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                cfg = loaded if isinstance(loaded, dict) else {}
            except FileNotFoundError:
                print(f"Warning: domain config not found at '{config_path}'.", file=sys.stderr)
            except Exception as e:
                print(f"Error loading domain config: {e}", file=sys.stderr)
    cfg.setdefault("groups", [])
    cfg.setdefault("editable_fields", [])
    return cfg


def derive_boolean_fields(cfg: dict) -> list[str]:
    """Heuristic reconstruction of the tri-state field list from the YAML,
    used only when agreement_core does not expose its own loader."""
    out: list[str] = []

    def add(p):
        if p and p not in out:
            out.append(p)

    for g in cfg.get("groups", []) or []:
        parent = (g.get("json_path") or "").strip()
        ft = g.get("filter_type")
        if ft == "tri_state" and parent:
            add(parent)
        for fdef in g.get("fields", []) or []:
            if isinstance(fdef, str):
                add(fdef if not parent or fdef.startswith(parent) else f"{parent}.{fdef}")
                continue
            p = fdef.get("json_path") or fdef.get("path") or fdef.get("key")
            if not p:
                continue
            full = p if (not parent or p.startswith(parent + ".")) else f"{parent}.{p}"
            ftype = fdef.get("filter_type") or fdef.get("type")
            if ft == "tri_state" or ftype in ("tri_state", "bool", "boolean", None):
                add(full)
    for p in cfg.get("editable_fields", []) or []:
        if isinstance(p, str):
            add(p)
    return out


def derive_categories(cfg: dict, fields: Sequence[str]) -> list[tuple[str, list[str]]]:
    """[(category label, [json paths])]. Prefers agreement_core's own builder,
    then an explicit `categories:` block, then prefix inference."""
    for name in CATEGORIES_CANDIDATES:
        fn = getattr(ac, name, None)
        if callable(fn):
            try:
                res = fn(cfg) if len(inspect.signature(fn).parameters) == 1 else fn(cfg, list(fields))
                if res:
                    return [(str(a), list(b)) for a, b in res]
            except Exception:
                pass

    explicit = cfg.get("categories")
    if isinstance(explicit, list) and explicit:
        cats = []
        for c in explicit:
            if isinstance(c, dict):
                nm = c.get("name") or c.get("label") or c.get("friendly_name")
                fl = c.get("fields") or c.get("json_paths") or []
                if nm:
                    cats.append((str(nm), [str(x) for x in fl]))
        if cats:
            return cats

    label_map = build_label_map(cfg)
    buckets: dict[str, list[str]] = {}
    for f in fields:
        head = f.split(".", 1)[0] if "." in f else "__main__"
        buckets.setdefault(head, []).append(f)
    cats = []
    if "__main__" in buckets:
        cats.append(("Main classification", buckets.pop("__main__")))
    for head, fl in buckets.items():
        label = label_map.get(f"{head}.") or label_map.get(head) or head.capitalize()
        cats.append((str(label), fl))
    return cats


def build_label_map(cfg: dict) -> dict[str, str]:
    fn = getattr(ac, "build_field_label_map", None)
    if callable(fn):
        try:
            return dict(fn(cfg) or {})
        except Exception:
            pass
    labels: dict[str, str] = {"is_offtopic": "Off-topic"}
    for g in cfg.get("groups", []) or []:
        parent = g.get("json_path") or ""
        nm = g.get("friendly_name") or g.get("label") or g.get("category")
        if parent and nm:
            labels[parent] = nm
            labels[parent + "."] = nm
    return labels


def resolve_loader(dotted: str | None = None) -> Callable:
    """Return the callable that turns (db, cfg) into (papers, boolean_fields)."""
    if dotted:
        mod_name, _, fn_name = dotted.rpartition(".")
        if not mod_name:
            fn = getattr(ac, fn_name, None)
        else:
            import importlib
            fn = getattr(importlib.import_module(mod_name), fn_name, None)
        if not callable(fn):
            raise AttributeError(f"Loader '{dotted}' could not be resolved")
        return fn

    for name in LOADER_CANDIDATES:
        fn = getattr(ac, name, None)
        if callable(fn):
            return fn
    raise AttributeError(
        "Could not auto-detect a corpus loader in agreement_core. "
        f"Looked for: {', '.join(LOADER_CANDIDATES)}. "
        "Pass --loader my.module.func explicitly."
    )


def _adaptive_call(fn: Callable, *, db, cfg, fields, categories) -> Any:
    """Bind only the parameters `fn` actually declares."""
    pool = {
        "db": db, "db_path": db, "database": db, "database_path": db, "path": db,
        "config": cfg, "cfg": cfg, "domain_config": cfg, "domain_cfg": cfg,
        "fields": fields, "boolean_fields": fields,
        "categories": categories,
        "verbose": False, "quiet": True,
    }
    sig = inspect.signature(fn)
    kwargs, positional = {}, []
    for pname, p in sig.parameters.items():
        if p.kind is p.VAR_POSITIONAL:
            positional = [db, cfg]
        elif p.kind is p.VAR_KEYWORD:
            continue
        elif pname in pool:
            kwargs[pname] = pool[pname]
        elif p.default is p.empty:
            positional.append(pool.get(pname, db))
    return fn(*positional, **kwargs)


def run_domain_analysis(
    db_path: str,
    config_path: str | None = None,
    *,
    loader: str | None = None,
    quiet: bool = False,
) -> tuple[dict, dict]:
    """db + yaml  ->  (results, info). `info` carries cfg/fields/categories/
    label_map so downstream code does not have to re-derive them."""
    cfg = load_domain_config(config_path)
    fn = resolve_loader(loader)

    fields_guess = derive_boolean_fields(cfg)
    cats_guess = derive_categories(cfg, fields_guess)

    loaded = _adaptive_call(fn, db=db_path, cfg=cfg,
                            fields=fields_guess, categories=cats_guess)

    papers, fields = None, None
    if isinstance(loaded, tuple):
        if len(loaded) >= 2:
            papers, fields = loaded[0], loaded[1]
        else:
            papers = loaded[0]
    else:
        papers = loaded

    if not fields:
        getter = getattr(ac, "get_boolean_fields", None)
        fields = getter(cfg) if callable(getter) else fields_guess
    if not fields:
        fields = derive_boolean_fields(cfg)

    categories = derive_categories(cfg, fields)
    label_map = build_label_map(cfg)

    if not quiet:
        print(f"Loaded {len(papers)} papers with 3-run data from {db_path}")

    results = ac.run_analysis(papers, fields, db_path, verbose=not quiet)
    info = {"cfg": cfg, "fields": list(fields),
            "categories": categories, "label_map": label_map,
            "db_path": db_path}
    return results, info