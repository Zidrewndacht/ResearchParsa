# web/routes_data.py
import os
import tempfile

import requests
from flask import Blueprint, jsonify, request

from shared import config, db

from . import importer

data_bp = Blueprint('data', __name__)

@data_bp.route('/api/papers', methods=['GET'])
def api_papers():
    """Returns all papers matching server-side filters as JSON.
    This is the single data endpoint consumed by the client-side renderer."""
    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')

    hide_offtopic = True
    if hide_offtopic_param is not None:
        hide_offtopic = hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']
    try:
        year_from = int(year_from_param) if year_from_param is not None else None
    except ValueError:
        year_from = None
    try:
        year_to = int(year_to_param) if year_to_param is not None else None
    except ValueError:
        year_to = None
    try:
        min_page_count = int(min_page_count_param) if min_page_count_param is not None else None
    except ValueError:
        min_page_count = None

    papers = db.fetch_papers(
        hide_offtopic=hide_offtopic,
        year_from=year_from,
        year_to=year_to,
        min_page_count=min_page_count,
    )

    # Strip heavy blobs not needed for table rendering / filtering / stats
    slim_papers = []
    for p in papers:
        slim = {
            'id': p.get('id'),
            'type': p.get('type'),
            'title': p.get('title'),
            'authors': p.get('authors'),
            'year': p.get('year'),
            'journal': p.get('journal'),
            'pages': p.get('pages'),
            'page_count': p.get('page_count'),
            'doi': p.get('doi'),
            'issn': p.get('issn'),
            'volume': p.get('volume'),        # ADD
            'month': p.get('month'),          # ADD
            'abstract': p.get('abstract'),
            'keywords': p.get('keywords'),
            'deannualized_conference': p.get('deannualized_conference'),
            'user_trace': p.get('user_trace'),
            'changed': p.get('changed'),
            'changed_formatted': p.get('changed_formatted'),
            'changed_by': p.get('changed_by'),
            'verified': p.get('verified'),
            'verified_by': p.get('verified_by'),
            'estimated_score': p.get('estimated_score'),
            'user_override_count': p.get('user_override_count'),
            'pdf_filename': p.get('pdf_filename'),
            'pdf_state': p.get('pdf_state'),
            'classification': p.get('classification', {}),
            'main_certainty': p.get('main_certainty', {}),
        }
        slim_papers.append(slim)

    # Total count across ALL papers (unfiltered) for the footer
    try:
        with db.get_db() as conn:
            total_paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    except Exception:
        total_paper_count = len(slim_papers)

    return jsonify({
        'papers': slim_papers,
        'total_paper_count': total_paper_count,
        'loaded_count': len(slim_papers),
    })

@data_bp.route('/update_paper', methods=['POST'])
def update_paper():
    """Endpoint to handle AJAX updates (partial or full)."""
    data = request.get_json()
    paper_id = data.get('id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        # Use 'user' as the identifier for changes made via this interface
        result = db.update_paper_custom_fields(paper_id, data, changed_by="user")
        # The result dict already contains status and other data
        return jsonify(result)
    except Exception as e:
        print(f"Error updating paper {paper_id}: {e}") # Log error
        return jsonify({'status': 'error', 'message': 'Failed to update database'}), 500

@data_bp.route('/classify', methods=['POST'])
def classify_paper():
    """Endpoint to handle classification requests."""
    data = request.get_json()
    mode = data.get('mode', 'id')
    paper_id = data.get('paper_id')
    
    # Determine which queue_manager endpoint to use
    if mode == 'consensus':
        endpoint = '/consensus'
    else:
        endpoint = '/classify'
    
    # Try to call queue manager
    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}{endpoint}",
            json={'mode': mode, 'paper_id': paper_id},
            timeout=None  # No timeout for single-paper requests
        )
        if response.status_code == 200:
            response.json()
            if mode == 'id':
                # Single paper - fetch updated data and return
                updated_data = db.fetch_updated_paper_data(paper_id)
                return jsonify(updated_data)
            else:
                # Batch - return immediately
                return jsonify({'status': 'started', 'message': f'Batch classification ({mode}) initiated.'})
        else:
            return jsonify({'status': 'error', 'message': 'Queue manager returned error'}), 500
    except requests.exceptions.RequestException:
        # Queue manager unavailable
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503
    
