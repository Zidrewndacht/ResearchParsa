# fix_bogus_screening_blobs.py
import os
import sys
import shutil
import sqlite3
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import config, db

def main():
    db_path = config.DATABASE_FILE
    print(f"Target database: {db_path}")
    
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    # STEP 1: MANDATORY SAFETY BACKUP
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup_before_repair_{timestamp}"
    print(f"Creating safety backup: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print("✅ Safety backup created. If anything goes wrong, restore from this file.\n")

    db.init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, title, 
               set_1_llm, set_1_llm_log, 
               set_2_llm, set_2_llm_log, 
               set_3_llm, set_3_llm_log 
        FROM papers
    """)
    papers = cursor.fetchall()
    
    total = len(papers)
    print(f"Scanning {total} papers for bogus on-topic screening blobs...\n")
    
    fixed_papers = []
    
    for row in papers:
        paper_id = row['id']
        if paper_id == '1' and 'Database is missing' in (row.get('title') or ''):
            continue
            
        updates = {}
        for set_num in [1, 2, 3]:
            blob_raw = row[f'set_{set_num}_llm']
            log_raw = row[f'set_{set_num}_llm_log']
            
            # If the blob is already NULL or empty, nothing to fix here
            if not blob_raw or blob_raw.strip() in ('', '{}'):
                continue
                
            try:
                log_entries = json.loads(log_raw) if log_raw else []
            except Exception:
                log_entries = []
                
            # 1. Is there a valid full classification?
            has_valid_classification = any(
                entry.get('type') in ('classifier', 'consensus') and entry.get('valid') is True
                for entry in log_entries
            )
            if has_valid_classification:
                continue # Legitimate full classification, skip
                
            # 2. Is there a screener entry?
            screener_entries = [
                entry for entry in log_entries 
                if entry.get('type') == 'screener' and entry.get('valid') is True
            ]
            if not screener_entries:
                continue # No screener, no classifier. Skip.
                
            # 3. We have a blob, and the only valid log is a screener.
            # This means the screener wrote the blob.
            # Check what the screener actually said in its output.
            screener_said_offtopic = False
            for entry in screener_entries:
                output = entry.get('output', {})
                if isinstance(output, str):
                    try: output = json.loads(output)
                    except: output = {}
                
                if isinstance(output, dict) and output.get('is_offtopic') is True:
                    screener_said_offtopic = True
                    break
            
            if screener_said_offtopic:
                continue # Legitimate off-topic screening. DO NOT TOUCH.
                
            # 4. THE BUG: Screener wrote a blob, but did NOT say is_offtopic=true.
            # This is a bogus on-topic blob. Nuke the blob to force re-classification.
            # We keep the log so /screen knows it was screened, but /consensus will 
            # pick it up because set_N_llm is NULL.
            updates[f'set_{set_num}_llm'] = None
            print(f"  [Paper {paper_id} Set {set_num}] Bogus on-topic screening blob found. Clearing blob.")
                
        if updates:
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [paper_id]
            cursor.execute(f"UPDATE papers SET {set_clause} WHERE id = ?", values)
            fixed_papers.append(paper_id)
            
    conn.commit()
    conn.close()
    
    print(f"\n✅ Cleared bogus blobs in {len(fixed_papers)} papers.")
    
    if fixed_papers:
        print("👉 Recalculating main classifications for affected papers...")
        for pid in fixed_papers:
            db.recalculate_main_set(pid, changed_by="Script_Fix_Bogus_Screening", create_log_entry=False)
        print(f"✅ Recalculated {len(fixed_papers)} papers.")
        print("\n👉 NEXT STEP: Run '/consensus' from the frontend.")
        print("   The gate will see these sets as NULL and run the full pipeline.")
    else:
        print("✅ No bogus screened sets found. Database is clean.")

if __name__ == '__main__':
    main()