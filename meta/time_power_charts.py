"""
Power Usage vs. Paper Consensus Progress Visualization
- UPDATED FOR NEW DB: Parses 'llm_log' JSON to find exact LLM completion times
- Computes: total time, average power, papers per hour, papers per kWh
- Visualizes metrics via a text box overlay and console summary
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
# CONFIGURATION - Paths relative to THIS script
# ============================================================================
try:
    SCRIPT_DIR = Path(__file__).parent.resolve()
except NameError:
    SCRIPT_DIR = Path.cwd()

DEFAULT_CSV_PATH = SCRIPT_DIR / "sensor_log27.CSV"
DEFAULT_DB_PATH = SCRIPT_DIR / "db.sqlite"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "consensus_progress.png"

POWER_SMOOTHING_WINDOW = 6

# Increased intervals for sparser ticks
PAPER_TICK_INTERVAL = 10
POWER_TICK_INTERVAL = 100
TIME_MAJOR_INTERVAL = 15
TIME_MINOR_INTERVAL = 5

# ============================================================================
# PARSE POWER LOG CSV
# ============================================================================
def parse_power_log(csv_path):
    """Parse power CSV, return list of {timestamp, psu_power_in}."""
    power_data = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        
        col_ts = next(i for i, h in enumerate(header) if 'date/time' in h.lower())
        col_power = next(i for i, h in enumerate(header) if 'psu power in' in h.lower() and '[w]' in h.lower())
        
        for row in reader:
            if len(row) <= max(col_ts, col_power):
                continue
            try:
                ts = datetime.fromisoformat(row[col_ts].strip().replace('Z', '+00:00'))
                power = float(row[col_power].strip().replace(',', '.'))
                power_data.append({'timestamp': ts, 'power': power})
            except (ValueError, IndexError):
                continue
    return power_data

# ============================================================================
# SMOOTH TIME SERIES
# ============================================================================
def smooth_series(values, window):
    """Centered rolling average with edge handling."""
    if len(values) < window:
        return values
    half = window // 2
    return [
        sum(values[max(0,i-half):min(len(values),i+half+1)]) / 
        len(values[max(0,i-half):min(len(values),i+half+1)])
        for i in range(len(values))
    ]

# ============================================================================
# GET PAPER COMPLETION TIMESTAMPS FROM 'llm_log' (NEW DB SCHEMA)
# ============================================================================
def get_paper_timestamps(db_path):
    """Get list of completion timestamps for papers based on their llm_log."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != '[]' AND llm_log != ''")
    
    timestamps = []
    for (log_str,) in cursor.fetchall():
        try:
            logs = json.loads(log_str)
            latest_ts = None
            for entry in logs:
                # ignore user edits
                if entry.get('type') in ['averaged_llm']:
                    ts_str = entry.get('timestamp')
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.strip().replace('Z', '+00:00'))
                        if latest_ts is None or ts > latest_ts:
                            latest_ts = ts
            if latest_ts:
                timestamps.append(latest_ts)
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            continue
            
    conn.close()
    timestamps.sort()
    return timestamps

# ============================================================================
# BUILD REMAINING PAPERS LINE
# ============================================================================
def build_remaining_line(power_data, paper_timestamps):
    """Start at total papers, decrement by 1 at each paper's completion time."""
    if not power_data:
        if not paper_timestamps:
            return []
        total = len(paper_timestamps)
        return [
            {'timestamp': ts, 'remaining': total - i - 1}
            for i, ts in enumerate(paper_timestamps)
        ]
    
    total = len(paper_timestamps)
    remaining_line = []
    idx = 0
    remaining = total
    
    for entry in power_data:
        ts = entry['timestamp']
        while idx < len(paper_timestamps) and paper_timestamps[idx] <= ts:
            remaining -= 1
            idx += 1
        remaining_line.append({'timestamp': ts, 'remaining': remaining})
    
    return remaining_line

# ============================================================================
# CONVERT TO ELAPSED MINUTES
# ============================================================================
def to_elapsed(data, start):
    """Convert timestamps to minutes from start time."""
    return [
        {'elapsed': (e['timestamp'] - start).total_seconds() / 60, **{k:v for k,v in e.items() if k!='timestamp'}}
        for e in data
    ]

