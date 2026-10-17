"""
time_power_charts.py
Power Usage vs. Paper Consensus Progress Visualization
- Parses 'llm_log' JSON for exact LLM completion times
- Parses PSU efficiency to detect 6 processing phases
- Full-height 15%-alpha phase shading, plain numbered markers at top
- Single legend box: data series + phases section with header
- LaTeX table with per-phase + aggregate + screening + full-classification metrics
"""

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MultipleLocator

# ============================================================================
# CONFIGURATION
# ============================================================================
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path.cwd()

DEFAULT_CSV_PATH    = SCRIPT_DIR / "sensor_log27.CSV"
DEFAULT_DB_PATH     = SCRIPT_DIR / "db.sqlite"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "consensus_progress.png"
DEFAULT_TEX_PATH    = SCRIPT_DIR / "consensus_metrics.tex"

POWER_SMOOTHING_WINDOW = 2

FULL_LOAD_EFF = 94.0
LOW_LOAD_EFF  = 90.0

# --- Ticks / grid intervals ---
PAPER_MAJOR_INTERVAL = 400
PAPER_MINOR_INTERVAL = 200
TIME_MAJOR_INTERVAL  = 10
TIME_MINOR_INTERVAL  = 5
POWER_TICK_INTERVAL  = 200
POWER_AXIS_MAX       = 1500

# Phase tint alpha (used identically on chart and in legend swatches)
PHASE_ALPHA = 0.15

# Okabe-Ito palette
C_REM = '#0072B2'   # Blue
C_PWR = '#D55E00'   # Vermilion

PHASE_COLOR = {
    'loading screening model':              '#E69F00',
    'screening phase':                      '#56B4E9',
    'loading full classification model':    '#F0E442',
    'initial classification phase':         '#009E73',
    'verification and re-classification':   '#CC79A7',
    'idle':                                 '#999999',
}

PHASE_LABEL = {
    'loading screening model':              'Loading screening model',
    'screening phase':                      'Screening phase',
    'loading full classification model':    'Loading full classification model',
    'initial classification phase':         'Initial classification phase',
    'verification and re-classification':   'Verification/Reclassification phase',
    'idle':                                 'Idle',
}

# Phase keys that do NOT count as "useful work" when computing aggregate
# efficiency numbers (loading, idle). Screening + classification + verify
# are the phases where papers are actually being processed.
NON_WORK_PHASES = {
    'loading screening model',
    'loading full classification model',
    'idle',
}

# ============================================================================
# CSV PARSING
# ============================================================================
def parse_power_log(csv_path):
    power_data = []
    if not csv_path.exists():
        return power_data

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        try:
            header = next(reader)
        except StopIteration:
            return power_data

        def find_col(*keywords):
            for i, h in enumerate(header):
                hl = h.lower()
                if all(k.lower() in hl for k in keywords):
                    return i
            return None

        col_ts    = find_col('date/time')
        col_p_in  = find_col('psu power in', '[w]')
        col_p_out = find_col('psu power out', '[w]')
        col_eff   = find_col('efficiency')

        if col_ts is None or col_p_in is None:
            return power_data

        for row in reader:
            if len(row) <= max(col_ts, col_p_in):
                continue
            try:
                ts   = datetime.fromisoformat(row[col_ts].strip().replace('Z', '+00:00'))
                p_in = float(row[col_p_in].strip().replace(',', '.'))

                eff = None
                if col_eff is not None and len(row) > col_eff:
                    try:
                        eff = float(row[col_eff].strip().replace(',', '.').replace('%', ''))
                    except ValueError:
                        eff = None
                if eff is None and col_p_out is not None and len(row) > col_p_out:
                    try:
                        p_out = float(row[col_p_out].strip().replace(',', '.'))
                        if p_in > 0:
                            eff = 100.0 * p_out / p_in
                    except ValueError:
                        eff = None

                power_data.append({
                    'timestamp':  ts,
                    'power':      p_in,
                    'efficiency': eff if eff is not None else 0.0,
                })
            except (ValueError, IndexError):
                continue
    return power_data

