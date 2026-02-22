import json
import os

import requests
from flask import Flask, render_template, jsonify, request, send_file

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv()

from collector import DataCollector  # Load separated engine

app = Flask(__name__)
DOCS_DIR = "docs"
BINANCE_BASE_URL = "https://api.binance.com"
CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_ID = os.getenv("GIST_ID")
print("DBG : ",GIST_ID)
print("DBG : ",GIST_TOKEN)
GIT_COMMANDS_FILE = os.getenv("GIT_COMMANDS_FILE", "git_commands.md")
INSIGHTS_FILE = os.getenv("INSIGHTS_FILE", "Insights.md")


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
            return files.get(filename, {}).get('content', "No content")
        return None


def get_gist_manager():
    if not GIST_TOKEN or not GIST_ID:
        return None
    return GistManager(GIST_TOKEN, GIST_ID)

def init_system():
    if not os.path.exists(DOCS_DIR): os.makedirs(DOCS_DIR)
    # Keep existing initialization logic (e.g., flowchart.md generation)

def get_doc_content(filename):
    path = os.path.join(DOCS_DIR, filename)
    return open(path, "r", encoding="utf-8").read() if os.path.exists(path) else ""


def fetch_binance_json(path, params):
    response = requests.get(f"{BINANCE_BASE_URL}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()

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
    try:
        data = DataCollector.get_full_analysis(ticker, start, end)
        print(f"DEBUG: Ticker={ticker}, Start={start}, End={end}")
        return jsonify({"status": "SUCCESS", **data})
    except Exception as exc:
        print(f"KIS API ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": str(exc)})

@app.route('/api/save-excel')
def save_excel():
    ticker = request.args.get('ticker')
    start = request.args.get('start').replace('-', '')
    end = request.args.get('end').replace('-', '')
    try:
        output = DataCollector.generate_excel(ticker, start, end)
        return send_file(output, as_attachment=True, download_name=f"Data_{ticker}.xlsx")
    except Exception as exc:
        print(f"KIS API EXCEL ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": str(exc)}), 502


@app.route('/api/crypto-data')
def crypto_data():
    interval = request.args.get('interval', '1h')
    limit_arg = request.args.get('limit', '120')
    if interval not in {"1m", "5m", "15m", "1h", "4h", "1d"}:
        return jsonify({"status": "ERROR", "error_msg": "Unsupported interval."}), 400

    try:
        limit = int(limit_arg)
    except ValueError:
        limit = 120
    limit = max(30, min(limit, 500))

    try:
        assets = []
        for symbol in CRYPTO_SYMBOLS:
            price_json = fetch_binance_json("/api/v3/ticker/price", {"symbol": symbol})
            stat_json = fetch_binance_json("/api/v3/ticker/24hr", {"symbol": symbol})
            kline_json = fetch_binance_json(
                "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "limit": limit},
            )

            assets.append(
                {
                    "symbol": symbol,
                    "base_asset": symbol.replace("USDT", ""),
                    "current_price": float(price_json["price"]),
                    "price_change_percent_24h": float(stat_json["priceChangePercent"]),
                    "quote_volume_24h": float(stat_json["quoteVolume"]),
                    "times": [int(item[0]) for item in kline_json],
                    "closes": [float(item[4]) for item in kline_json],
                }
            )

        return jsonify(
            {
                "status": "SUCCESS",
                "interval": interval,
                "assets": assets,
                "source": "Binance Public API",
            }
        )
    except requests.RequestException as exc:
        print(f"BINANCE API ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": "Failed to call Binance API."}), 502
    except Exception as exc:
        print(f"CRYPTO ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": str(exc)}), 500

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

@app.route('/api/insights', methods=['GET', 'POST'])
def insights():
    gist_manager = get_gist_manager()
    if gist_manager is None:
        return jsonify({"status": "ERROR", "error_msg": "Missing GIST_TOKEN or GIST_ID"}), 500
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        content = payload.get("content", "")
        if gist_manager.update_md(INSIGHTS_FILE, content):
            return jsonify({"status": "SUCCESS"})
        return jsonify({"status": "ERROR", "error_msg": "Failed to update gist"}), 502
    content = gist_manager.get_md(INSIGHTS_FILE)
    if content is None:
        return jsonify({"status": "ERROR", "error_msg": "Failed to fetch gist"}), 502
    return jsonify({"status": "SUCCESS", "content": content})

if __name__ == '__main__':
    init_system()
    app.run(host='127.0.0.1', port=5002, debug=True)
