"""
Cross-Domain Agreement Comparison CLI
Compares S1 (Engineered) and S2 (Rapid) datasets and generates the 
tab:cross_domain LaTeX table along with all missing placeholder macros.
"""
import argparse
import os
import sys
from pathlib import Path
import yaml

# Repo root (this script lives in meta/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from meta import agreement_core

def load_domain_config_file(config_path: str) -> dict:
    """Load domain configuration from a YAML file (CLI-side resolution)."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
            if not cfg or not isinstance(cfg, dict):
                cfg = {}
    except FileNotFoundError:
        print(f"Warning: Domain config not found at '{config_path}'.", file=sys.stderr)
        cfg = {}
    except Exception as e:
        print(f"Error loading domain config: {e}", file=sys.stderr)
        cfg = {}
    cfg.setdefault('groups', [])
    cfg.setdefault('editable_fields', [])
    return cfg

def get_field_stats(results, field_name):
    """Extract stats for a specific field from the on_topic_only stratum."""
    on_topic = results.get('on_topic_only', {})
    field_results = on_topic.get('field_results')
    if field_results is None or field_results.empty:
        return None
    row = field_results[field_results['field'] == field_name]
    if row.empty:
        return None
    return row.iloc[0].to_dict()

import numpy as np
from scipy import stats

def wilson_score_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Identical math to agreement_core.py"""
    if n == 0:
        return 0.0, 100.0
    z = stats.norm.ppf((1 + confidence) / 2)
    p_hat = successes / n
    denominator = 1 + z**2 / n
    centre = (p_hat + z**2 / (2 * n)) / denominator
    margin = (
        z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator
    )
    lower = max(0.0, (centre - margin) * 100)
    upper = min(100.0, (centre + margin) * 100)
    return lower, upper

