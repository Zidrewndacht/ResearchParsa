"""
GPU Comparison: 1 GPU vs 2 GPUs
Outputs:
1. A combined plot (shared relative time axis, both starting at t=0) 
2. A LaTeX table with performance metrics split by phase and ratios.
"""

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_power_log(csv_path):
    """Parse power CSV, return list of {timestamp, psu_power_in}."""
    if not csv_path.exists(): return []
    power_data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        try:
            col_ts = next(i for i, h in enumerate(header) if 'date/time' in h.lower())
            col_power = next(i for i, h in enumerate(header) if 'psu power in' in h.lower() and '[w]' in h.lower())
        except StopIteration:
            return []
            
        for row in reader:
            if len(row) <= max(col_ts, col_power): continue
            try:
                ts = datetime.fromisoformat(row[col_ts].strip().replace('Z', '+00:00'))
                power = float(row[col_power].strip().replace(',', '.'))
                power_data.append({'timestamp': ts, 'power': power})
            except (ValueError, IndexError):
                continue
    return power_data

def smooth_series(values, window):
    """Centered rolling average with edge handling."""
    if len(values) < window: return values
    half = window // 2
    return [
        sum(values[max(0,i-half):min(len(values),i+half+1)]) / 
        len(values[max(0,i-half):min(len(values),i+half+1)])
        for i in range(len(values))
    ]

def get_paper_timestamps(db_path):
    """Get list of completion timestamps for papers based on their llm_log."""
    if not db_path.exists(): return []
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != '[]' AND llm_log != ''")
    
    timestamps = []
    for (log_str,) in cursor.fetchall():
        try:
            logs = json.loads(log_str)
            latest_ts = None
            for entry in logs:
                if entry.get('type') == 'averaged_llm':
                    ts_str = entry.get('timestamp')
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.strip().replace('Z', '+00:00'))
                        if latest_ts is None or ts > latest_ts:
                            latest_ts = ts
            if latest_ts: timestamps.append(latest_ts)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
    conn.close()
    timestamps.sort()
    return timestamps

# ============================================================================
# METRICS & DATA PREP
# ============================================================================

def integrate_power(power_data, t_start, t_end):
    """Integrate power over a specific time window to get Energy (kWh) and Avg Power (W)."""
    energy_wh = 0.0
    if not power_data or t_end <= t_start:
        return 0.0, 0.0
    
    for i in range(len(power_data) - 1):
        t1, t2 = power_data[i]['timestamp'], power_data[i+1]['timestamp']
        p = power_data[i]['power']
        
        # Clip the interval to [t_start, t_end]
        clip_start = max(t1, t_start)
        clip_end = min(t2, t_end)
        
        if clip_end > clip_start:
            delta_hrs = (clip_end - clip_start).total_seconds() / 3600.0
            energy_wh += p * delta_hrs
            
    total_time_hrs = (t_end - t_start).total_seconds() / 3600.0
    avg_power = (energy_wh / total_time_hrs) if total_time_hrs > 0 else 0.0
    
    return energy_wh / 1000.0, avg_power

def prepare_plot_data(power_data, paper_timestamps):
    """Prepare aligned lists for step-plots and line-plots."""
    if not paper_timestamps:
        return [], [], [], []
        
    t0_candidates = [paper_timestamps[0]]
    if power_data:
        t0_candidates.append(power_data[0]['timestamp'])
    start_time = min(t0_candidates)
    
    rem_times, rem_counts = [0.0], [len(paper_timestamps)]
    current_rem = len(paper_timestamps)
    
    completed_before_start = sum(1 for ts in paper_timestamps if ts < start_time)
    current_rem -= completed_before_start
    rem_counts[0] = current_rem
    
    for ts in paper_timestamps:
        if ts >= start_time:
            rem_times.append((ts - start_time).total_seconds() / 60)
            current_rem -= 1
            rem_counts.append(current_rem)
            
    pwr_times = [(p['timestamp'] - start_time).total_seconds() / 60 for p in power_data if p['timestamp'] >= start_time]
    pwr_vals = [p['power'] for p in power_data if p['timestamp'] >= start_time]
    
    return rem_times, rem_counts, pwr_times, smooth_series(pwr_vals, 6)

