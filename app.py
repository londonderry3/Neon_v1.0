import json
import os

import requests
from flask import Flask, render_template, jsonify, request, send_file

from dotenv import load_dotenv
load_dotenv()

from collector import DataCollector # 분리된 엔진 불러오기

app = Flask(__name__)
DOCS_DIR = "docs"
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_ID = os.getenv("GIST_ID")
print("DBG : ",GIST_ID)
print("DBG : ",GIST_TOKEN)
GIT_COMMANDS_FILE = os.getenv("GIT_COMMANDS_FILE", "git_commands.md")


class GistManager:
    def __init__(self, token, gist_id):
        self.token = token
        self.gist_id = gist_id
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def update_md(self, filename, content):
        url = f"https://api.github.com/gists/{self.gist_id}"
        data = {
            "files": {
                filename: {"content": content}
            }
        }
        response = requests.patch(url, headers=self.headers, data=json.dumps(data), timeout=10)
        return response.status_code == 200

    def get_md(self, filename):
        url = f"https://api.github.com/gists/{self.gist_id}"
        response = requests.get(url, headers=self.headers, timeout=10)
        if response.status_code == 200:
            files = response.json().get('files', {})
            return files.get(filename, {}).get('content', "내용 없음")
        return None


def get_gist_manager():
    if not GIST_TOKEN or not GIST_ID:
        return None
    return GistManager(GIST_TOKEN, GIST_ID)

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

@app.route('/api/git-commands', methods=['GET', 'POST'])
def git_commands():
    gist_manager = get_gist_manager()
    if gist_manager is None:
        return jsonify({"status": "ERROR", "error_msg": "Missing GIST_TOKEN or GIST_ID"}), 500
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        content = payload.get("content", "")
        if gist_manager.update_md(GIT_COMMANDS_FILE, content):
            return jsonify({"status": "SUCCESS"})
        return jsonify({"status": "ERROR", "error_msg": "Failed to update gist"}), 502
    content = gist_manager.get_md(GIT_COMMANDS_FILE)
    if content is None:
        return jsonify({"status": "ERROR", "error_msg": "Failed to fetch gist"}), 502
    return jsonify({"status": "SUCCESS", "content": content})

if __name__ == '__main__':
    init_system()
    app.run(host='127.0.0.1', port=5002, debug=True)