@data_bp.route('/verify', methods=['POST'])
def verify_paper():
    """Endpoint to handle verification requests."""
    data = request.get_json()
    mode = data.get('mode', 'id')
    paper_id = data.get('paper_id')
    
    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}/verify",
            json={'mode': mode, 'paper_id': paper_id},
            timeout=None
        )
        
        if response.status_code == 200:
            response.json()
            if mode == 'id':
                updated_data = db.fetch_updated_paper_data(paper_id)
                return jsonify(updated_data)
            else:
                return jsonify({'status': 'started', 'message': f'Batch verification ({mode}) initiated.'})
        else:
            return jsonify({'status': 'error', 'message': 'Queue manager returned error'}), 500
    
    except requests.exceptions.RequestException:
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503
    
@data_bp.route('/upload_bibtex', methods=['POST'])
def upload_bibtex():
    if 'file' not in request.files: return jsonify({'status': 'error', 'message': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'status': 'error', 'message': 'No selected file'}), 400
    filename = file.filename.lower()
    
    tmp_file_path = None
    tmp_bib_path = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            tmp_file_path = tmp_file.name
            
        if filename.endswith('.bib'):
            importer.import_bibtex(tmp_file_path, config.DATABASE_FILE)
        elif filename.endswith('.csv'):
            bibtex_entries = importer.convert_csv_to_bibtex(tmp_file_path)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.bib') as tmp_bib_file:
                for entry in bibtex_entries:
                    tmp_bib_file.write(entry.encode('utf-8'))
                tmp_bib_path = tmp_bib_file.name
            importer.import_bibtex(tmp_bib_path, config.DATABASE_FILE)
        else:
            return jsonify({'status': 'error', 'message': 'Invalid file type. Please upload a .bib or .csv file.'}), 400
            
        return jsonify({'status': 'success', 'message': f'{"BibTeX" if filename.endswith(".bib") else "CSV"} file imported successfully.'})
    except Exception as e:
        print(f"Error importing file: {e}")
        return jsonify({'status': 'error', 'message': f'Import failed: {e!s}'}), 500
    finally:
        if tmp_file_path and os.path.exists(tmp_file_path):
            try: os.unlink(tmp_file_path)
            except: pass
        if tmp_bib_path and os.path.exists(tmp_bib_path):
            try: os.unlink(tmp_bib_path)
            except: pass

@data_bp.route('/review_traces', methods=['POST'])
def review_traces():
    """Proxies the trace-review request to the queue manager (which owns all LLM access)."""
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}/review_traces",
            json={'paper_id': paper_id},
            timeout=None  # No timeout for this single manual request
        )
    except requests.exceptions.RequestException:
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503

    try:
        result = response.json()
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Queue manager returned non-JSON response'}), 502

    return jsonify(result), response.status_code

@data_bp.route('/screen', methods=['POST'])
def screen_papers():
    data = request.get_json()
    mode = data.get('mode', 'remaining')
    try:
        response = requests.post(
            f"{config.QUEUE_MANAGER_URL}/screen",
            json={'mode': mode},
            timeout=None
        )
        if response.status_code == 200:
            return jsonify({'status': 'started', 'message': f'Quick screening ({mode}) initiated.'})
        # Surface the queue manager's error message (e.g. missing screening config)
        try:
            return jsonify({'status': 'error', 'message': response.json().get('error', 'Queue manager error')}), response.status_code
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Queue manager returned error'}), 500
    except requests.exceptions.RequestException:
        return jsonify({'status': 'error', 'message': 'Queue manager unavailable'}), 503