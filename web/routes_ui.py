# web/routes_ui.py
import json
import sqlite3

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from shared import config, db

from . import export_logic

ui_bp = Blueprint('ui', __name__)

# Load domain config once at module level
from shared.config import load_domain_config

domain_config = load_domain_config()
@ui_bp.route('/', methods=['GET'])
def index():
    try:
        with db.get_db() as conn:
            total_paper_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    except sqlite3.OperationalError as e:
        if "no such table: papers" in str(e) or "unable to open database file" in str(e):
            db.init_db(config.DATABASE_FILE)
            return redirect(url_for('ui.index'))
        raise

    hide_offtopic_param = request.args.get('hide_offtopic')
    year_from_param = request.args.get('year_from')
    year_to_param = request.args.get('year_to')
    min_page_count_param = request.args.get('min_page_count')

    # Deep-link support (same logic as before)
    focus_paper = request.args.get('focus_paper', '').strip() or None
    if focus_paper:
        try:
            focus_paper_row = db.get_paper_by_id(focus_paper)
            if focus_paper_row and focus_paper_row.get('year') is not None:
                focus_year = int(focus_paper_row['year'])
            else:
                focus_year = None
        except (TypeError, ValueError):
            focus_year = None
        if hide_offtopic_param is None:
            hide_offtopic_param = '0'
        if focus_year is not None:
            if year_from_param is None: year_from_param = str(focus_year)
            if year_to_param is None: year_to_param = str(focus_year)
        else:
            if year_from_param is None: year_from_param = '1800'
            if year_to_param is None: year_to_param = '2038'
        if min_page_count_param is None:
            min_page_count_param = '0'

    try:
        year_from_input_value = str(int(year_from_param)) if year_from_param is not None else str(config.DEFAULT_YEAR_FROM)
    except ValueError:
        year_from_input_value = str(config.DEFAULT_YEAR_FROM)
    try:
        year_to_input_value = str(int(year_to_param)) if year_to_param is not None else str(config.DEFAULT_YEAR_TO)
    except ValueError:
        year_to_input_value = str(config.DEFAULT_YEAR_TO)
    try:
        min_page_count_input_value = str(int(min_page_count_param)) if min_page_count_param is not None else str(config.DEFAULT_MIN_PAGE_COUNT)
    except ValueError:
        min_page_count_input_value = str(config.DEFAULT_MIN_PAGE_COUNT)

    hide_offtopic_checkbox_checked = hide_offtopic_param is None or hide_offtopic_param.lower() in ['1', 'true', 'yes', 'on']

    return render_template(
        'index.html',
        domain_config=domain_config,
        hide_offtopic=hide_offtopic_checkbox_checked,
        year_from_value=year_from_input_value,
        year_to_value=year_to_input_value,
        min_page_count_value=min_page_count_input_value,
        total_paper_count=total_paper_count,
        focus_paper=focus_paper,
        search_query_value=request.args.get('search_query', '')
    )

@ui_bp.route('/get_detail_row', methods=['GET'])
def get_detail_row():
    paper_id = request.args.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400
    try:
        paper_dict = db.get_paper_by_id(paper_id)
        if paper_dict:
            try: paper_dict['classification'] = json.loads(paper_dict['classification']) if paper_dict['classification'] else {}
            except: paper_dict['classification'] = {}
            detail_html = render_template('detail_row.html', paper=paper_dict, domain_config=domain_config)
            return jsonify({'status': 'success', 'html': detail_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
    except Exception as e:
        print(f"Error fetching detail row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch detail row'}), 500

@ui_bp.route('/get_history_row', methods=['GET'])
def get_history_row():
    paper_id = request.args.get('paper_id')
    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400
    try:
        paper = db.get_paper_by_id(paper_id)
        if paper:
            paper_dict = dict(paper)
            try: paper_dict['classification'] = json.loads(paper_dict['classification']) if paper_dict['classification'] else {}
            except: paper_dict['classification'] = {}
            try: paper_dict['main_certainty'] = json.loads(paper_dict['main_certainty']) if paper_dict['main_certainty'] else {}
            except: paper_dict['main_certainty'] = {}

            paper_dict['llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=None)
            paper_dict['set_1_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=1)
            paper_dict['set_2_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=2)
            paper_dict['set_3_llm_log_entries'] = export_logic.prepare_history_log_data(paper_dict, set_num=3)

            history_html = render_template('history_row.html', paper=paper_dict, domain_config=domain_config)
            return jsonify({'status': 'success', 'html': history_html})
        else:
            return jsonify({'status': 'error', 'message': 'Paper not found'}), 404
    except Exception as e:
        print(f"Error fetching history row for paper {paper_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to fetch history row'}), 500