# ============================================================================
# CREATE PLOT & METRICS
# ============================================================================
def plot(power_data, remaining_data, output_path, has_power=True):
    if not remaining_data:
        print("❌ No paper data to plot")
        return
    
    if has_power and power_data:
        start = power_data[0]['timestamp']
        power_elapsed = to_elapsed(power_data, start)
        times = [d['elapsed'] for d in power_elapsed]
        power_raw = [d['power'] for d in power_elapsed]
        power_smooth = smooth_series(power_raw, POWER_SMOOTHING_WINDOW)
    else:
        start = remaining_data[0]['timestamp']
        times = [(e['timestamp'] - start).total_seconds() / 60 for e in remaining_data]
        power_smooth = None
    
    rem_elapsed = to_elapsed(remaining_data, start)
    rem_times = [d['elapsed'] for d in rem_elapsed]
    rem_count = [d['remaining'] for d in rem_elapsed]
    
    C_REM = '#1f77b4'
    C_PWR = "#c7290d"
    
    _fig, ax1 = plt.subplots(figsize=(7, 5))
    
    ax1.set_xlabel('Elapsed Time (minutes)', fontsize=14, fontweight='bold')
    ax1.plot(rem_times, rem_count, color=C_REM, linewidth=2.5, label='Remaining Papers', drawstyle='steps-post')
    
    max_rem = max(rem_count) if rem_count else 1
    ax1.set_ylim(0, max(max_rem * 1.05, 1))
    ax1.yaxis.set_major_locator(MultipleLocator(PAPER_TICK_INTERVAL))
    ax1.tick_params(axis='y', labelcolor=C_REM, labelsize=14)
    
    if has_power and power_smooth:
        ax2 = ax1.twinx()
        ax2.plot(times, power_smooth, color=C_PWR, linewidth=1.25, label='Wall Power (W)', alpha=0.95)
        ax2.set_ylim(0, 900)
        ax2.yaxis.set_major_locator(MultipleLocator(POWER_TICK_INTERVAL))
        ax2.tick_params(axis='y', labelcolor=C_PWR, labelsize=14)
        ax2.grid(False)
    else:
        ax2 = None
    
    ax1.grid(True, axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
    ax1.set_xlim(0, times[-1] if times else 0)
    ax1.xaxis.set_major_locator(MultipleLocator(TIME_MAJOR_INTERVAL))
    ax1.xaxis.set_minor_locator(MultipleLocator(TIME_MINOR_INTERVAL))
    ax1.grid(True, axis='x', which='major', alpha=0.3, linestyle='--')
    ax1.grid(True, axis='x', which='minor', alpha=0.15, linestyle=':')
    ax1.tick_params(axis='x', labelsize=12)
    
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels() if ax2 else ([], [])
    if lines1 + lines2:
        ax1.legend(lines1 + lines2, labels1 + labels2, loc='lower left', fontsize=14, framealpha=0.95)
    
    # --- METRICS CALCULATION ---
    total_papers = rem_count[0] if rem_count else 0
    total_min = times[-1] if times else 0
    total_hours = total_min / 60
    
    avg_power = sum(power_smooth) / len(power_smooth) if (has_power and power_smooth) else 0
    energy_kwh = (total_hours * avg_power) / 1000 if total_hours > 0 and avg_power > 0 else 0
    
    papers_per_hour = total_papers / total_hours if total_hours > 0 else 0
    papers_per_kwh = total_papers / energy_kwh if energy_kwh > 0 else 0

    # Add text box to plot (Upper Left)
    if has_power and power_smooth and total_hours > 0:
        textstr = '\n'.join((
            f"Total Papers: {total_papers}",
            f"Duration: {total_hours:.1f} hrs ({total_min:.0f} min)",
            f"Avg Power: {avg_power:.0f} W",
            f"Energy: {energy_kwh:.2f} kWh",
            f"Papers/Hour: {papers_per_hour:.1f}",
            f"Papers/kWh: {papers_per_kwh:.1f}"
        ))
        props = dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.85, edgecolor='gray')
        ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes, fontsize=11,
                 verticalalignment='top', bbox=props)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Saved: {output_path}")
    
    # Console Summary
    print("\n📊 Summary:")
    print(f"   📄 Papers processed: {total_papers}")
    if total_hours > 0:
        print(f"   ⏱️  Duration: {total_min:.1f} min ({total_hours:.2f} hrs)")
        print(f"   🚀 Papers per hour: {papers_per_hour:.2f}")
    if has_power and power_smooth:
        print(f"   ⚡ Avg Power: {avg_power:.1f} W")
        if total_hours > 0:
            print(f"   🔋 Total Energy: {energy_kwh:.2f} kWh")
            print(f"   🌱 Papers per kWh: {papers_per_kwh:.2f}")

# ============================================================================
# MAIN
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='Visualize power vs paper progress')
    parser.add_argument('--db', type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument('--power', type=Path, default=None)
    parser.add_argument('--no-power', action='store_true')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUTPUT_PATH)
    
    args = parser.parse_args()
    
    if args.no_power:
        power_path, has_power = None, False
    elif args.power:
        power_path, has_power = args.power, True
    else:
        power_path, has_power = DEFAULT_CSV_PATH, True
    
    if not args.db.exists(): return print(f"❌ DB not found: {args.db}")
    if has_power and power_path and not power_path.exists(): 
        return print(f"❌ Power CSV not found: {power_path}")
    
    print("📄 Loading paper timestamps...")
    paper_ts = get_paper_timestamps(args.db)
    print(f"   → {len(paper_ts)} papers found")
    if not paper_ts: return
    
    power_data = []
    if has_power and power_path:
        print("🔌 Loading power data...")
        power_data = parse_power_log(power_path)
        print(f"   → {len(power_data)} samples")
    
    remaining = build_remaining_line(power_data if has_power else [], paper_ts)
    
    print("🎨 Generating plot...")
    plot(power_data if has_power else None, remaining, args.out, has_power=has_power)

if __name__ == "__main__":
    main()