# ============================================================================
# INTEGRATE POWER (same as charts.py)
# ============================================================================
def integrate_power(power_data, t_start, t_end):
    """Trapezoid-style integration of power over [t_start, t_end].

    Returns (energy_kwh, avg_power_w).
    """
    energy_wh = 0.0
    if not power_data or t_end <= t_start:
        return 0.0, 0.0

    for i in range(len(power_data) - 1):
        t1, t2 = power_data[i]['timestamp'], power_data[i + 1]['timestamp']
        p      = power_data[i]['power']

        clip_start = max(t1, t_start)
        clip_end   = min(t2, t_end)
        if clip_end > clip_start:
            delta_hrs = (clip_end - clip_start).total_seconds() / 3600.0
            energy_wh += p * delta_hrs

    total_time_hrs = (t_end - t_start).total_seconds() / 3600.0
    avg_power      = (energy_wh / total_time_hrs) if total_time_hrs > 0 else 0.0
    return energy_wh / 1000.0, avg_power

# ============================================================================
# SMOOTH
# ============================================================================
def smooth_series(values, window):
    if len(values) < window:
        return values
    half = window // 2
    return [
        sum(values[max(0, i - half):min(len(values), i + half + 1)]) /
        len(values[max(0, i - half):min(len(values), i + half + 1)])
        for i in range(len(values))
    ]

# ============================================================================
# PAPER TIMESTAMPS
# ============================================================================
def get_paper_timestamps(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT llm_log FROM papers "
        "WHERE llm_log IS NOT NULL AND llm_log != '[]' AND llm_log != ''"
    )
    timestamps = []
    for (log_str,) in cur.fetchall():
        try:
            logs = json.loads(log_str)
            latest = None
            for entry in logs:
                if entry.get('type') == 'averaged_llm':
                    ts_str = entry.get('timestamp')
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.strip().replace('Z', '+00:00'))
                        if latest is None or ts > latest:
                            latest = ts
            if latest:
                timestamps.append(latest)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
    conn.close()
    timestamps.sort()
    return timestamps

# ============================================================================
# PHASE DETECTION
# ============================================================================
def detect_phases(power_data, paper_ts):
    phases = []
    n = len(power_data)
    if n == 0:
        return phases

    def find_pattern(start_idx, cond, count):
        for i in range(start_idx, n - count + 1):
            if all(cond(power_data[j]) for j in range(i, i + count)):
                return i
        return None

    def is_full(p): return p['efficiency'] >= FULL_LOAD_EFF
    def is_low(p):  return 0 < p['efficiency'] < LOW_LOAD_EFF

    start_idx = 0
    last_ts   = power_data[-1]['timestamp']

    def emit(name, s_idx, e_idx_or_ts):
        s_ts = power_data[s_idx]['timestamp']
        e_ts = (power_data[e_idx_or_ts]['timestamp']
                if isinstance(e_idx_or_ts, int) else e_idx_or_ts)
        if e_ts > s_ts:
            phases.append((name, s_ts, e_ts))
            return True
        return False

    idx = find_pattern(start_idx, is_full, 2)
    emit('loading screening model', start_idx, idx if idx is not None else last_ts)
    if idx is None: return phases
    start_idx = idx

    idx = find_pattern(start_idx, is_low, 3)
    emit('screening phase', start_idx, idx if idx is not None else last_ts)
    if idx is None: return phases
    start_idx = idx

    idx = find_pattern(start_idx, is_full, 2)
    emit('loading full classification model', start_idx, idx if idx is not None else last_ts)
    if idx is None: return phases
    start_idx = idx

    s_ts = power_data[start_idx]['timestamp']
    end_ts = next((ts for ts in paper_ts if ts > s_ts), None)
    if end_ts is None:
        emit('initial classification phase', start_idx, last_ts)
        return phases
    emit('initial classification phase', start_idx, end_ts)

    while start_idx < n and power_data[start_idx]['timestamp'] < end_ts:
        start_idx += 1
    if start_idx >= n:
        return phases

    idx = find_pattern(start_idx, is_low, 4)
    emit('verification and re-classification', start_idx,
         idx if idx is not None else last_ts)
    if idx is None: return phases
    start_idx = idx

    emit('idle', start_idx, last_ts)
    return phases

# ============================================================================
# METRICS
# ============================================================================

