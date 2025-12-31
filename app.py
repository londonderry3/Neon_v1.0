import os
from flask import Flask, render_template, jsonify, request, send_file
from collector import DataCollector # 분리된 엔진 불러오기

app = Flask(__name__)
DOCS_DIR = "docs"

def init_system():
    if not os.path.exists(DOCS_DIR): os.makedirs(DOCS_DIR)
    # 기존 초기화 로직 유지 (flowchart.md 등 생성)

def get_doc_content(filename):
    path = os.path.join(DOCS_DIR, filename)
    return open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""

@app.route('/')
def index():
    all_files = sorted([f for f in os.listdir(DOCS_DIR) if f.endswith('.md')])
    contents = {f: get_doc_content(f) for f in all_files}
    md_section_files = [f for f in all_files if f not in ["flowchart.md", "project_context.md"]]
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

if __name__ == '__main__':
    init_system()
    app.run(host='127.0.0.1', port=5002, debug=True)