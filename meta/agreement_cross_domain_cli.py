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
    """Generates all missing S1, S2, and S4 placeholder macros dynamically."""
    meta1, meta2 = s1_res.get('_meta', {}), s2_res.get('_meta', {})
    s1_ot, s1_off = s1_res['on_topic_only'], s1_res['off_topic_only']
    s2_ot, s2_off = s2_res['on_topic_only'], s2_res['off_topic_only']
    
    # Calculate Total Papers safely
    s1_total_papers = len(meta1.get('on_topic_ids', [])) + len(meta1.get('off_topic_ids', [])) + len(meta1.get('undetermined_ids', []))
    s2_total_papers = len(meta2.get('on_topic_ids', [])) + len(meta2.get('off_topic_ids', [])) + len(meta2.get('undetermined_ids', []))
    
    # S1 specific field stats
    is_offtopic_s1 = get_field_stats(s1_res, 'is_offtopic') or {}
    hybrid_s1 = get_field_stats(s1_res, 'technique.hybrid') or {}
    comp_other_s1 = get_field_stats(s1_res, 'features.component_other') or {}
    
    # S2 specific field stats
    is_offtopic_s2 = get_field_stats(s2_res, 'is_offtopic') or {}
    
    # S1 Main category math
    main_cat_fields = [f for f in s1_fields if not f.startswith('features.') and not f.startswith('technique.')]
    fr = s1_ot.get('field_results')
    main_contra_count = int(fr[fr['field'].isin(main_cat_fields)]['contradiction'].sum()) if fr is not None and not fr.empty else 0
    main_other_contra = main_contra_count - int(is_offtopic_s1.get('contradiction', 0))
    
    # S1 Contradiction Shares
    biased_yes = s1_ot.get('overall_contradiction_biased_yes', 0)
    biased_no = s1_ot.get('overall_contradiction_biased_no', 0)
    chaotic = s1_ot.get('overall_contradiction_chaotic', 0)
    total_contra = s1_ot.get('overall_contradiction', 0)
    
    biased_share = ((biased_yes + biased_no) / total_contra * 100) if total_contra > 0 else 0.0
    chaotic_share = (chaotic / total_contra * 100) if total_contra > 0 else 0.0
    
    # Cross-domain deltas
    max_contra = max(s1_ot.get('overall_contradiction_pct', 0.0), s2_ot.get('overall_contradiction_pct', 0.0))
    contradiction_ceiling = max(0.6, round(max_contra + 0.05, 1))
    agreement_delta = abs(s1_ot.get('overall_perfect_pct', 0.0) - s2_ot.get('overall_perfect_pct', 0.0))

    lines = [
        "% AUTO-GENERATED MISSING MACROS",
        f"\\newcommand{{\\placeholderOnTopicPapers}}{{{len(meta1.get('on_topic_ids', [])):,}}}",
        f"\\newcommand{{\\placeholderOnTopicBiasedCertainPct}}{{{s1_ot.get('overall_uncertain_biased_certain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderOnTopicBiasedUncertainPct}}{{{s1_ot.get('overall_uncertain_biased_uncertain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderIsOfftopicContraCount}}{{{int(is_offtopic_s1.get('contradiction', 0)):,}}}",
        f"\\newcommand{{\\placeholderIsOfftopicContraPct}}{{{float(is_offtopic_s1.get('contradiction_pct', 0.0)):.2f}}}",
        f"\\newcommand{{\\placeholderMainOtherContraCount}}{{{main_other_contra:,}}}",
        f"\\newcommand{{\\placeholderHybridContraPct}}{{{float(hybrid_s1.get('contradiction_pct', 0.0)):.2f}}}",
        f"\\newcommand{{\\placeholderHybridContraCount}}{{{int(hybrid_s1.get('contradiction', 0)):,}}}",
        f"\\newcommand{{\\placeholderCompOtherContraPct}}{{{float(comp_other_s1.get('contradiction_pct', 0.0)):.2f}}}",
        f"\\newcommand{{\\placeholderCompOtherContraCount}}{{{int(comp_other_s1.get('contradiction', 0)):,}}}",
        f"\\newcommand{{\\placeholderCompOtherUncertainPct}}{{{float(comp_other_s1.get('uncertain_pct', 0.0)):.2f}}}",
        f"\\newcommand{{\\placeholderBiasedContraCount}}{{{biased_yes + biased_no:,}}}",
        f"\\newcommand{{\\placeholderBiasedContraShare}}{{{biased_share:.1f}}}",
        f"\\newcommand{{\\placeholderChaoticContraCount}}{{{chaotic:,}}}",
        f"\\newcommand{{\\placeholderChaoticContraShare}}{{{chaotic_share:.1f}}}",
        f"\\newcommand{{\\placeholderOffTopicContraCount}}{{{s1_off.get('overall_contradiction', 0):,}}}",
        f"\\newcommand{{\\placeholderOffTopicContraPct}}{{{s1_off.get('overall_contradiction_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderContradictionCeiling}}{{{contradiction_ceiling}}}",
        f"\\newcommand{{\\placeholderUncertainTotal}}{{{s1_ot.get('overall_uncertain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderAgreementDelta}}{{{agreement_delta:.2f}}}",
        "", "% Domain Two (S2) Macros",
        f"\\newcommand{{\\placeholderDTwoPapers}}{{{s2_total_papers:,}}}",
        f"\\newcommand{{\\placeholderDTwoFields}}{{{len(s2_fields)}}}",
        f"\\newcommand{{\\placeholderDTwoObs}}{{{s2_ot.get('n_observations', 0) + s2_off.get('n_observations', 0):,}}}",
        f"\\newcommand{{\\placeholderDTwoPerfectPct}}{{{s2_ot.get('overall_perfect_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderDTwoBiasedCertainPct}}{{{s2_ot.get('overall_uncertain_biased_certain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderDTwoBiasedUncertainPct}}{{{s2_ot.get('overall_uncertain_biased_uncertain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderDTwoUncertainPct}}{{{s2_ot.get('overall_uncertain_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderDTwoContraPct}}{{{s2_ot.get('overall_contradiction_pct', 0.0):.2f}}}",
        f"\\newcommand{{\\placeholderDTwoIsOfftopicContraPct}}{{{float(is_offtopic_s2.get('contradiction_pct', 0.0)):.2f}}}"
    ]
    
    # Dummy S4 macros
    s4_macros = ["placeholderS4Size", "placeholderS4OnTopic", "placeholderAvgPower", "placeholderInitialClassMinutes", 
                 "placeholderTotalMinutes", "placeholderSpeedupX", "placeholderEfficiencyX", "placeholderBatchSizeRatio",
                 "placeholderAltModelSpeedup", "placeholderAltModelPerfect", "placeholderAltModelHumanMatch", 
                 "placeholderScreeningTime", "placeholderClassifyThroughput", "placeholderSpeedX"]
    lines.append("\n% S4 / Hardware placeholders (dummy values)")
    for m in s4_macros: lines.append(f"\\providecommand{{\\{m}}}{{[TBD]}}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
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