def compute_metrics(phases, power_data, paper_ts):
    """Compute per-phase and aggregate metrics.

    Returns a dict with everything we want to render.
    """
    m = {}
    total_papers = len(paper_ts)
    m['total_papers'] = total_papers

    if not power_data:
        return m

    # ---- Total process ---------------------------------------------------
    t_start = power_data[0]['timestamp']
    t_end   = power_data[-1]['timestamp']
    m['total_duration_min'] = (t_end - t_start).total_seconds() / 60.0
    total_energy_kwh, total_avg_power = integrate_power(power_data, t_start, t_end)
    m['total_energy_kwh'] = total_energy_kwh
    m['total_avg_power']  = total_avg_power

    total_hours = m['total_duration_min'] / 60.0
    m['total_papers_per_hour'] = total_papers / total_hours if total_hours > 0 else 0.0
    m['total_papers_per_kwh']  = total_papers / total_energy_kwh if total_energy_kwh > 0 else 0.0

    # ---- Per-phase breakdown --------------------------------------------
    per_phase = []
    for name, s_ts, e_ts in phases:
        dur_min = (e_ts - s_ts).total_seconds() / 60.0
        energy_kwh, avg_power = integrate_power(power_data, s_ts, e_ts)
        per_phase.append({
            'name':        name,
            'start_ts':    s_ts,
            'end_ts':      e_ts,
            'duration_min': dur_min,
            'avg_power':   avg_power,
            'energy_kwh':  energy_kwh,
            'is_work':     name not in NON_WORK_PHASES,
        })
    m['per_phase'] = per_phase

    # ---- Useful-work aggregate (excludes loading + idle) ----------------
    work_energy_kwh = sum(p['energy_kwh']  for p in per_phase if p['is_work'])
    work_dur_min    = sum(p['duration_min'] for p in per_phase if p['is_work'])
    work_avg_power  = ((work_energy_kwh * 1000) / (work_dur_min / 60.0)
                       if work_dur_min > 0 else 0.0)
    m['work_energy_kwh']    = work_energy_kwh
    m['work_duration_min']  = work_dur_min
    m['work_avg_power']     = work_avg_power
    work_hours              = work_dur_min / 60.0
    m['work_papers_per_hour'] = total_papers / work_hours if work_hours > 0 else 0.0
    m['work_papers_per_kwh']  = (total_papers / work_energy_kwh
                                 if work_energy_kwh > 0 else 0.0)

    # ---- Screening-phase specific ---------------------------------------
    # The screening model is fed the ENTIRE input set. Papers processed
    # by screening = len(paper_ts). Only a subset survives and continues
    # into the full classification pipeline.
    screening = next((p for p in per_phase
                      if p['name'] == 'screening phase'), None)
    screening_end_ts = None
    if screening:
        screening_papers = total_papers
        s_dur_h          = screening['duration_min'] / 60.0
        m['screening_papers']          = screening_papers
        m['screening_duration_min']    = screening['duration_min']
        m['screening_avg_power']       = screening['avg_power']
        m['screening_energy_kwh']      = screening['energy_kwh']
        m['screening_papers_per_hour'] = (screening_papers / s_dur_h
                                          if s_dur_h > 0 else 0.0)
        m['screening_papers_per_kwh']  = (
            screening_papers / screening['energy_kwh']
            if screening['energy_kwh'] > 0 else 0.0
        )
        screening_end_ts = screening['end_ts']

    # ---- Full-classification specific -----------------------------------
    # Classification + verification is one measurable unit: papers only
    # decrement the remaining count once they finish verification, so
    # measuring "classification alone" would always read 0 papers.
    # The papers processed by this unit are the survivors of screening.
    init  = next((p for p in per_phase
                  if p['name'] == 'initial classification phase'), None)
    verif = next((p for p in per_phase
                  if p['name'] == 'verification and re-classification'), None)
    if init and verif:
        s_ts = init['start_ts']
        e_ts = verif['end_ts']
        dur_min = (e_ts - s_ts).total_seconds() / 60.0
        energy_kwh, avg_power = integrate_power(power_data, s_ts, e_ts)

        # Survivors of screening = papers whose final completion
        # timestamp falls *after* screening ended.
        cutoff_ts   = screening_end_ts if screening_end_ts is not None else s_ts
        full_papers = sum(1 for ts in paper_ts if ts > cutoff_ts)

        dur_h = dur_min / 60.0
        m['full_papers']          = full_papers
        m['full_duration_min']    = dur_min
        m['full_avg_power']       = avg_power
        m['full_energy_kwh']      = energy_kwh
        m['full_papers_per_hour'] = (full_papers / dur_h) if dur_h > 0 else 0.0
        m['full_papers_per_kwh']  = (full_papers / energy_kwh
                                     if energy_kwh > 0 else 0.0)

    return m