# ============================================================================
# VISUALIZATION & OUTPUT
# ============================================================================

def plot_combined(d1, d2, out_chart):
    """Plot both datasets on a single figure with shared relative X-axis."""
    rem_t1, rem_c1, pwr_t1, pwr_s1 = prepare_plot_data(d1['power_data'], d1['paper_ts'])
    rem_t2, rem_c2, pwr_t2, pwr_s2 = prepare_plot_data(d2['power_data'], d2['paper_ts'])
    
    fig, ax1 = plt.subplots(figsize=(10, 6))
    
    # Colorblind-friendly palette (Okabe-Ito)
    C_REM_1, C_REM_2 = '#0072B2', '#D55E00' # Blue, Vermilion
    C_PWR_1, C_PWR_2 = '#CC79A7', '#009E73' # Purple, Green

    # Remaining Papers (Left Y) - Solid lines
    ax1.plot(rem_t1, rem_c1, color=C_REM_1, linestyle='-', linewidth=2.5, label='Remaining Papers (1 GPU)', drawstyle='steps-post')
    ax1.plot(rem_t2, rem_c2, color=C_REM_2, linestyle='-', linewidth=2.5, label='Remaining Papers (2 GPUs)', drawstyle='steps-post')
    
    max_rem = max(max(rem_c1) if rem_c1 else 0, max(rem_c2) if rem_c2 else 0)
    ax1.set_ylim(0, max(max_rem * 1.05, 1))
    ax1.set_ylabel('Remaining Papers', fontsize=12, fontweight='bold')
    
    # 5 papers per major tick, with horizontal grid lines
    ax1.yaxis.set_major_locator(MultipleLocator(5))
    ax1.grid(True, axis='y', alpha=0.3, linestyle='--')
    
    # Wall Power (Right Y) - Solid lines with translucent fill
    ax2 = ax1.twinx()
    
    ax2.plot(pwr_t1, pwr_s1, color=C_PWR_1, linestyle='-', linewidth=1.5, label='Wall Power (1 GPU)', alpha=0.9)
    ax2.fill_between(pwr_t1, pwr_s1, color=C_PWR_1, alpha=0.2, label='_nolegend_')
    
    ax2.plot(pwr_t2, pwr_s2, color=C_PWR_2, linestyle='-', linewidth=1.5, label='Wall Power (2 GPUs)', alpha=0.9)
    ax2.fill_between(pwr_t2, pwr_s2, color=C_PWR_2, alpha=0.2, label='_nolegend_')
    
    ax2.set_ylim(0, 1000)
    ax2.set_ylabel('Wall Power (W)', fontsize=12, fontweight='bold')
    ax2.yaxis.set_major_locator(MultipleLocator(200))
    ax2.grid(False)
    
    # X-Axis (Shared relative time)
    all_times = rem_t1 + rem_t2 + pwr_t1 + pwr_t2
    max_time = max(all_times, default=1)
    ax1.set_xlim(0, max_time)
    ax1.set_xlabel('Elapsed Time (minutes)', fontsize=12, fontweight='bold')
    
    # 1 minute minor ticks, 5 minutes major ticks
    ax1.xaxis.set_major_locator(MultipleLocator(5))
    ax1.xaxis.set_minor_locator(MultipleLocator(1))
    
    ax1.grid(True, axis='x', which='major', alpha=0.3, linestyle='--')
    ax1.grid(True, axis='x', which='minor', alpha=0.15, linestyle=':')
    
    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=10, framealpha=0.9)
    
    plt.tight_layout()
    plt.savefig(out_chart, dpi=600, bbox_inches='tight', facecolor='white')
    print(f"✅ Saved combined chart: {out_chart}")

