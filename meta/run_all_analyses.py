#!/usr/bin/env python3
"""
Master runner for the constrained agentic pipeline paper analyses.
All analysis scripts are located in the meta/ directory.
"""

import subprocess
import sys
from pathlib import Path


# ============================================================================
# PATH CONFIGURATION
# ============================================================================
# Update these paths to match your local environment and data locations.
# All generated outputs (tables, macros, charts) will be placed in OUTPUT_DIR.

OUTPUT_DIR = Path("./paper_outputs")

# --- Databases ---
S1_DB = Path("./data/paper-data/db-s1_pcb_aoi.sqlite")           # Primary domain (PCB AOI)
S2_DB = Path("./data/paper-data/db-s2_slr_sms.sqlite")           # Secondary domain (SLR/SMS)

USER_DB = Path("./data/paper-data/db.human.sqlite")             # Human-labeled subset (S3)
AI_DB   = Path("./data/paper-data/db.100.2gpu.sqlite")          # AI-classified subset (S3 -- same as 2GPU AI run)

S4_DB = Path("./data/paper-data/db-4000-after.sqlite")         # Performance benchmark (S4)

GPU1_DB = Path("./data/paper-data/db.100.1gpu.sqlite")    # 1-GPU scaling test
GPU2_DB = Path("./data/paper-data/db.100.2gpu.sqlite")    # 2-GPU scaling test

# --- Power / Sensor Logs ---
POWER_CSV_S4    = Path("./data/paper-data/csv/4000-screening+full.csv")
POWER_CSV_GPU1  = Path("./data/paper-data/csv/1GPU-100-27B-full.csv")
POWER_CSV_GPU2  = Path("./data/paper-data/csv/2GPU-100-27B-full.csv")

# --- Optional: Domain Configs ---
# Leave as None if your domain_config.yaml files are located next to the DBs
# or in the current working directory (the scripts will auto-resolve them).
S1_CONFIG = Path("./data/paper-data/config/s1s3-pcba-domain_config.yaml")
S2_CONFIG = Path("./data/paper-data/config/s2-slr-domain_config.yaml")
S3_CONFIG = Path("./data/paper-data/config/s1s3-pcba-domain_config.yaml")

# --- Optional: GPU Batch Size Ratio ---
# If you measured a specific max-batch-size ratio for the GPU comparison, 
# set it here (e.g., 5.0). Otherwise, leave as None.
GPU_BATCH_SIZE_RATIO = None

# ============================================================================
# EXECUTION LOGIC
# ============================================================================

def run_cmd(cmd: list, description: str):
    """Execute a subprocess command with formatted console output."""
    print(f"\n{'='*70}")
    print(f"▶ {description}")
    print(f"  Command: {' '.join(str(c) for c in cmd)}")
    print(f"{'='*70}")
    
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print(f"\n❌ FAILED: {description}")
        print("Aborting pipeline. Please check the error messages above.")
        sys.exit(result.returncode)
        
    print(f"✅ SUCCESS: {description}\n")