# ============================================================================
# LATEX TABLE
# ============================================================================

def generate_latex_table(m, out_tex, caption=None, label="tab:consensus_metrics"):
    """Render the metrics dict as a two-column per-stage LaTeX table."""
    if caption is None:
        caption = ("Energy and performance metrics per pipeline stage "
                   "for the S4 full-pipeline run.")

    def fmt_num(v, d=0):
        """Thousand-separated, fixed-decimals; '--' on bad input."""
        try:
            return f"{float(v):,.{d}f}"
        except (TypeError, ValueError):
            return "--"

    screening_papers = m.get('screening_papers', m.get('total_papers', 0))
    full_papers      = m.get('full_papers', 0)

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\begin{tabular}{l r r}",
        r"\hline",
        r"\textbf{Metric} & \textbf{Stage 1: Screening} & "
        r"\textbf{Stage 2: Full classification} \\",
        r"\hline",
        rf"Papers processed & "
        rf"{fmt_num(screening_papers, 0)} & "
        rf"{fmt_num(full_papers, 0)} \\",
        rf"Duration (min) & "
        rf"{fmt_num(m.get('screening_duration_min', 0), 1)} & "
        rf"{fmt_num(m.get('full_duration_min', 0), 1)} \\",
        rf"Average power (W) & "
        rf"{fmt_num(m.get('screening_avg_power', 0), 0)} & "
        rf"{fmt_num(m.get('full_avg_power', 0), 0)} \\",
        rf"Energy (kWh) & "
        rf"{fmt_num(m.get('screening_energy_kwh', 0), 3)} & "
        rf"{fmt_num(m.get('full_energy_kwh', 0), 3)} \\",
        rf"Papers / hour & "
        rf"{fmt_num(m.get('screening_papers_per_hour', 0), 0)} & "
        rf"{fmt_num(m.get('full_papers_per_hour', 0), 0)} \\",
        rf"Papers / kWh & "
        rf"{fmt_num(m.get('screening_papers_per_kwh', 0), 0)} & "
        rf"{fmt_num(m.get('full_papers_per_kwh', 0), 0)} \\",
        r"\hline",
        r"\end{tabular}",
        r"\end{table}",
    ]

    with open(out_tex, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"✅ Saved LaTeX table: {out_tex}")
    
# ============================================================================
# REMAINING LINE
# ============================================================================
def build_remaining_line(power_data, paper_timestamps):
    if not power_data:
        if not paper_timestamps:
            return []
        total = len(paper_timestamps)
        return [
            {'timestamp': ts, 'remaining': total - i - 1}
            for i, ts in enumerate(paper_timestamps)
        ]
    total = len(paper_timestamps)
    out, idx, rem = [], 0, total
    for entry in power_data:
        ts = entry['timestamp']
        while idx < len(paper_timestamps) and paper_timestamps[idx] <= ts:
            rem -= 1
            idx += 1
        out.append({'timestamp': ts, 'remaining': rem})
    return out

def to_elapsed(data, start):
    return [
        {'elapsed': (e['timestamp'] - start).total_seconds() / 60,
         **{k: v for k, v in e.items() if k != 'timestamp'}}
        for e in data
    ]