def compute_metrics(paper_ts, power_data):
    """
    Calculate performance and efficiency metrics split by phase.
    """
    if not paper_ts or not power_data:
        return {k: 0 for k in ['total_papers', 'total_duration_min', 'total_avg_power', 'total_energy_kwh', 
                               'total_papers_per_hour', 'total_papers_per_kwh',
                               'init_duration_min', 'init_avg_power', 'init_energy_kwh', 'init_papers_per_hour', 'init_papers_per_kwh',
                               'verif_duration_min', 'verif_avg_power', 'verif_energy_kwh', 'verif_papers_per_hour', 'verif_papers_per_kwh']}
        
    total_papers = len(paper_ts)
    
    process_start = power_data[0]['timestamp']
    verification_start = paper_ts[0]
    end_time = paper_ts[-1]
    
    # Total Process
    total_energy_kwh, total_avg_power = integrate_power(power_data, process_start, end_time)
    total_duration_min = (end_time - process_start).total_seconds() / 60.0
    total_duration_hrs = total_duration_min / 60.0
    
    # Classification Phase
    init_energy_kwh, init_avg_power = integrate_power(power_data, process_start, verification_start)
    init_duration_min = (verification_start - process_start).total_seconds() / 60.0
    init_duration_hrs = init_duration_min / 60.0
    
    # Verification Phase
    verif_energy_kwh, verif_avg_power = integrate_power(power_data, verification_start, end_time)
    verif_duration_min = (end_time - verification_start).total_seconds() / 60.0
    verif_duration_hrs = verif_duration_min / 60.0
    
    return {
        'total_papers': total_papers,
        'total_duration_min': total_duration_min,
        'total_avg_power': total_avg_power,
        'total_energy_kwh': total_energy_kwh,
        'total_papers_per_hour': total_papers / total_duration_hrs if total_duration_hrs > 0 else 0,
        'total_papers_per_kwh': total_papers / total_energy_kwh if total_energy_kwh > 0 else 0,
        
        'init_duration_min': init_duration_min,
        'init_avg_power': init_avg_power,
        'init_energy_kwh': init_energy_kwh,
        'init_papers_per_hour': total_papers / init_duration_hrs if init_duration_hrs > 0 else 0,
        'init_papers_per_kwh': total_papers / init_energy_kwh if init_energy_kwh > 0 else 0,
        
        'verif_duration_min': verif_duration_min,
        'verif_avg_power': verif_avg_power,
        'verif_energy_kwh': verif_energy_kwh,
        'verif_papers_per_hour': total_papers / verif_duration_hrs if verif_duration_hrs > 0 else 0,
        'verif_papers_per_kwh': total_papers / verif_energy_kwh if verif_energy_kwh > 0 else 0,
    }