def build_cross_domain_table(s1_res, s2_res):
    """Builds the side-by-side LaTeX table for S1 vs S2 with Wilson CIs."""
    s1_ot, s2_ot = s1_res['on_topic_only'], s2_res['on_topic_only']
    n1, n2 = s1_ot['n_observations'], s2_ot['n_observations']

    # --- Most contradictory field (per-field stats, n = n_papers) ---
    def get_most_contra(res):
        fr = res.get('field_results')
        if fr is None or fr.empty:
            return None
        idx = fr['contradiction_pct'].idxmax()
        return fr.loc[idx]

    s1_mc = get_most_contra(s1_ot)
    s2_mc = get_most_contra(s2_ot)

    # Uncertain = Biased Certain + Biased Uncertain (sum counts to avoid rounding drift)
    s1_unc_cnt = s1_ot.get('overall_uncertain_biased_certain', 0) + s1_ot.get('overall_uncertain_biased_uncertain', 0)
    s2_unc_cnt = s2_ot.get('overall_uncertain_biased_certain', 0) + s2_ot.get('overall_uncertain_biased_uncertain', 0)
    s1_unc_pct = (s1_unc_cnt / n1 * 100) if n1 > 0 else 0.0
    s2_unc_pct = (s2_unc_cnt / n2 * 100) if n2 > 0 else 0.0

    def row_with_ci(label, c1, p1, c2, p2):
        l1, u1 = wilson_score_interval(c1, n1)
        l2, u2 = wilson_score_interval(c2, n2)
        return [
            f"\\textbf{{{label}}} & {p1:.2f}\\% ({c1:,}) & {p2:.2f}\\% ({c2:,}) \\\\",
            f"\\quad \\textit{{\\footnotesize 95\\% CI}} & "
            f"\\textit{{\\footnotesize [{l1:.2f}\\%, {u1:.2f}\\%]}} & "
            f"\\textit{{\\footnotesize [{l2:.2f}\\%, {u2:.2f}\\%]}} \\\\[6pt]"
        ]

    lines = [
        r"\begin{table*}[t]", r"\centering",
        r"\caption{Cross-domain comparison of on-topic agreement outcomes between S1 "
        r"(carefully engineered prompts) and S2 (rapidly prototyped prompts). "
        r"Percentage shown first; count of classification decisions in parentheses. "
        r"Wilson 95\% Confidence Intervals in italics.}",
        r"\label{tab:cross_domain}",
        r"\begin{tabular*}{\textwidth}{@{\extracolsep{\fill}}lcc@{}}", r"\hline",
        r"\textbf{Metric} & \textbf{S1 (Engineered)} & \textbf{S2 (Rapid)} \\", r"\hline",
        f"\\textbf{{Total decisions}} & {n1:,} & {n2:,} \\\\[6pt]"
    ]

    lines.extend(row_with_ci("Perfect",
                             s1_ot['overall_perfect'], s1_ot['overall_perfect_pct'],
                             s2_ot['overall_perfect'], s2_ot['overall_perfect_pct']))
    lines.extend(row_with_ci("Uncertain",
                             s1_unc_cnt, s1_unc_pct,
                             s2_unc_cnt, s2_unc_pct))
    lines.extend(row_with_ci("Biased Certain",
                             s1_ot.get('overall_uncertain_biased_certain', 0),
                             s1_ot.get('overall_uncertain_biased_certain_pct', 0.0),
                             s2_ot.get('overall_uncertain_biased_certain', 0),
                             s2_ot.get('overall_uncertain_biased_certain_pct', 0.0)))
    lines.extend(row_with_ci("Biased Uncertain",
                             s1_ot.get('overall_uncertain_biased_uncertain', 0),
                             s1_ot.get('overall_uncertain_biased_uncertain_pct', 0.0),
                             s2_ot.get('overall_uncertain_biased_uncertain', 0),
                             s2_ot.get('overall_uncertain_biased_uncertain_pct', 0.0)))
    lines.extend(row_with_ci("Contradictions",
                             s1_ot['overall_contradiction'], s1_ot['overall_contradiction_pct'],
                             s2_ot['overall_contradiction'], s2_ot['overall_contradiction_pct']))

    # --- Most contradictory field with its own CI (n = n_papers, not n_observations) ---
    if s1_mc is not None and s2_mc is not None:
        s1_field_fmt = agreement_core.escape_latex_underscores(
            agreement_core.format_field_name(s1_mc['field']))
        s2_field_fmt = agreement_core.escape_latex_underscores(
            agreement_core.format_field_name(s2_mc['field']))

        lines.append(
            f"\\textbf{{Most contradictory field}} & "
            f"\\texttt{{{s1_field_fmt}}} & "
            f"\\texttt{{{s2_field_fmt}}} \\\\")
        lines.append(
            f"\\quad \\textit{{\\footnotesize Field contradiction rate}} & "
            f"\\textit{{\\footnotesize {float(s1_mc['contradiction_pct']):.2f}\\% "
            f"({int(s1_mc['contradiction']):,} papers)}} & "
            f"\\textit{{\\footnotesize {float(s2_mc['contradiction_pct']):.2f}\\% "
            f"({int(s2_mc['contradiction']):,} papers)}} \\\\")
        lines.append(
            f"\\quad \\textit{{\\footnotesize 95\\% CI}} & "
            f"\\textit{{\\footnotesize [{float(s1_mc['contradiction_ci_lower']):.2f}\\%, "
            f"{float(s1_mc['contradiction_ci_upper']):.2f}\\%]}} & "
            f"\\textit{{\\footnotesize [{float(s2_mc['contradiction_ci_lower']):.2f}\\%, "
            f"{float(s2_mc['contradiction_ci_upper']):.2f}\\%]}} \\\\")

    lines.extend([r"\hline", r"\end{tabular*}", r"\end{table*}"])
    return "\n".join(lines)