# ============================================================================
# PLOT
# ============================================================================
def plot(power_data, remaining_data, phases, output_path, has_power=True):
    if not remaining_data:
        print("❌ No paper data to plot")
        return

    if has_power and power_data:
        start         = power_data[0]['timestamp']
        power_elapsed = to_elapsed(power_data, start)
        times         = [d['elapsed'] for d in power_elapsed]
        power_raw     = [d['power']   for d in power_elapsed]
        power_smooth  = smooth_series(power_raw, POWER_SMOOTHING_WINDOW)
    else:
        start         = remaining_data[0]['timestamp']
        times         = [(e['timestamp'] - start).total_seconds() / 60
                         for e in remaining_data]
        power_smooth  = None

    rem_elapsed = to_elapsed(remaining_data, start)
    rem_times   = [d['elapsed']   for d in rem_elapsed]
    rem_count   = [d['remaining'] for d in rem_elapsed]

    fig, ax1 = plt.subplots(figsize=(10, 6))

    phase_spans = []
    for i, (name, s_ts, e_ts) in enumerate(phases, start=1):
        t0 = (s_ts - start).total_seconds() / 60
        t1 = (e_ts - start).total_seconds() / 60
        if t1 <= t0:
            continue
        color = PHASE_COLOR.get(name, '#cccccc')
        ax1.axvspan(t0, t1, color=color, alpha=PHASE_ALPHA, zorder=0)
        phase_spans.append((i, name, t0, t1))

    ax1.plot(rem_times, rem_count, color=C_REM, linewidth=2.5,
             label='Remaining Papers', drawstyle='steps-post', zorder=3)

    max_rem = max(rem_count) if rem_count else 1
    ax1.set_ylim(0, max(max_rem * 1.05, 1))
    ax1.set_ylabel('Remaining Papers', fontsize=12, fontweight='bold')
    ax1.yaxis.set_major_locator(MultipleLocator(PAPER_MAJOR_INTERVAL))
    ax1.yaxis.set_minor_locator(MultipleLocator(PAPER_MINOR_INTERVAL))

    ax2 = None
    if has_power and power_smooth:
        ax2 = ax1.twinx()
        ax2.plot(times, power_smooth, color=C_PWR, linewidth=1.5,
                 label='Wall Power (W)', alpha=0.9, zorder=3)
        ax2.set_ylim(0, POWER_AXIS_MAX)
        ax2.set_ylabel('Wall Power (W)', fontsize=12, fontweight='bold')
        ax2.yaxis.set_major_locator(MultipleLocator(POWER_TICK_INTERVAL))

    all_times = list(times) + list(rem_times)
    max_time  = max(all_times, default=1)
    ax1.set_xlim(0, max_time)
    ax1.set_xlabel('Elapsed Time (minutes)', fontsize=12, fontweight='bold')
    ax1.xaxis.set_major_locator(MultipleLocator(TIME_MAJOR_INTERVAL))
    ax1.xaxis.set_minor_locator(MultipleLocator(TIME_MINOR_INTERVAL))

    ax1.grid(True, axis='both', which='major',
             alpha=0.35, linestyle='--', linewidth=0.7, zorder=1)
    ax1.grid(True, axis='both', which='minor',
             alpha=0.12, linestyle=':', linewidth=0.5, zorder=1)
    if ax2 is not None:
        ax2.grid(False)
        ax2.xaxis.grid(False)
        ax2.yaxis.grid(False)
    ax1.set_axisbelow(True)

    # Phase numbers at top, plain text
    for i, name, t0, t1 in phase_spans:
        mid = 0.5 * (t0 + t1)
        ax1.text(
            mid, 0.985, str(i),
            transform=ax1.get_xaxis_transform(),
            ha='center', va='top',
            fontsize=8, color='#222222',
            zorder=6,
        )

    # Single legend
    handles, labels = ax1.get_legend_handles_labels()
    if ax2 is not None:
        h2, l2 = ax2.get_legend_handles_labels()
        handles += h2
        labels  += l2

    handles.append(Patch(facecolor='none', edgecolor='none'))
    labels.append('')

    handles.append(Patch(facecolor='none', edgecolor='none'))
    labels.append(r"$\mathbf{Processing\ phases}$")

    for i, name, _t0, _t1 in phase_spans:
        handles.append(Patch(
            facecolor=PHASE_COLOR.get(name, '#cccccc'),
            edgecolor='#888888', linewidth=0.4,
            alpha=PHASE_ALPHA,
        ))
        labels.append(f"{i}. {PHASE_LABEL.get(name, name)}")

    ax1.legend(
        handles, labels,
        loc='upper right',
        bbox_to_anchor=(0.98, 0.95),
        fontsize=9, framealpha=0.92,
        labelspacing=0.35, borderpad=0.55,
    )

    plt.tight_layout()
    plt.savefig(output_path, dpi=600, bbox_inches='tight', facecolor='white')
    print(f"✅ Saved: {output_path}")

    # Console summary
    total_papers = rem_count[0] if rem_count else 0
    total_min    = times[-1] if times else 0
    total_hours  = total_min / 60
    avg_power    = (sum(power_smooth) / len(power_smooth)) if (has_power and power_smooth) else 0
    energy_kwh   = (total_hours * avg_power) / 1000 if total_hours > 0 and avg_power > 0 else 0
    pph          = total_papers / total_hours if total_hours > 0 else 0
    ppkwh        = total_papers / energy_kwh  if energy_kwh > 0 else 0

    print("\n📊 Summary:")
    print(f"   📄 Papers processed: {total_papers}")
    if total_hours > 0:
        print(f"   ⏱️  Duration: {total_min:.1f} min ({total_hours:.2f} hrs)")
        print(f"   🚀 Papers per hour: {pph:.2f}")
    if has_power and power_smooth:
        print(f"   ⚡ Avg Power: {avg_power:.1f} W")
        if total_hours > 0:
            print(f"   🔋 Total Energy: {energy_kwh:.2f} kWh")
            print(f"   🌱 Papers per kWh: {ppkwh:.2f}")