def generate_latex_table(m1, m2, out_tex):
    """Generate a LaTeX table with phase-split metrics and ratio column."""
    def ratio(v2, v1):
        try:
            return f"{float(v2)/float(v1):.2f}$\\times$" if float(v1) != 0 else "N/A"
        except (ValueError, TypeError):
            return "N/A"

    def fmt(val, decimals):
        return f"{val:.{decimals}f}"

    rows = [
        ("Total Papers", fmt(m1['total_papers'],0), fmt(m2['total_papers'],0), ratio(m2['total_papers'], m1['total_papers'])),
        r"\hline",
        r"\textbf{Total Process} & & & \\",
        ("Duration (min)", fmt(m1['total_duration_min'],1), fmt(m2['total_duration_min'],1), ratio(m2['total_duration_min'], m1['total_duration_min'])),
        ("Average Power (W)", fmt(m1['total_avg_power'],0), fmt(m2['total_avg_power'],0), ratio(m2['total_avg_power'], m1['total_avg_power'])),
        ("Total Energy (kWh)", fmt(m1['total_energy_kwh'],3), fmt(m2['total_energy_kwh'],3), ratio(m2['total_energy_kwh'], m1['total_energy_kwh'])),
        ("Papers / Hour", fmt(m1['total_papers_per_hour'],1), fmt(m2['total_papers_per_hour'],1), ratio(m2['total_papers_per_hour'], m1['total_papers_per_hour'])),
        ("Papers / kWh", fmt(m1['total_papers_per_kwh'],1), fmt(m2['total_papers_per_kwh'],1), ratio(m2['total_papers_per_kwh'], m1['total_papers_per_kwh'])),
        r"\hline",
        r"\textbf{Classification Phase} & & & \\",
        ("Duration (min)", fmt(m1['init_duration_min'],1), fmt(m2['init_duration_min'],1), ratio(m2['init_duration_min'], m1['init_duration_min'])),
        ("Average Power (W)", fmt(m1['init_avg_power'],0), fmt(m2['init_avg_power'],0), ratio(m2['init_avg_power'], m1['init_avg_power'])),
        ("Energy (kWh)", fmt(m1['init_energy_kwh'],3), fmt(m2['init_energy_kwh'],3), ratio(m2['init_energy_kwh'], m1['init_energy_kwh'])),
        ("Papers / Hour", fmt(m1['init_papers_per_hour'],1), fmt(m2['init_papers_per_hour'],1), ratio(m2['init_papers_per_hour'], m1['init_papers_per_hour'])),
        ("Papers / kWh", fmt(m1['init_papers_per_kwh'],1), fmt(m2['init_papers_per_kwh'],1), ratio(m2['init_papers_per_kwh'], m1['init_papers_per_kwh'])),
        r"\hline",
        r"\textbf{Verification Phase} & & & \\",
        ("Duration (min)", fmt(m1['verif_duration_min'],1), fmt(m2['verif_duration_min'],1), ratio(m2['verif_duration_min'], m1['verif_duration_min'])),
        ("Average Power (W)", fmt(m1['verif_avg_power'],0), fmt(m2['verif_avg_power'],0), ratio(m2['verif_avg_power'], m1['verif_avg_power'])),
        ("Energy (kWh)", fmt(m1['verif_energy_kwh'],3), fmt(m2['verif_energy_kwh'],3), ratio(m2['verif_energy_kwh'], m1['verif_energy_kwh'])),
        ("Papers / Hour", fmt(m1['verif_papers_per_hour'],1), fmt(m2['verif_papers_per_hour'],1), ratio(m2['verif_papers_per_hour'], m1['verif_papers_per_hour'])),
        ("Papers / kWh", fmt(m1['verif_papers_per_kwh'],1), fmt(m2['verif_papers_per_kwh'],1), ratio(m2['verif_papers_per_kwh'], m1['verif_papers_per_kwh'])),
        r"\hline",
    ]

    tex = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{Performance Comparison: 1 GPU vs 2 GPUs}",
        r"\label{tab:dual_vs_single_gpu}",
        r"\begin{tabular}{l c c c}",
        r"\hline",
        r"\textbf{Metric} & \textbf{1 GPU} & \textbf{2 GPUs} & \textbf{Ratio (2/1)} \\",
        r"\hline"
    ]
    
    for row in rows:
        if isinstance(row, str):
            tex.append(row)
        else:
            tex.append(f"{row[0]} & {row[1]} & {row[2]} & {row[3]} \\\\")
            
    tex.extend([r"\end{tabular}", r"\end{table}"])
    
    with open(out_tex, 'w') as f:
        f.write('\n'.join(tex))
    print(f"✅ Saved LaTeX table: {out_tex}")