def main():
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📂 All outputs will be saved to: {OUTPUT_DIR.resolve()}")

    # 1. S1: 3-Run Agreement Analysis
    cmd_s1 = [
        sys.executable, "meta/agreement_3sets_cli_v1.4.py",
        "--db", S1_DB,
        "-o", OUTPUT_DIR / "agreement_3run_results"
    ]
    if S1_CONFIG: cmd_s1.extend(["--config", S1_CONFIG])
    run_cmd(cmd_s1, "S1: 3-Run Agreement Analysis (PCB AOI)")

    # 2. S3: Human-AI Alignment
    cmd_s3 = [
        sys.executable, "meta/agreement_human_cli_v1.4.py",
        "--user-db", USER_DB,
        "--ai-db", AI_DB,
        "-o", OUTPUT_DIR / "human_ai_alignment_table.tex"
    ]
    if S3_CONFIG: cmd_s3.extend(["--config", S3_CONFIG])
    run_cmd(cmd_s3, "S3: Human-AI Alignment Analysis")

    # 3. S1 vs S2: Cross-Domain Comparison
    cmd_xdom = [
        sys.executable, "meta/agreement_cross_domain_cli.py",
        "--db1", S1_DB,
        "--db2", S2_DB,
        "-o", OUTPUT_DIR / "cross_domain_results"
    ]
    if S1_CONFIG: cmd_xdom.extend(["--config1", S1_CONFIG])
    if S2_CONFIG: cmd_xdom.extend(["--config2", S2_CONFIG])
    run_cmd(cmd_xdom, "Cross-Domain Comparison (S1 vs S2)")

    # 4. S4: Time & Power Charts
    cmd_s4 = [
        sys.executable, "meta/time_power_charts.py",
        "--db", S4_DB,
        "--power", POWER_CSV_S4,
        "--out", OUTPUT_DIR / "consensus_progress.png",
        "--out-tex", OUTPUT_DIR / "consensus_metrics.tex",
        "--out-macros", OUTPUT_DIR / "consensus_metrics_macros.tex"
    ]
    run_cmd(cmd_s4, "S4: Time, Power, and Throughput Metrics")

    # 5. GPU Comparison (1 vs 2 GPUs)
    cmd_gpu = [
        sys.executable, "meta/gpu_comparison.py", 
        "--db1", GPU1_DB,
        "--power1", POWER_CSV_GPU1,
        "--db2", GPU2_DB,
        "--power2", POWER_CSV_GPU2,
        "--out-chart", OUTPUT_DIR / "gpu_comparison_chart.png",
        "--out-tex", OUTPUT_DIR / "gpu_comparison_table.tex",
        "--out-macros", OUTPUT_DIR / "gpu_comparison_macros.tex"
    ]
    if GPU_BATCH_SIZE_RATIO is not None:
        cmd_gpu.extend(["--batch-size-ratio", str(GPU_BATCH_SIZE_RATIO)])
    run_cmd(cmd_gpu, "GPU Comparison (1 vs 2 GPUs)")

    # ========================================================================
    # CONSOLIDATE MACROS INTO A SINGLE FILE
    # ========================================================================
    print("\n" + "="*70)
    print("📝 Consolidating all macros into a single file...")
    
    macro_files = [
        OUTPUT_DIR / "agreement_3run_results_macros.tex",
        OUTPUT_DIR / "human_ai_alignment_table_macros.tex",
        OUTPUT_DIR / "cross_domain_results_macros.tex",
        OUTPUT_DIR / "consensus_metrics_macros.tex",
        OUTPUT_DIR / "gpu_comparison_macros.tex",
    ]
    
    combined_macros_path = OUTPUT_DIR / "all_macros.tex"
    with open(combined_macros_path, "w", encoding="utf-8") as out_f:
        out_f.write("% ==========================================\n")
        out_f.write("% CONSOLIDATED MACROS FILE\n")
        out_f.write("% Generated by run_all_analyses.py\n")
        out_f.write("% ==========================================\n\n")
        
        for mf in macro_files:
            if mf.exists():
                out_f.write(f"% --- Source: {mf.name} ---\n")
                out_f.write(mf.read_text(encoding="utf-8"))
                out_f.write("\n\n")
            else:
                out_f.write(f"% WARNING: {mf.name} not found!\n\n")
                
    print(f"✅ All macros combined into: {combined_macros_path}")

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "="*70)
    print("🎉 ALL ANALYSES COMPLETED SUCCESSFULLY!")
    print(f"📂 Outputs are located in: {OUTPUT_DIR.resolve()}")
    print("="*70)
    
    print("\n📝 NEXT STEPS FOR LATEX:")
    print("Include the single consolidated macros file in your main .tex:")
    print("-" * 70)
    print(f"\\input{{{combined_macros_path}}}")
    print("-" * 70)


if __name__ == "__main__":
    main()