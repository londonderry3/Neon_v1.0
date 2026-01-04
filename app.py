import os
from flask import Flask, render_template, jsonify, request, send_file
from collector import DataCollector # 분리된 엔진 불러오기

app = Flask(__name__)
DOCS_DIR = "docs"
GIT_COMMANDS_DIR = "personal-dev-os"
GIT_COMMANDS_FILE = "git_commands.md"

def init_system():
    if not os.path.exists(DOCS_DIR): os.makedirs(DOCS_DIR)
    if not os.path.exists(GIT_COMMANDS_DIR): os.makedirs(GIT_COMMANDS_DIR)
    commands_path = os.path.join(GIT_COMMANDS_DIR, GIT_COMMANDS_FILE)
    if not os.path.exists(commands_path):
        with open(commands_path, "w", encoding="utf-8") as f:
            f.write("# Git Commands Log\n\n- ")
    # 기존 초기화 로직 유지 (flowchart.md 등 생성)

def get_doc_content(filename):
    path = os.path.join(DOCS_DIR, filename)
    return open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""

def read_text_file(path):
    return open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""

@app.route('/')
def index():
    all_files = sorted([f for f in os.listdir(DOCS_DIR) if f.endswith('.md')])
    contents = {f: get_doc_content(f) for f in all_files}
    md_section_files = [
        f for f in all_files
        if f not in ["flowchart.md", "project_context.md", "update_history.md"]
    ]
    return render_template('index.html', contents=contents, md_section_files=md_section_files)

@app.route('/api/chart-data')
def chart_data():
    ticker = request.args.get('ticker', '005930')
    start = request.args.get('start').replace('-', '')
    end = request.args.get('end').replace('-', '')
    data = DataCollector.get_full_analysis(ticker, start, end)
    print(f"DEBUG: Ticker={ticker}, Start={start}, End={end}")
    return jsonify({"status": "SUCCESS", **data}) if data else jsonify({"status": "ERROR", "error_msg": "No Data"})

@app.route('/api/save-excel')
def save_excel():
    ticker = request.args.get('ticker')
    start = request.args.get('start').replace('-', '')
    end = request.args.get('end').replace('-', '')
    output = DataCollector.generate_excel(ticker, start, end)
    return send_file(output, as_attachment=True, download_name=f"Data_{ticker}.xlsx")

@app.route('/api/git-commands', methods=['GET', 'POST'])
def git_commands():
    commands_path = os.path.join(GIT_COMMANDS_DIR, GIT_COMMANDS_FILE)
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        content = payload.get("content", "")
        with open(commands_path, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"status": "SUCCESS"})
    return jsonify({"status": "SUCCESS", "content": read_text_file(commands_path)})

if __name__ == '__main__':
    init_system()
    app.run(host='127.0.0.1', port=5002, debug=True)