# ============================================================================
# MAIN
# ============================================================================
def generate_latex_macros(m1: dict, m2: dict, out_macros: Path, batch_size_ratio=None) -> None:
    """
    Generate LaTeX macros for the 1-GPU vs 2-GPU comparison.

    Generated macros include:
    - placeholderSpeedupX
    - placeholderSpeedX
    - placeholderEfficiencyX

    The optional batch-size ratio macro is emitted only when explicitly
    supplied, because this script cannot infer it from timestamps/power logs.
    """
    def safe_macro(name: str, value: str) -> str:
        return (
            f"\\providecommand{{\\{name}}}{{}}\n"
            f"\\renewcommand{{\\{name}}}{{{value}}}"
        )

    def get_float(d: dict, key: str) -> float:
        try:
            return float(d.get(key, 0.0) or 0.0)
        except Exception:
            return 0.0

    def ratio(a: float, b: float) -> float:
        try:
            return float(a) / float(b) if float(b) != 0.0 else 0.0
        except Exception:
            return 0.0

    speedup = ratio(
        get_float(m2, "total_papers_per_hour"),
        get_float(m1, "total_papers_per_hour")
    )

    efficiency = ratio(
        get_float(m2, "total_papers_per_kwh"),
        get_float(m1, "total_papers_per_kwh")
    )

    classification_speedup = ratio(
        get_float(m2, "init_papers_per_hour"),
        get_float(m1, "init_papers_per_hour")
    )

    verification_speedup = ratio(
        get_float(m2, "verif_papers_per_hour"),
        get_float(m1, "verif_papers_per_hour")
    )

    duration_ratio = ratio(
        get_float(m2, "total_duration_min"),
        get_float(m1, "total_duration_min")
    )

    macros = [
        "% AUTO-GENERATED GPU-COMPARISON MACROS: DO NOT EDIT MANUALLY",
        "% Generated by the 1 GPU vs 2 GPUs comparison script",
        "",
        safe_macro("placeholderSpeedupX", f"{speedup:.2f}"),
        safe_macro("placeholderSpeedX", f"{speedup:.2f}"),
        safe_macro("placeholderEfficiencyX", f"{efficiency:.2f}"),
        "",
        safe_macro("placeholderGpuTotalDurationRatio", f"{duration_ratio:.2f}"),
        safe_macro("placeholderGpuClassificationSpeedup", f"{classification_speedup:.2f}"),
        safe_macro("placeholderGpuVerificationSpeedup", f"{verification_speedup:.2f}"),
    ]

    if batch_size_ratio is not None:
        macros += [
            "",
            safe_macro("placeholderBatchSizeRatio", f"{float(batch_size_ratio):.1f}"),
        ]

    with open(out_macros, "w", encoding="utf-8") as f:
        f.write("\n".join(macros) + "\n")

    print(f"  LaTeX macros saved to: {out_macros}")

def main():
    parser = argparse.ArgumentParser(description="Compare 1 GPU vs 2 GPUs performance.")
    parser.add_argument('--db1', type=Path, required=True, help='1GPU DB path')
    parser.add_argument('--power1', type=Path, required=True, help='1GPU Power CSV')
    parser.add_argument('--db2', type=Path, required=True, help='2GPU DB path')
    parser.add_argument('--power2', type=Path, required=True, help='2GPU Power CSV')
    parser.add_argument('--out-chart', type=Path, default='gpu_comparison_chart.png')
    parser.add_argument('--out-tex', type=Path, default='gpu_comparison_table.tex')
    parser.add_argument('--out-macros', type=Path, default='gpu_comparison_macros.tex')
    parser.add_argument('--batch-size-ratio', type=float, default=None,
                        help='Optional measured max-batch-size ratio, e.g. 5.0')

    args = parser.parse_args()

    d1 = {
        'power_data': parse_power_log(args.power1),
        'paper_ts': get_paper_timestamps(args.db1)
    }

    d2 = {
        'power_data': parse_power_log(args.power2),
        'paper_ts': get_paper_timestamps(args.db2)
    }

    if not d1['paper_ts'] or not d2['paper_ts']:
        print("Error: One or both datasets have no paper completion timestamps.")
        return

    print("Calculating metrics...")
    m1 = compute_metrics(d1['paper_ts'], d1['power_data'])
    m2 = compute_metrics(d2['paper_ts'], d2['power_data'])

    print("Generating combined plot...")
    plot_combined(d1, d2, args.out_chart)

    print("Generating LaTeX table...")
    generate_latex_table(m1, m2, args.out_tex)

    print("Generating LaTeX macros...")
    generate_latex_macros(m1, m2, args.out_macros, args.batch_size_ratio)


if __name__ == "__main__":
    main()
    