def generate_latex_macros(m: dict, out_macros: Path) -> None:
    """
    Generate LaTeX macros from the full-pipeline power/time metrics.

    These macros are used in the manuscript for the S4 benchmark:
    - corpus size;
    - on-topic survivors;
    - average wall power;
    - screening time;
    - Stage-2 throughput;
    - total useful runtime.
    """
    m = m or {}

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

    def fmt_fixed(v, decimals: int) -> str:
        try:
            return f"{float(v):.{decimals}f}"
        except Exception:
            return f"{0.0:.{decimals}f}"

    per_phase = m.get("per_phase", []) or []

    initial_phase = next(
        (p for p in per_phase if p.get("name") == "initial classification phase"),
        None
    )
    screening_phase = next(
        (p for p in per_phase if p.get("name") == "screening phase"),
        None
    )

    initial_class_minutes = (
        float(initial_phase.get("duration_min", 0.0))
        if initial_phase is not None
        else 0.0
    )

    # Optional diagnostic macro: screening + initial classification.
    # Not required by the current draft, but useful if the caption is
    # interpreted as the flat portion from the beginning of useful work.
    initial_flat_minutes = 0.0
    for p in per_phase:
        name = p.get("name")
        if name == "screening phase":
            initial_flat_minutes += float(p.get("duration_min", 0.0))
        elif name == "initial classification phase":
            initial_flat_minutes += float(p.get("duration_min", 0.0))
            break

    total_minutes = m.get("work_duration_min")
    if not total_minutes:
        total_minutes = m.get("total_duration_min", 0.0)

    avg_power = m.get("work_avg_power")
    if not avg_power:
        avg_power = m.get("total_avg_power", 0.0)

    screening_time = (
        float(screening_phase.get("duration_min", 0.0))
        if screening_phase is not None
        else float(m.get("screening_duration_min", 0.0) or 0.0)
    )

    full_papers = int(m.get("full_papers", 0) or 0)
    classify_throughput = float(m.get("full_papers_per_hour", 0.0) or 0.0)

    macros = [
        "% AUTO-GENERATED S4 / FULL-PIPELINE MACROS: DO NOT EDIT MANUALLY",
        "% Generated by time_power_charts.py",
        "",
        safe_macro("placeholderSfourSize", fmt_int(m.get("total_papers", 0))),
        safe_macro("placeholderSfourOnTopic", fmt_int(full_papers)),
        safe_macro("placeholderAvgPower", fmt_int(avg_power)),
        safe_macro("placeholderInitialClassMinutes", fmt_fixed(initial_class_minutes, 1)),
        safe_macro("placeholderInitialFlatMinutes", fmt_fixed(initial_flat_minutes, 1)),
        safe_macro("placeholderTotalMinutes", fmt_fixed(total_minutes, 1)),
        safe_macro("placeholderScreeningTime", fmt_fixed(screening_time, 1)),
        safe_macro("placeholderClassifyThroughput", fmt_fixed(classify_throughput, 2)),
        "",
        safe_macro("placeholderSfourEnergy", fmt_fixed(m.get("work_energy_kwh", m.get("total_energy_kwh", 0.0)), 3)),
        safe_macro("placeholderSfourPapersPerHour", fmt_fixed(m.get("work_papers_per_hour", 0.0), 2)),
        safe_macro("placeholderSfourPapersPerKwh", fmt_fixed(m.get("work_papers_per_kwh", 0.0), 2)),
        "",
        safe_macro("placeholderScreeningPapers", fmt_int(m.get("screening_papers", m.get("total_papers", 0)))),
        safe_macro("placeholderScreeningAvgPower", fmt_int(m.get("screening_avg_power", 0.0))),
        safe_macro("placeholderScreeningEnergy", fmt_fixed(m.get("screening_energy_kwh", 0.0), 3)),
        safe_macro("placeholderScreeningPapersPerHour", fmt_fixed(m.get("screening_papers_per_hour", 0.0), 2)),
        safe_macro("placeholderScreeningPapersPerKwh", fmt_fixed(m.get("screening_papers_per_kwh", 0.0), 2)),
        "",
        safe_macro("placeholderFullClassPapers", fmt_int(full_papers)),
        safe_macro("placeholderFullClassDuration", fmt_fixed(m.get("full_duration_min", 0.0), 1)),
        safe_macro("placeholderFullClassAvgPower", fmt_int(m.get("full_avg_power", 0.0))),
        safe_macro("placeholderFullClassEnergy", fmt_fixed(m.get("full_energy_kwh", 0.0), 3)),
        safe_macro("placeholderFullClassPapersPerHour", fmt_fixed(m.get("full_papers_per_hour", 0.0), 2)),
        safe_macro("placeholderFullClassPapersPerKwh", fmt_fixed(m.get("full_papers_per_kwh", 0.0), 2)),
    ]

    with open(out_macros, "w", encoding="utf-8") as f:
        f.write("\n".join(macros) + "\n")

    print(f"  LaTeX macros saved to: {out_macros}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Visualize power vs paper progress')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument('--power', type=Path, default=None)
    parser.add_argument('--no-power', action='store_true')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument('--out-tex', type=Path, default=DEFAULT_TEX_PATH,
                        help='Path to write the LaTeX metrics table.')

    try:
        default_macros = Path(__file__).parent.resolve() / "consensus_metrics_macros.tex"
    except NameError:
        default_macros = Path.cwd() / "consensus_metrics_macros.tex"

    parser.add_argument('--out-macros', type=Path, default=default_macros,
                        help='Path to write the LaTeX macro definitions.')

    args = parser.parse_args()

    if args.no_power:
        power_path, has_power = None, False
    elif args.power:
        power_path, has_power = args.power, True
    else:
        power_path, has_power = DEFAULT_CSV_PATH, True

    if not args.db.exists():
        return print(f"DB not found: {args.db}")

    if has_power and power_path and not power_path.exists():
        return print(f"Power CSV not found: {power_path}")

    print("Loading paper timestamps...")
    paper_ts = get_paper_timestamps(args.db)
    print(f"   {len(paper_ts)} papers found")

    if not paper_ts:
        return

    power_data = []
    if has_power and power_path:
        print("Loading power data...")
        power_data = parse_power_log(power_path)
        print(f"   {len(power_data)} samples")

    phases = []
    if has_power and power_data:
        has_eff = any(p['efficiency'] > 0 for p in power_data)
        if has_eff:
            print("Detecting phases...")
            phases = detect_phases(power_data, paper_ts)
            print(f"   {len(phases)} phase(s) detected")
            for name, s, e in phases:
                dur = (e - s).total_seconds() / 60
                print(f"      {name:<40} {dur:7.1f} min")
        else:
            print("No efficiency data found -- skipping phase detection.")

    remaining = build_remaining_line(power_data if has_power else [], paper_ts)

    print("Generating plot...")
    plot(power_data if has_power else None, remaining, phases,
         args.out, has_power=has_power)

    if has_power and power_data:
        print("Computing metrics for LaTeX table/macros...")
        metrics = compute_metrics(phases, power_data, paper_ts)

        if phases:
            generate_latex_table(metrics, args.out_tex)
        else:
            print("No phases detected; skipping LaTeX metrics table.")

        generate_latex_macros(metrics, args.out_macros)
    else:
        print("No power data; writing fallback macros with zeros.")
        generate_latex_macros({"total_papers": len(paper_ts)}, args.out_macros)


if __name__ == "__main__":
    main()