def generate_missing_macros(s1_res, s2_res, s1_fields, s2_fields, output_path):
    """
    Generates all S1/S2 placeholder macros used by the manuscript.

    Important:
    - This function no longer emits S4/hardware placeholders.
      Those are generated by time_power_charts.py and the GPU comparison script.
    - Definitions are written as provide/renew so they can safely override
      stale placeholder definitions in the LaTeX preamble.
    """
    try:
        from meta import cross_domain_core as xdc
    except ImportError:
        import cross_domain_core as xdc

    def safe_macro(name: str, value: str) -> str:
        return (
            f"\\providecommand{{\\{name}}}{{}}\n"
            f"\\renewcommand{{\\{name}}}{{{value}}}"
        )

    def fmt_int(v) -> str:
        try:
            return f"{int(round(float(v))):,}"
        except Exception:
            return "0"

    def fmt_pct(v) -> str:
        try:
            return f"{float(v):.2f}"
        except Exception:
            return "0.00"

    def fmt_share(v) -> str:
        try:
            return f"{float(v):.1f}"
        except Exception:
            return "0.0"

    def fmt_trim(v) -> str:
        try:
            s = f"{float(v):.2f}".rstrip("0").rstrip(".")
            return s if s else "0"
        except Exception:
            return "0"

    def structural_categories(fields):
        main_fields = []
        features_fields = []
        techniques_fields = []

        for f in fields:
            if f.startswith("features."):
                features_fields.append(f)
            elif f.startswith("technique."):
                techniques_fields.append(f)
            else:
                main_fields.append(f)

        cats = []
        if main_fields:
            cats.append(("Main classification", main_fields))
        if features_fields:
            cats.append(("Features", features_fields))
        if techniques_fields:
            cats.append(("Techniques", techniques_fields))
        return cats

    xdom = xdc.summarize_cross_domain(
        s1_res,
        s2_res,
        categories_s1=structural_categories(s1_fields),
        categories_s2=structural_categories(s2_fields),
    )

    s1 = xdom.get("s1") or {}
    s2 = xdom.get("s2") or {}

    m1 = s1.get("metrics") or {}
    m2 = s2.get("metrics") or {}

    def get_metric(metrics, key):
        return metrics.get(key) or {"count": 0, "pct": 0.0, "n": 0}

    # -----------------------------
    # S1 metrics
    # -----------------------------
    perfect1 = get_metric(m1, "perfect")
    uncertain1 = get_metric(m1, "uncertain")
    biased_certain1 = get_metric(m1, "biased_certain")
    biased_uncertain1 = get_metric(m1, "biased_uncertain")
    contra1 = get_metric(m1, "contradiction")

    off_metrics1 = s1.get("off_metrics") or {}
    off_contra1 = off_metrics1.get("contradiction") or {"count": 0, "pct": 0.0}

    is_offtopic1 = s1.get("is_offtopic") or {}
    hybrid1 = s1.get("hybrid") or {}
    comp_other1 = s1.get("comp_other") or {}

    # -----------------------------
    # S2 metrics
    # -----------------------------
    perfect2 = get_metric(m2, "perfect")
    uncertain2 = get_metric(m2, "uncertain")
    biased_certain2 = get_metric(m2, "biased_certain")
    biased_uncertain2 = get_metric(m2, "biased_uncertain")
    contra2 = get_metric(m2, "contradiction")

    is_offtopic2 = s2.get("is_offtopic") or {}
    most_contra2 = s2.get("most_contra") or {}

    # -----------------------------
    # Global derived values
    # -----------------------------
    contradiction_ceiling = xdom.get("contradiction_ceiling")
    if contradiction_ceiling is None:
        contradiction_ceiling = 0.0

    uncertain_total = xdom.get("uncertain_total")
    if uncertain_total is None:
        uncertain_total = uncertain1["pct"]

    agreement_delta = xdom.get("agreement_delta")
    if agreement_delta is None:
        agreement_delta = abs(float(perfect1["pct"]) - float(perfect2["pct"]))

    lines = [
        "% AUTO-GENERATED CROSS-DOMAIN MACROS: DO NOT EDIT MANUALLY",
        "% Generated by agreement_cross_domain_cli.py",
        "",
    ]

    # ==================================================================
    # S1 / primary-domain placeholders
    # ==================================================================
    lines += [
        safe_macro("placeholderOnTopicPapers", fmt_int(s1.get("on_topic_papers", 0))),
        safe_macro("placeholderOnTopicObs", fmt_int(s1.get("on_topic_obs", 0))),
        safe_macro("placeholderOnTopicPerfectPct", fmt_pct(perfect1["pct"])),
        safe_macro("placeholderOnTopicUncertainPct", fmt_pct(uncertain1["pct"])),
        safe_macro("placeholderOnTopicUncertainCount", fmt_int(uncertain1["count"])),
        safe_macro("placeholderOnTopicBiasedCertainPct", fmt_pct(biased_certain1["pct"])),
        safe_macro("placeholderOnTopicBiasedCertainCount", fmt_int(biased_certain1["count"])),
        safe_macro("placeholderOnTopicBiasedUncertainPct", fmt_pct(biased_uncertain1["pct"])),
        safe_macro("placeholderOnTopicBiasedUncertainCount", fmt_int(biased_uncertain1["count"])),
        safe_macro("placeholderOnTopicContraPct", fmt_pct(contra1["pct"])),
        safe_macro("placeholderOnTopicContraCount", fmt_int(contra1["count"])),
        "",
        safe_macro("placeholderIsOfftopicContraCount", fmt_int(is_offtopic1.get("contra_count", 0))),
        safe_macro("placeholderIsOfftopicContraPct", fmt_pct(is_offtopic1.get("contra_pct", 0.0))),
        safe_macro("placeholderMainOtherContraCount", fmt_int(s1.get("main_other_contra_count", 0))),
        safe_macro("placeholderHybridContraCount", fmt_int(hybrid1.get("contra_count", 0))),
        safe_macro("placeholderHybridContraPct", fmt_pct(hybrid1.get("contra_pct", 0.0))),
        safe_macro("placeholderCompOtherContraCount", fmt_int(comp_other1.get("contra_count", 0))),
        safe_macro("placeholderCompOtherContraPct", fmt_pct(comp_other1.get("contra_pct", 0.0))),
        safe_macro("placeholderCompOtherUncertainPct", fmt_pct(comp_other1.get("uncertain_pct", 0.0))),
        "",
        safe_macro("placeholderBiasedContraCount", fmt_int(s1.get("biased_contra_count", 0))),
        safe_macro("placeholderBiasedContraShare", fmt_share(s1.get("biased_contra_share", 0.0))),
        safe_macro("placeholderChaoticContraCount", fmt_int(s1.get("chaotic_contra_count", 0))),
        safe_macro("placeholderChaoticContraShare", fmt_share(s1.get("chaotic_contra_share", 0.0))),
        safe_macro("placeholderOffTopicContraCount", fmt_int(off_contra1.get("count", 0))),
        safe_macro("placeholderOffTopicContraPct", fmt_pct(off_contra1.get("pct", 0.0))),
        "",
        safe_macro("placeholderContradictionCeiling", fmt_trim(contradiction_ceiling)),
        safe_macro("placeholderUncertainTotal", fmt_pct(uncertain_total)),
        safe_macro("placeholderAgreementDelta", fmt_pct(agreement_delta)),
        "",
    ]

    # ==================================================================
    # S2 / secondary-domain placeholders
    # ==================================================================
    lines += [
        safe_macro("placeholderDTwoPapers", fmt_int(s2.get("total_papers", 0))),
        safe_macro("placeholderDTwoFields", fmt_int(s2.get("n_fields") or len(s2_fields))),
        safe_macro("placeholderDTwoObs", fmt_int(s2.get("all_obs", 0))),
        safe_macro("placeholderDTwoOnTopicPapers", fmt_int(s2.get("on_topic_papers", 0))),
        safe_macro("placeholderDTwoOnTopicObs", fmt_int(s2.get("on_topic_obs", 0))),
        "",
        safe_macro("placeholderDTwoPerfectPct", fmt_pct(perfect2["pct"])),
        safe_macro("placeholderDTwoPerfectCount", fmt_int(perfect2["count"])),
        safe_macro("placeholderDTwoUncertainPct", fmt_pct(uncertain2["pct"])),
        safe_macro("placeholderDTwoUncertainCount", fmt_int(uncertain2["count"])),
        safe_macro("placeholderDTwoBiasedCertainPct", fmt_pct(biased_certain2["pct"])),
        safe_macro("placeholderDTwoBiasedCertainCount", fmt_int(biased_certain2["count"])),
        safe_macro("placeholderDTwoBiasedUncertainPct", fmt_pct(biased_uncertain2["pct"])),
        safe_macro("placeholderDTwoBiasedUncertainCount", fmt_int(biased_uncertain2["count"])),
        safe_macro("placeholderDTwoContraPct", fmt_pct(contra2["pct"])),
        safe_macro("placeholderDTwoContraCount", fmt_int(contra2["count"])),
        "",
        safe_macro("placeholderDTwoIsOfftopicContraCount", fmt_int(is_offtopic2.get("contra_count", 0))),
        safe_macro("placeholderDTwoIsOfftopicContraPct", fmt_pct(is_offtopic2.get("contra_pct", 0.0))),
        "",
    ]

    # Optional but useful for later table/text fixes
    if most_contra2:
        raw = str(most_contra2.get("field_raw", "none"))
        raw_tex = raw.replace("_", "\\_")
        label = str(most_contra2.get("field_label", raw)).replace("_", "\\_")

        lines += [
            safe_macro("placeholderDTwoMostContraFieldRaw", raw_tex),
            safe_macro("placeholderDTwoMostContraField", label),
            safe_macro("placeholderDTwoMostContraPct", fmt_pct(most_contra2.get("pct", 0.0))),
            safe_macro("placeholderDTwoMostContraCount", fmt_int(most_contra2.get("count", 0))),
        ]
    else:
        lines += [
            safe_macro("placeholderDTwoMostContraFieldRaw", "none"),
            safe_macro("placeholderDTwoMostContraField", "None"),
            safe_macro("placeholderDTwoMostContraPct", "0.00"),
            safe_macro("placeholderDTwoMostContraCount", "0"),
        ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  Missing macros saved to: {output_path}")
    
def resolve_config(db_path, config_arg):
    if config_arg and Path(config_arg).exists(): return config_arg
    db_dir = Path(db_path).resolve().parent
    for c in [db_dir / 'domain_config.yaml', Path.cwd() / 'domain_config.yaml', Path(__file__).resolve().parent / 'domain_config.yaml']:
        if c.exists(): return str(c)
    return str(db_dir / 'domain_config.yaml')

def main():
    parser = argparse.ArgumentParser(description='Cross-domain agreement comparison.')
    parser.add_argument('--db1', required=True)
    parser.add_argument('--config1', default=None)
    parser.add_argument('--db2', required=True)
    parser.add_argument('--config2', default=None)
    parser.add_argument('-o', '--output', default='cross_domain_results')
    parser.add_argument('-q', '--quiet', action='store_true')
    args = parser.parse_args()

    cfg1, cfg2 = load_domain_config_file(resolve_config(args.db1, args.config1)), load_domain_config_file(resolve_config(args.db2, args.config2))
    fields1, fields2 = agreement_core.discover_boolean_fields(cfg1), agreement_core.discover_boolean_fields(cfg2)
    
    if not args.quiet: print(f"S1 Fields: {len(fields1)} | S2 Fields: {len(fields2)}")

    papers1 = agreement_core.load_all_papers_from_single_db(args.db1, fields1)
    res1 = agreement_core.run_analysis(papers1, fields1, args.db1, verbose=not args.quiet, log_analysis_strata=['all_papers'])
    
    papers2 = agreement_core.load_all_papers_from_single_db(args.db2, fields2)
    res2 = agreement_core.run_analysis(papers2, fields2, args.db2, verbose=not args.quiet, log_analysis_strata=['all_papers'])
    
    with open(f"{args.output}_table.tex", 'w', encoding='utf-8') as f:
        f.write("% Cross-Domain Comparison Table\n" + build_cross_domain_table(res1, res2) + "\n")
        
    generate_missing_macros(res1, res2, fields1, fields2, f"{args.output}_macros.tex")

if __name__ == '__main__':
    main()