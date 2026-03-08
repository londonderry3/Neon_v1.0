import json
import os
import sqlite3
import time
from bisect import bisect_right
import math
from pathlib import Path

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
BINANCE_FUTURES_BASE_URL = "https://fapi.binance.com"
CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CRYPTO_CACHE_DB = os.getenv("CRYPTO_CACHE_DB", "analysis/crypto_cache.db")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_ID = os.getenv("GIST_ID")
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


def gist_config_missing_response():
    return (
        jsonify(
            {
                "status": "ERROR",
                "error_code": "GIST_CONFIG_MISSING",
                "error_msg": "Gist integration is not configured. Set GIST_TOKEN and GIST_ID in .env and restart the server.",
            }
        ),
        500,
    )


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


def fetch_binance_futures_json(path, params):
    response = requests.get(f"{BINANCE_FUTURES_BASE_URL}{path}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def interval_to_ms(interval):
    mapping = {
        "1m": 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "8h": 8 * 60 * 60 * 1000,
        "24h": 24 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
        "1w": 7 * 24 * 60 * 60 * 1000,
        "1M": 30 * 24 * 60 * 60 * 1000,
    }
    if interval not in mapping:
        raise ValueError(f"Unsupported interval: {interval}")
    return mapping[interval]


def get_cache_conn():
    db_path = Path(CRYPTO_CACHE_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ohlcv_cache (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            close_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            PRIMARY KEY (symbol, interval, open_time)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS funding_cache (
            symbol TEXT NOT NULL,
            funding_time INTEGER NOT NULL,
            funding_rate REAL NOT NULL,
            PRIMARY KEY (symbol, funding_time)
        )
        """
    )
    return conn


def upsert_ohlcv_cache(conn, symbol, interval, klines):
    if not klines:
        return
    rows = [
        (
            symbol,
            interval,
            int(k[0]),
            int(k[6]),
            float(k[1]),
            float(k[2]),
            float(k[3]),
            float(k[4]),
            float(k[5]),
        )
        for k in klines
    ]
    conn.executemany(
        """
        INSERT INTO ohlcv_cache(symbol, interval, open_time, close_time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
            close_time=excluded.close_time,
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume
        """,
        rows,
    )


def load_ohlcv_cache(conn, symbol, interval, start_ms, end_ms):
    cursor = conn.execute(
        """
        SELECT open_time, open, high, low, close, volume, close_time
        FROM ohlcv_cache
        WHERE symbol=? AND interval=? AND open_time BETWEEN ? AND ?
        ORDER BY open_time ASC
        """,
        (symbol, interval, int(start_ms), int(end_ms)),
    )
    return [list(row) for row in cursor.fetchall()]


def upsert_funding_cache(conn, symbol, funding_items):
    if not funding_items:
        return
    rows = [(symbol, int(item["fundingTime"]), float(item["fundingRate"])) for item in funding_items]
    conn.executemany(
        """
        INSERT INTO funding_cache(symbol, funding_time, funding_rate)
        VALUES (?, ?, ?)
        ON CONFLICT(symbol, funding_time) DO UPDATE SET
            funding_rate=excluded.funding_rate
        """,
        rows,
    )


def load_funding_cache(conn, symbol, start_ms, end_ms):
    cursor = conn.execute(
        """
        SELECT funding_time, funding_rate
        FROM funding_cache
        WHERE symbol=? AND funding_time BETWEEN ? AND ?
        ORDER BY funding_time ASC
        """,
        (symbol, int(start_ms), int(end_ms)),
    )
    return [{"fundingTime": int(row[0]), "fundingRate": str(row[1])} for row in cursor.fetchall()]


def fetch_funding_segment_paginated(symbol, start_ms, end_ms):
    all_items = []
    cursor_ms = int(start_ms)
    end_ms = int(end_ms)
    max_loops = 40
    loops = 0
    while cursor_ms <= end_ms and loops < max_loops:
        loops += 1
        batch = fetch_binance_futures_json(
            "/fapi/v1/fundingRate",
            {"symbol": symbol, "startTime": cursor_ms, "endTime": end_ms, "limit": 1000},
        )
        if not batch:
            break
        all_items.extend(batch)
        last_time = int(batch[-1]["fundingTime"])
        if len(batch) < 1000 or last_time >= end_ms:
            break
        cursor_ms = last_time + 1
    return all_items


def normalize_analysis_interval(interval):
    return "1d" if interval == "24h" else interval


def fetch_klines_segment(symbol, interval, start_ms, end_ms):
    normalized_interval = normalize_analysis_interval(interval)
    step_ms = interval_to_ms(normalized_interval)
    all_rows = []
    cursor_ms = int(start_ms)
    end_ms = int(end_ms)
    estimated_loops = math.ceil(max(0, end_ms - cursor_ms) / (step_ms * 1000)) + 5
    max_loops = max(40, estimated_loops)
    loops = 0
    while cursor_ms <= end_ms and loops < max_loops:
        loops += 1
        batch_end = min(end_ms, cursor_ms + step_ms * 999)
        batch = fetch_binance_json(
            "/api/v3/klines",
            {"symbol": symbol, "interval": normalized_interval, "startTime": cursor_ms, "endTime": batch_end, "limit": 1000},
        )
        if not batch:
            break
        all_rows.extend(batch)
        last_open = int(batch[-1][0])
        if len(batch) < 1000 or last_open >= end_ms:
            break
        cursor_ms = last_open + step_ms
    return all_rows


def choose_analysis_price_interval(display_interval, display_limit, max_points=12000):
    return "8h"


def estimate_limit_for_window(display_interval, display_limit, target_interval):
    window_ms = interval_to_ms(display_interval) * max(1, int(display_limit))
    return max(30, math.ceil(window_ms / interval_to_ms(target_interval)) + 4)


def fetch_ohlcv_with_cache(symbol, interval, limit):
    normalized_interval = normalize_analysis_interval(interval)
    step_ms = interval_to_ms(normalized_interval)
    now_ms = int(time.time() * 1000)
    end_ms = now_ms
    start_ms = end_ms - step_ms * (limit + 2)

    with get_cache_conn() as conn:
        cached = load_ohlcv_cache(conn, symbol, normalized_interval, start_ms, end_ms)
        if not cached:
            fetched = fetch_klines_segment(symbol, normalized_interval, start_ms, end_ms)
            upsert_ohlcv_cache(conn, symbol, normalized_interval, fetched)
        else:
            cached_times = [int(row[0]) for row in cached]
            min_cached = min(cached_times)
            max_cached = max(cached_times)
            if start_ms < min_cached:
                fetched_left = fetch_klines_segment(symbol, normalized_interval, start_ms, min_cached - step_ms)
                upsert_ohlcv_cache(conn, symbol, normalized_interval, fetched_left)
            if max_cached + step_ms <= end_ms:
                fetched_right = fetch_klines_segment(symbol, normalized_interval, max_cached + step_ms, end_ms)
                upsert_ohlcv_cache(conn, symbol, normalized_interval, fetched_right)

        rows = load_ohlcv_cache(conn, symbol, normalized_interval, start_ms, end_ms)
        return rows[-limit:] if len(rows) > limit else rows


def fetch_funding_history(symbol, start_time_ms, end_time_ms):
    with get_cache_conn() as conn:
        cached = load_funding_cache(conn, symbol, start_time_ms, end_time_ms)
        if not cached:
            batch = fetch_funding_segment_paginated(symbol, start_time_ms, end_time_ms)
            upsert_funding_cache(conn, symbol, batch)
            return load_funding_cache(conn, symbol, start_time_ms, end_time_ms)

        cached_times = [int(item["fundingTime"]) for item in cached]
        min_cached = min(cached_times)
        max_cached = max(cached_times)
        funding_step = 8 * 60 * 60 * 1000

        if start_time_ms < min_cached:
            left_batch = fetch_funding_segment_paginated(
                symbol,
                start_time_ms,
                max(start_time_ms, min_cached - funding_step),
            )
            upsert_funding_cache(conn, symbol, left_batch)
        if max_cached + funding_step <= end_time_ms:
            right_batch = fetch_funding_segment_paginated(
                symbol,
                max_cached + funding_step,
                end_time_ms,
            )
            upsert_funding_cache(conn, symbol, right_batch)

        return load_funding_cache(conn, symbol, start_time_ms, end_time_ms)


def aggregate_funding_points(funding_items, interval):
    points = [(int(item["fundingTime"]), float(item["fundingRate"]) * 100) for item in funding_items]
    if not points:
        return [], [], "raw"

    # Binance funding-rate endpoint provides 8h cadence at best.
    # Keep raw points for all intervals to preserve maximum available resolution.
    grouped = sorted(points, key=lambda x: x[0])
    resolution = "raw_8h"

    return [ts for ts, _ in grouped], [rate for _, rate in grouped], resolution


def align_price_to_indicator(price_times, price_values, indicator_times):
    aligned_prices = []
    aligned_indicators = []
    for ind_time, ind_value in indicator_times:
        idx = bisect_right(price_times, ind_time) - 1
        if idx < 0 or idx >= len(price_values):
            continue
        aligned_prices.append(price_values[idx])
        aligned_indicators.append(ind_value)
    return aligned_prices, aligned_indicators


def expand_indicator_to_price_times(price_times, price_values, indicator_pairs):
    if not price_times or not price_values or not indicator_pairs:
        return [], [], []

    indicator_pairs = sorted(indicator_pairs, key=lambda x: x[0])
    indicator_times = [ts for ts, _ in indicator_pairs]
    indicator_values = [val for _, val in indicator_pairs]

    expanded_times = []
    expanded_prices = []
    expanded_indicator = []
    for ts, price in zip(price_times, price_values):
        idx = bisect_right(indicator_times, ts) - 1
        if idx < 0:
            continue
        expanded_times.append(ts)
        expanded_prices.append(price)
        expanded_indicator.append(indicator_values[idx])
    return expanded_times, expanded_prices, expanded_indicator


def pearson_corr(values_a, values_b):
    n = min(len(values_a), len(values_b))
    if n < 2:
        return None
    a = values_a[:n]
    b = values_b[:n]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return None
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    return cov / ((var_a ** 0.5) * (var_b ** 0.5))


def median_step_ms(times_ms):
    if len(times_ms) < 2:
        return None
    diffs = sorted(max(1, b - a) for a, b in zip(times_ms[:-1], times_ms[1:]))
    return diffs[len(diffs) // 2]


def slice_by_lag(series_a, series_b, lag_steps):
    n = min(len(series_a), len(series_b))
    if n < 3:
        return [], []
    a = series_a[:n]
    b = series_b[:n]
    if lag_steps > 0:
        return a[lag_steps:], b[:-lag_steps]
    if lag_steps < 0:
        return a[:lag_steps], b[-lag_steps:]
    return a, b


def cross_correlation_analysis(price_values, indicator_values, step_ms):
    n = min(len(price_values), len(indicator_values))
    if n < 8:
        return {
            "best_corr": None,
            "best_lag_steps": 0,
            "best_lag_ms": None,
            "samples": n,
            "sweep": {"lag_steps": [], "lag_ms": [], "values": []},
        }
    max_lag = min(max(1, n // 3), 24)
    best = {"corr_abs": -1, "corr": None, "lag": 0, "samples": 0}
    lag_steps = []
    lag_ms_list = []
    sweep_values = []
    for lag in range(-max_lag, max_lag + 1):
        a, b = slice_by_lag(price_values, indicator_values, lag)
        if len(a) < 6:
            continue
        corr = pearson_corr(a, b)
        if corr is None:
            continue
        lag_steps.append(lag)
        lag_ms_list.append((lag * step_ms) if step_ms is not None else None)
        sweep_values.append(corr)
        if lag >= 0:
            continue
        if abs(corr) > best["corr_abs"]:
            best = {"corr_abs": abs(corr), "corr": corr, "lag": lag, "samples": len(a)}
    if best["corr"] is None:
        return {
            "best_corr": None,
            "best_lag_steps": None,
            "best_lag_ms": None,
            "samples": n,
            "sweep": {"lag_steps": lag_steps, "lag_ms": lag_ms_list, "values": sweep_values},
        }
    best_lag_ms = (best["lag"] * step_ms) if step_ms is not None else None
    return {
        "best_corr": best["corr"],
        "best_lag_steps": best["lag"],
        "best_lag_ms": best_lag_ms,
        "samples": best["samples"],
        "sweep": {"lag_steps": lag_steps, "lag_ms": lag_ms_list, "values": sweep_values},
    }


def shannon_entropy(discrete_values):
    total = len(discrete_values)
    if total == 0:
        return 0.0
    freq = {}
    for v in discrete_values:
        freq[v] = freq.get(v, 0) + 1
    entropy = 0.0
    for cnt in freq.values():
        p = cnt / total
        entropy -= p * __import__("math").log(max(p, 1e-12))
    return entropy


def discretize_to_quantile_bins(values, bins=10):
    n = len(values)
    if n == 0:
        return []
    ordered = sorted((v, i) for i, v in enumerate(values))
    out = [0] * n
    for rank, (_, idx) in enumerate(ordered):
        out[idx] = min(bins - 1, (rank * bins) // n)
    return out


def mutual_information(discrete_a, discrete_b):
    n = min(len(discrete_a), len(discrete_b))
    if n == 0:
        return 0.0
    a = discrete_a[:n]
    b = discrete_b[:n]
    joint = {}
    freq_a = {}
    freq_b = {}
    for x, y in zip(a, b):
        joint[(x, y)] = joint.get((x, y), 0) + 1
        freq_a[x] = freq_a.get(x, 0) + 1
        freq_b[y] = freq_b.get(y, 0) + 1
    mi = 0.0
    for (x, y), cnt in joint.items():
        pxy = cnt / n
        px = freq_a[x] / n
        py = freq_b[y] / n
        mi += pxy * __import__("math").log(max(pxy / max(px * py, 1e-12), 1e-12))
    return mi


def delayed_mutual_information_analysis(price_values, indicator_values, step_ms):
    n = min(len(price_values), len(indicator_values))
    if n < 8:
        return {
            "best_mi": None,
            "best_lag_steps": 0,
            "best_lag_ms": None,
            "samples": n,
            "sweep": {"lag_steps": [], "lag_ms": [], "values": []},
        }
    max_lag = min(max(1, n // 3), 24)
    price_disc = discretize_to_quantile_bins(price_values)
    ind_disc = discretize_to_quantile_bins(indicator_values)
    best = {"mi": -1.0, "lag": 0, "samples": 0}
    lag_steps = []
    lag_ms_list = []
    sweep_values = []
    for lag in range(-max_lag, max_lag + 1):
        a, b = slice_by_lag(price_disc, ind_disc, lag)
        if len(a) < 6:
            continue
        mi = mutual_information(a, b)
        h_a = shannon_entropy(a)
        h_b = shannon_entropy(b)
        norm = min(h_a, h_b)
        nmi = mi / norm if norm > 0 else 0.0
        lag_steps.append(lag)
        lag_ms_list.append((lag * step_ms) if step_ms is not None else None)
        sweep_values.append(nmi)
        if lag >= 0:
            continue
        if nmi > best["mi"]:
            best = {"mi": nmi, "lag": lag, "samples": len(a)}
    if best["mi"] < 0:
        return {
            "best_mi": None,
            "best_lag_steps": None,
            "best_lag_ms": None,
            "samples": n,
            "sweep": {"lag_steps": lag_steps, "lag_ms": lag_ms_list, "values": sweep_values},
        }
    best_lag_ms = (best["lag"] * step_ms) if step_ms is not None else None
    return {
        "best_mi": (best["mi"] if best["mi"] >= 0 else None),
        "best_lag_steps": best["lag"],
        "best_lag_ms": best_lag_ms,
        "samples": best["samples"],
        "sweep": {"lag_steps": lag_steps, "lag_ms": lag_ms_list, "values": sweep_values},
    }


def granger_causality_analysis(price_values, indicator_values):
    n = min(len(price_values), len(indicator_values))
    def _unavailable(reason):
        return {
            "best_pvalue": None,
            "best_lag_steps": None,
            "samples": n,
            "available": False,
            "reason": reason,
            "sweep": {"lag_steps": [], "values": []},
        }

    if n < 24:
        return _unavailable("insufficient_samples")
    try:
        import numpy as np  # type: ignore
        from statsmodels.tsa.stattools import grangercausalitytests  # type: ignore
    except Exception as exc:
        return _unavailable(f"statsmodels_import_error: {exc}")

    max_lag = min(12, max(1, n // 5))
    data = np.column_stack([price_values[:n], indicator_values[:n]])
    try:
        result = grangercausalitytests(data, maxlag=max_lag, verbose=False)
    except Exception as exc:
        return _unavailable(f"granger_compute_error: {exc}")

    best_p = None
    best_lag = None
    sweep_lags = []
    sweep_vals = []
    for lag, tests in result.items():
        p_val = float(tests[0]["ssr_ftest"][1])
        sweep_lags.append(int(lag))
        sweep_vals.append(p_val)
        if best_p is None or p_val < best_p:
            best_p = p_val
            best_lag = int(lag)
    return {
        "best_pvalue": best_p,
        "best_lag_steps": best_lag,
        "samples": n,
        "available": True,
        "reason": None,
        "sweep": {"lag_steps": sweep_lags, "values": sweep_vals},
    }


def calc_max_drawdown(equity_curve):
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    mdd = 0.0
    for val in equity_curve:
        peak = max(peak, val)
        if peak <= 0:
            continue
        drawdown = (val / peak) - 1.0
        mdd = min(mdd, drawdown)
    return mdd


def compute_cagr(equity_start, equity_end, years):
    if equity_start <= 0 or equity_end <= 0 or years <= 0:
        return None
    return (equity_end / equity_start) ** (1.0 / years) - 1.0


def compute_sharpe(period_returns, periods_per_year):
    n = len(period_returns)
    if n < 2 or periods_per_year <= 0:
        return None
    mean_r = sum(period_returns) / n
    var = sum((r - mean_r) ** 2 for r in period_returns) / (n - 1)
    std = math.sqrt(max(var, 0.0))
    if std == 0:
        return None
    return (mean_r / std) * math.sqrt(periods_per_year)


def estimate_periods_per_year(step_ms):
    if step_ms is None or step_ms <= 0:
        return 365.0
    year_ms = 365.25 * 24 * 60 * 60 * 1000
    return year_ms / step_ms


def years_between(times_ms):
    if len(times_ms) < 2:
        return 0.0
    delta_ms = max(0, times_ms[-1] - times_ms[0])
    return delta_ms / (365.25 * 24 * 60 * 60 * 1000)


def simulate_strategy(
    prices,
    indicator,
    lag_steps,
    direction,
    fee_rate=0.001,
    slippage_rate=0.0005,
    indicator_history=None,
):
    n = min(len(prices), len(indicator))
    if n < 3:
        return {
            "equity_curve": [1.0] * n,
            "period_returns": [],
            "win_rate": None,
            "cumulative_return": 0.0,
        }

    equity = 1.0
    equity_curve = [equity]
    period_returns = []
    prev_position = 0

    history = indicator_history or []
    history_len = len(history)
    for t in range(1, n):
        signal_idx = t - lag_steps
        if signal_idx < 0:
            hist_idx = history_len + signal_idx
            if 0 <= hist_idx < history_len:
                raw = history[hist_idx]
                base_pos = 1 if raw > 0 else (-1 if raw < 0 else 0)
                position = base_pos * direction
            else:
                position = 0
        elif signal_idx >= n:
            position = 0
        else:
            raw = indicator[signal_idx]
            base_pos = 1 if raw > 0 else (-1 if raw < 0 else 0)
            position = base_pos * direction

        turnover = abs(position - prev_position)
        if turnover > 0:
            cost = turnover * (fee_rate + slippage_rate)
            equity *= max(0.0, 1.0 - cost)

        step_ret = (prices[t] / prices[t - 1]) - 1.0
        strat_ret = position * step_ret
        equity *= (1.0 + strat_ret)
        period_returns.append(strat_ret)
        equity_curve.append(equity)
        prev_position = position

    wins = [r for r in period_returns if r > 0]
    win_rate = (len(wins) / len(period_returns)) if period_returns else None
    return {
        "equity_curve": equity_curve,
        "period_returns": period_returns,
        "win_rate": win_rate,
        "cumulative_return": (equity_curve[-1] - 1.0) if equity_curve else 0.0,
    }


def simulate_buy_and_hold(prices):
    if not prices:
        return {"equity_curve": [], "period_returns": [], "cumulative_return": 0.0}
    equity = 1.0
    equity_curve = [equity]
    period_returns = []
    for t in range(1, len(prices)):
        ret = (prices[t] / prices[t - 1]) - 1.0
        equity *= (1.0 + ret)
        period_returns.append(ret)
        equity_curve.append(equity)
    return {
        "equity_curve": equity_curve,
        "period_returns": period_returns,
        "cumulative_return": (equity_curve[-1] - 1.0) if equity_curve else 0.0,
    }


def find_best_lag_sharpe(prices, indicator, periods_per_year, max_lag=24, allow_zero=False):
    n = min(len(prices), len(indicator))
    if n < 24:
        return {"lag_steps": 0, "direction": 1, "score": None, "metric": "is_sharpe"}
    best = {"lag_steps": 0, "direction": 1, "score": -10**9, "metric": "is_sharpe"}
    max_lag = min(max_lag, max(1, n // 3))
    # Backtest must be causal: only use past indicator values (lag > 0 here).
    start_lag = 0 if allow_zero else 1
    for lag in range(start_lag, max_lag + 1):
        a, b = slice_by_lag(prices, indicator, lag)
        if len(a) < 16:
            continue
        corr = pearson_corr(a, b)
        if corr is None:
            continue
        direction = 1 if corr >= 0 else -1
        sim = simulate_strategy(prices, indicator, lag, direction)
        score = compute_sharpe(sim["period_returns"], periods_per_year)
        if score is None:
            continue
        if score > best["score"]:
            best = {"lag_steps": lag, "direction": direction, "score": score}
    if best["score"] == -10**9:
        return {"lag_steps": 0, "direction": 1, "score": None, "metric": "is_sharpe"}
    best["metric"] = "is_sharpe"
    return best


def find_best_lag_is(prices, indicator, periods_per_year, max_lag=24):
    return find_best_lag_sharpe(prices, indicator, periods_per_year, max_lag=max_lag, allow_zero=False)


def build_strategy_indicator(indicator, window=12):
    n = len(indicator)
    if n < 3:
        return list(indicator)

    w = max(3, min(window, max(3, n // 6)))
    prefix = [0.0]
    for val in indicator:
        prefix.append(prefix[-1] + float(val))

    centered = []
    for i in range(n):
        left = max(0, i - w + 1)
        count = i - left + 1
        mean = (prefix[i + 1] - prefix[left]) / count
        centered.append(float(indicator[i]) - mean)

    pos = sum(1 for v in centered if v > 0)
    neg = sum(1 for v in centered if v < 0)
    if pos == 0 or neg == 0:
        # If still one-sided, switch to first-difference signal.
        diff = [0.0]
        for i in range(1, n):
            diff.append(float(indicator[i]) - float(indicator[i - 1]))
        return diff
    return centered


def kalman_filter_series(values, process_var=None, measurement_var=None):
    n = len(values)
    if n == 0:
        return {"filtered": [], "predicted": [], "variances": []}

    if n == 1:
        only = float(values[0])
        return {"filtered": [only], "predicted": [only], "variances": [1.0]}

    diffs = [float(values[i]) - float(values[i - 1]) for i in range(1, n)]
    diff_var = sum(d * d for d in diffs) / max(1, len(diffs))
    mean_v = sum(float(v) for v in values) / n
    obs_var = sum((float(v) - mean_v) ** 2 for v in values) / max(1, n - 1)

    q = process_var if process_var is not None else max(diff_var * 0.05, 1e-8)
    r = measurement_var if measurement_var is not None else max(obs_var * 0.25, 1e-8)

    x = float(values[0])
    p = max(obs_var, r, 1.0)
    filtered = [x]
    predicted = [x]
    variances = [p]

    for idx in range(1, n):
        x_pred = x
        p_pred = p + q
        z = float(values[idx])
        gain = p_pred / (p_pred + r)
        x = x_pred + gain * (z - x_pred)
        p = max((1.0 - gain) * p_pred, 1e-8)
        predicted.append(x_pred)
        filtered.append(x)
        variances.append(p)

    return {"filtered": filtered, "predicted": predicted, "variances": variances}


def compute_basic_error_metrics(actual, predicted):
    n = min(len(actual), len(predicted))
    if n == 0:
        return {"mae": None, "rmse": None, "corr": None, "samples": 0}
    a = [float(v) for v in actual[:n]]
    p = [float(v) for v in predicted[:n]]
    abs_errors = [abs(x - y) for x, y in zip(a, p)]
    sq_errors = [(x - y) ** 2 for x, y in zip(a, p)]
    mse = sum(sq_errors) / n if n else None
    return {
        "mae": (sum(abs_errors) / n) if n else None,
        "rmse": math.sqrt(mse) if mse is not None else None,
        "corr": pearson_corr(a, p),
        "samples": n,
    }


def align_prediction_with_delay(times_ms, actual, predicted, delay_steps):
    n = min(len(times_ms), len(actual), len(predicted))
    if n == 0:
        return {"times": [], "actual": [], "predicted": [], "delay_steps": delay_steps}

    delay = int(max(0, delay_steps or 0))
    if delay == 0:
        return {
            "times": list(times_ms[:n]),
            "actual": list(actual[:n]),
            "predicted": list(predicted[:n]),
            "delay_steps": 0,
        }
    if delay >= n:
        return {"times": [], "actual": [], "predicted": [], "delay_steps": delay}

    return {
        "times": list(times_ms[delay:n]),
        "actual": list(actual[delay:n]),
        "predicted": list(predicted[: n - delay]),
        "delay_steps": delay,
    }


def compute_kalman_funding_report(times_ms, funding_rates, optimal_lag_steps=0):
    n = min(len(times_ms), len(funding_rates))
    if n < 12:
        return None

    times = times_ms[:n]
    observed = [float(v) for v in funding_rates[:n]]
    kalman = kalman_filter_series(observed)
    filtered = kalman["filtered"]
    predicted = kalman["predicted"]

    split_idx = max(6, int(n * 0.66))
    if split_idx >= n - 3:
        return None

    times_is = times[:split_idx]
    times_oos = times[split_idx:]
    observed_is = observed[:split_idx]
    observed_oos = observed[split_idx:]
    filtered_is = filtered[:split_idx]
    filtered_oos = filtered[split_idx:]
    predicted_oos = predicted[split_idx:]
    delayed_oos = align_prediction_with_delay(times_oos, observed_oos, predicted_oos, optimal_lag_steps)

    return {
        "split_index": split_idx,
        "optimal_lag_steps": int(max(0, optimal_lag_steps or 0)),
        "all": {
            "times": times,
            "actual": observed,
            "filtered": filtered,
            "predicted": predicted,
        },
        "in_sample": {
            "times": times_is,
            "actual": observed_is,
            "filtered": filtered_is,
        },
        "out_of_sample": {
            "times": times_oos,
            "actual": observed_oos,
            "predicted": predicted_oos,
            "filtered": filtered_oos,
            "delay_aligned": delayed_oos,
        },
        "metrics": {
            "in_sample_filter_fit": compute_basic_error_metrics(observed_is, filtered_is),
            "out_of_sample_prediction": compute_basic_error_metrics(observed_oos, predicted_oos),
            "out_of_sample_prediction_delay_aligned": compute_basic_error_metrics(
                delayed_oos["actual"],
                delayed_oos["predicted"],
            ),
        },
    }


def compute_backtest_report(times_ms, prices, indicator):
    n = min(len(times_ms), len(prices), len(indicator))
    if n < 12:
        return None
    times = times_ms[:n]
    p = prices[:n]
    ind = indicator[:n]
    ind_signal = build_strategy_indicator(ind)

    split_idx = max(6, int(n * 0.66))
    if split_idx >= n - 3:
        return None

    times_is, times_oos = times[:split_idx], times[split_idx - 1:]
    prices_is, prices_oos = p[:split_idx], p[split_idx - 1:]
    ind_is, ind_oos = ind_signal[:split_idx], ind_signal[split_idx - 1:]
    max_lag = min(24, max(1, len(prices_is) // 3))

    step_ms = median_step_ms(times)
    ppy = estimate_periods_per_year(step_ms)
    params = find_best_lag_is(prices_is, ind_is, ppy, max_lag=max_lag)
    lag_steps = params["lag_steps"]
    direction = params["direction"]

    strat_is = simulate_strategy(prices_is, ind_is, lag_steps, direction)
    strat_full = simulate_strategy(p, ind_signal, lag_steps, direction)
    oos_indicator_history = []
    if lag_steps > 0:
        oos_start_idx = split_idx - 1
        hist_start = max(0, oos_start_idx - lag_steps)
        oos_indicator_history = ind_signal[hist_start:oos_start_idx]

    strat_oos = simulate_strategy(
        prices_oos,
        ind_oos,
        lag_steps,
        direction,
        indicator_history=oos_indicator_history,
    )
    bh_is = simulate_buy_and_hold(prices_is)
    bh_oos = simulate_buy_and_hold(prices_oos)
    bh_full = simulate_buy_and_hold(p)

    years_is = years_between(times_is)
    years_oos = years_between(times_oos)

    cagr_is = compute_cagr(1.0, strat_is["equity_curve"][-1], years_is) if strat_is["equity_curve"] else None
    cagr_oos = compute_cagr(1.0, strat_oos["equity_curve"][-1], years_oos) if strat_oos["equity_curve"] else None
    sharpe_is = compute_sharpe(strat_is["period_returns"], ppy)
    sharpe_oos = compute_sharpe(strat_oos["period_returns"], ppy)
    mdd_is = calc_max_drawdown(strat_is["equity_curve"])
    mdd_oos = calc_max_drawdown(strat_oos["equity_curve"])
    wr_is = strat_is["win_rate"]
    wr_oos = strat_oos["win_rate"]

    cagr_degrade = None
    if cagr_is is not None and cagr_is != 0 and cagr_oos is not None:
        cagr_degrade = (cagr_oos - cagr_is) / abs(cagr_is)
    sharpe_degrade = None
    if sharpe_is is not None and sharpe_is != 0 and sharpe_oos is not None:
        sharpe_degrade = (sharpe_oos - sharpe_is) / abs(sharpe_is)

    lag_sweep_is = []
    lag_sweep_oos = []
    lag_sweep_full = []
    for lag in range(1, max_lag + 1):
        a, b = slice_by_lag(prices_is, ind_is, lag)
        if len(a) < 16:
            continue
        corr = pearson_corr(a, b)
        if corr is None:
            continue
        sweep_direction = 1 if corr >= 0 else -1
        sweep_is = simulate_strategy(prices_is, ind_is, lag, sweep_direction)
        oos_indicator_history = []
        oos_start_idx = split_idx - 1
        hist_start = max(0, oos_start_idx - lag)
        oos_indicator_history = ind_signal[hist_start:oos_start_idx]
        sweep_oos = simulate_strategy(
            prices_oos,
            ind_oos,
            lag,
            sweep_direction,
            indicator_history=oos_indicator_history,
        )
        curve_meta = {
            "lag_steps": lag,
            "direction": sweep_direction,
            "corr": corr,
        }
        lag_sweep_is.append(
            {
                **curve_meta,
                "equity_curve": sweep_is["equity_curve"],
            }
        )
        lag_sweep_oos.append(
            {
                **curve_meta,
                "equity_curve": sweep_oos["equity_curve"],
            }
        )
        full_a, full_b = slice_by_lag(p, ind_signal, lag)
        full_corr = pearson_corr(full_a, full_b) if len(full_a) >= 16 else None
        if full_corr is not None:
            full_direction = 1 if full_corr >= 0 else -1
            sweep_full = simulate_strategy(p, ind_signal, lag, full_direction)
            lag_sweep_full.append(
                {
                    "lag_steps": lag,
                    "direction": full_direction,
                    "corr": full_corr,
                    "equity_curve": sweep_full["equity_curve"],
                }
            )

    return {
        "split_index": 0,
        "sweet_spot_lag_steps": lag_steps,
        "direction": direction,
        "selection_metric": params.get("metric", "is_sharpe"),
        "selection_score": params.get("score"),
        "fee_rate": 0.001,
        "slippage_rate": 0.0005,
        "equity_curves": {
            "full_sample": {
                "times": times,
                "strategy": strat_full["equity_curve"],
                "buy_and_hold": bh_full["equity_curve"],
                "lag_sweep": {
                    "times": times,
                    "curves": lag_sweep_full,
                },
            },
            "in_sample": {
                "times": times_is,
                "strategy": strat_is["equity_curve"],
                "buy_and_hold": bh_is["equity_curve"],
                "lag_sweep": {
                    "times": times_is,
                    "curves": lag_sweep_is,
                },
            },
            "out_of_sample": {
                "times": times_oos,
                "strategy": strat_oos["equity_curve"],
                "buy_and_hold": bh_oos["equity_curve"],
                "lag_sweep": {
                    "times": times_oos,
                    "curves": lag_sweep_oos,
                },
            },
        },
        "metrics": {
            "full_sample": summarize_strategy_metrics(times, strat_full["equity_curve"], strat_full["period_returns"], ppy),
            "in_sample": {
                "cagr": cagr_is,
                "sharpe": sharpe_is,
                "mdd": mdd_is,
                "win_rate": wr_is,
            },
            "out_of_sample": {
                "cagr": cagr_oos,
                "sharpe": sharpe_oos,
                "mdd": mdd_oos,
                "win_rate": wr_oos,
            },
            "overfitting": {
                "cagr_degradation": cagr_degrade,
                "sharpe_degradation": sharpe_degrade,
            },
        },
    }


def summarize_strategy_metrics(times_ms, equity_curve, period_returns, periods_per_year):
    years = years_between(times_ms)
    cagr = compute_cagr(1.0, equity_curve[-1], years) if equity_curve else None
    sharpe = compute_sharpe(period_returns, periods_per_year)
    mdd = calc_max_drawdown(equity_curve)
    wins = [r for r in period_returns if r > 0]
    win_rate = (len(wins) / len(period_returns)) if period_returns else None
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "mdd": mdd,
        "win_rate": win_rate,
    }


def compute_adaptive_lag_history(times_ms, prices, indicator):
    n = min(len(times_ms), len(prices), len(indicator))
    if n < 12:
        base_times = list(times_ms[:n])
        return {
            "times": base_times,
            "lag_history": [None] * n,
            "direction_history": [0] * n,
            "kalman_filtered": [],
            "kalman_predicted": [],
        }

    times = list(times_ms[:n])
    p = [float(v) for v in prices[:n]]
    ind_signal = build_strategy_indicator(indicator[:n])
    step_ms = median_step_ms(times)
    ppy = estimate_periods_per_year(step_ms)
    lag_history = [None]
    direction_history = [0]

    for t in range(1, n):
        hist_prices = p[:t]
        hist_indicator = ind_signal[:t]
        hist_max_lag = min(24, max(1, len(hist_prices) // 3))
        params = find_best_lag_sharpe(
            hist_prices,
            hist_indicator,
            ppy,
            max_lag=hist_max_lag,
            allow_zero=True,
        )
        lag_history.append(int(params["lag_steps"]))
        direction_history.append(int(params["direction"]))

    lag_numeric = [float(v) if v is not None else 0.0 for v in lag_history]
    lag_kalman = kalman_filter_series(lag_numeric)

    return {
        "times": times,
        "lag_history": lag_history,
        "direction_history": direction_history,
        "kalman_filtered": lag_kalman["filtered"],
        "kalman_predicted": lag_kalman["predicted"],
    }


def compute_lag_kalman_equity_report(times_ms, prices, indicator, adaptive_lag):
    n = min(len(times_ms), len(prices), len(indicator))
    if n < 12 or not adaptive_lag:
        return None

    times = list(times_ms[:n])
    p = [float(v) for v in prices[:n]]
    ind_signal = build_strategy_indicator(indicator[:n])
    lag_forecast = list((adaptive_lag.get("kalman_predicted") or [])[:n])
    direction_history = list((adaptive_lag.get("direction_history") or [])[:n])
    if len(lag_forecast) < n or len(direction_history) < n:
        return None

    fee_rate = 0.001
    slippage_rate = 0.0005
    step_ms = median_step_ms(times)
    ppy = estimate_periods_per_year(step_ms)
    equity = 1.0
    equity_curve = [equity]
    period_returns = []
    prev_position = 0
    lag_used = [0]

    for t in range(1, n):
        lag_steps = int(round(lag_forecast[t])) if lag_forecast[t] is not None else 0
        lag_steps = max(0, min(24, lag_steps))
        direction = int(direction_history[t]) if direction_history[t] in (-1, 1) else 0
        signal_idx = t - lag_steps
        if signal_idx < 0 or signal_idx >= len(ind_signal):
            position = 0
        else:
            raw = ind_signal[signal_idx]
            base_pos = 1 if raw > 0 else (-1 if raw < 0 else 0)
            position = base_pos * direction

        turnover = abs(position - prev_position)
        if turnover > 0:
            cost = turnover * (fee_rate + slippage_rate)
            equity *= max(0.0, 1.0 - cost)

        step_ret = (p[t] / p[t - 1]) - 1.0
        strat_ret = position * step_ret
        equity *= (1.0 + strat_ret)
        equity_curve.append(equity)
        period_returns.append(strat_ret)
        prev_position = position
        lag_used.append(lag_steps)

    return {
        "model": "lag_kalman_forecast_equity",
        "lag_used": lag_used,
        "equity_curve": {
            "times": times,
            "strategy": equity_curve,
        },
        "metrics": summarize_strategy_metrics(times, equity_curve, period_returns, ppy),
    }


def compute_kalman_backtest_report(times_ms, prices, indicator):
    n = min(len(times_ms), len(prices), len(indicator))
    if n < 24:
        return None

    times = list(times_ms[:n])
    p = [float(v) for v in prices[:n]]
    ind = [float(v) for v in indicator[:n]]
    kalman = kalman_filter_series(ind)
    predicted_indicator = kalman["predicted"]
    predicted_signal = build_strategy_indicator(predicted_indicator)

    step_ms = median_step_ms(times)
    ppy = estimate_periods_per_year(step_ms)
    fee_rate = 0.001
    slippage_rate = 0.0005
    equity = 1.0
    equity_curve = [equity]
    period_returns = []
    lag_history = [None]
    direction_history = [0]
    prev_position = 0

    for t in range(1, n):
        hist_prices = p[:t]
        hist_indicator = predicted_signal[:t]
        hist_max_lag = min(24, max(1, len(hist_prices) // 3))
        params = find_best_lag_sharpe(
            hist_prices,
            hist_indicator,
            ppy,
            max_lag=hist_max_lag,
            allow_zero=True,
        )
        lag_steps = int(params["lag_steps"])
        direction = int(params["direction"])
        signal_idx = t - lag_steps
        if signal_idx < 0 or signal_idx >= len(predicted_signal):
            position = 0
        else:
            raw = predicted_signal[signal_idx]
            base_pos = 1 if raw > 0 else (-1 if raw < 0 else 0)
            position = base_pos * direction

        turnover = abs(position - prev_position)
        if turnover > 0:
            cost = turnover * (fee_rate + slippage_rate)
            equity *= max(0.0, 1.0 - cost)

        step_ret = (p[t] / p[t - 1]) - 1.0
        strat_ret = position * step_ret
        equity *= (1.0 + strat_ret)
        equity_curve.append(equity)
        period_returns.append(strat_ret)
        lag_history.append(lag_steps)
        direction_history.append(direction)
        prev_position = position

    split_idx = max(6, int(n * 0.66))
    bh_full = simulate_buy_and_hold(p)

    times_is = times[:split_idx]
    times_oos = times[split_idx - 1:]
    strategy_is = equity_curve[:split_idx]
    strategy_oos = equity_curve[split_idx - 1:]
    bh_is = bh_full["equity_curve"][:split_idx]
    bh_oos = bh_full["equity_curve"][split_idx - 1:]
    returns_is = period_returns[: max(0, split_idx - 1)]
    returns_oos = period_returns[max(0, split_idx - 1):]

    latest_lag = next((lag for lag in reversed(lag_history) if lag is not None), 0)
    latest_dir = next((d for d in reversed(direction_history) if d in (-1, 1)), 1)
    latest_score = None
    if n >= 2:
        latest_params = find_best_lag_sharpe(
            p[:-1],
            predicted_signal[:-1],
            ppy,
            max_lag=min(24, max(1, (n - 1) // 3)),
            allow_zero=True,
        )
        latest_score = latest_params.get("score")

    return {
        "model": "kalman_predicted_walkforward_8h",
        "split_index": split_idx,
        "sweet_spot_lag_steps": latest_lag,
        "direction": latest_dir,
        "selection_metric": "walkforward_is_sharpe",
        "selection_score": latest_score,
        "fee_rate": fee_rate,
        "slippage_rate": slippage_rate,
        "lag_history": lag_history,
        "direction_history": direction_history,
        "indicator_preview": {
            "times": times,
            "predicted": predicted_indicator,
            "filtered": kalman["filtered"],
        },
        "equity_curves": {
            "full_sample": {
                "times": times,
                "strategy": equity_curve,
                "buy_and_hold": bh_full["equity_curve"],
            },
            "in_sample": {
                "times": times_is,
                "strategy": strategy_is,
                "buy_and_hold": bh_is,
                "lag_sweep": {"times": times_is, "curves": []},
            },
            "out_of_sample": {
                "times": times_oos,
                "strategy": strategy_oos,
                "buy_and_hold": bh_oos,
                "lag_sweep": {"times": times_oos, "curves": []},
            },
        },
        "metrics": {
            "full_sample": summarize_strategy_metrics(times, equity_curve, period_returns, ppy),
            "in_sample": summarize_strategy_metrics(times_is, strategy_is, returns_is, ppy),
            "out_of_sample": summarize_strategy_metrics(times_oos, strategy_oos, returns_oos, ppy),
        },
    }


def fetch_binance_ticker_snapshot():
    symbols_param = json.dumps(CRYPTO_SYMBOLS)
    try:
        prices = fetch_binance_json("/api/v3/ticker/price", {"symbols": symbols_param})
    except requests.RequestException:
        prices = [fetch_binance_json("/api/v3/ticker/price", {"symbol": s}) for s in CRYPTO_SYMBOLS]

    try:
        stats = fetch_binance_json("/api/v3/ticker/24hr", {"symbols": symbols_param})
    except requests.RequestException:
        stats = [fetch_binance_json("/api/v3/ticker/24hr", {"symbol": s}) for s in CRYPTO_SYMBOLS]

    price_map = {item["symbol"]: item for item in prices}
    stat_map = {item["symbol"]: item for item in stats}
    snapshot_assets = []
    for symbol in CRYPTO_SYMBOLS:
        price_item = price_map[symbol]
        stat_item = stat_map[symbol]
        snapshot_assets.append(
            {
                "symbol": symbol,
                "base_asset": symbol.replace("USDT", ""),
                "current_price": float(price_item["price"]),
                "price_change_percent_24h": float(stat_item["priceChangePercent"]),
                "quote_volume_24h": float(stat_item["quoteVolume"]),
            }
        )
    return snapshot_assets

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
    analysis_interval = request.args.get('analysis_interval', '8h')
    limit_arg = request.args.get('limit', '120')
    if interval not in {"15m", "1h", "1d", "1w", "1M"}:
        return jsonify({"status": "ERROR", "error_msg": "Unsupported interval."}), 400
    if analysis_interval not in {"1h", "4h", "8h", "24h"}:
        return jsonify({"status": "ERROR", "error_msg": "Unsupported analysis interval."}), 400

    try:
        limit = int(limit_arg)
    except ValueError:
        limit = 120
    limit = max(30, min(limit, 500))

    try:
        snapshot_assets = fetch_binance_ticker_snapshot()
        assets = []
        for snapshot_asset in snapshot_assets:
            symbol = snapshot_asset["symbol"]
            display_kline = fetch_ohlcv_with_cache(symbol, interval, limit)
            if not display_kline:
                raise ValueError(f"No OHLCV data available for {symbol} ({interval})")
            start_time_ms = int(display_kline[0][0])
            end_time_ms = int(display_kline[-1][6])

            analysis_limit = estimate_limit_for_window(interval, limit, analysis_interval)
            analysis_kline = fetch_ohlcv_with_cache(symbol, analysis_interval, analysis_limit)
            analysis_kline = [row for row in analysis_kline if start_time_ms <= int(row[0]) <= end_time_ms]
            if not analysis_kline:
                analysis_kline = display_kline
                analysis_interval = interval

            funding_json = fetch_funding_history(symbol, start_time_ms, end_time_ms)
            funding_times, funding_rates, funding_resolution = aggregate_funding_points(funding_json, interval)
            funding_pairs = list(zip(funding_times, funding_rates))
            display_times = [int(item[0]) for item in display_kline]
            display_closes = [float(item[4]) for item in display_kline]
            analysis_times = [int(item[0]) for item in analysis_kline]
            analysis_closes = [float(item[4]) for item in analysis_kline]
            aligned_prices, aligned_funding = align_price_to_indicator(
                analysis_times,
                analysis_closes,
                funding_pairs,
            )
            backtest_times, backtest_prices, backtest_funding = expand_indicator_to_price_times(
                analysis_times,
                analysis_closes,
                funding_pairs,
            )
            funding_corr = pearson_corr(aligned_prices, aligned_funding)
            funding_step_ms = median_step_ms(funding_times)
            cross_corr = cross_correlation_analysis(aligned_prices, aligned_funding, funding_step_ms)
            delayed_mi = delayed_mutual_information_analysis(aligned_prices, aligned_funding, funding_step_ms)
            granger = granger_causality_analysis(aligned_prices, aligned_funding)
            backtest = compute_backtest_report(backtest_times, backtest_prices, backtest_funding)
            kalman_backtest = compute_kalman_backtest_report(backtest_times, backtest_prices, backtest_funding)
            adaptive_lag = compute_adaptive_lag_history(backtest_times, backtest_prices, backtest_funding)
            lag_kalman_equity = compute_lag_kalman_equity_report(
                backtest_times,
                backtest_prices,
                backtest_funding,
                adaptive_lag,
            )
            optimal_lag_steps = backtest["sweet_spot_lag_steps"] if backtest else 0
            kalman_report = compute_kalman_funding_report(
                funding_times,
                funding_rates,
                optimal_lag_steps=optimal_lag_steps,
            )

            asset = {
                **snapshot_asset,
                "times": display_times,
                "closes": display_closes,
                "price_resolution": {
                    "display_interval": interval,
                    "analysis_interval": analysis_interval,
                    "analysis_points": len(analysis_times),
                },
                "funding_times": funding_times,
                "funding_rates": funding_rates,
                "funding_resolution": funding_resolution,
                "indicator_correlations": {
                    "funding": funding_corr,
                },
                "correlation_samples": {
                    "funding": min(len(aligned_prices), len(aligned_funding)),
                },
                "indicator_lead_analysis": {
                    "funding": {
                        "cross_correlation": cross_corr,
                        "granger": granger,
                        "mutual_information": delayed_mi,
                        "backtest": backtest,
                        "kalman_backtest": kalman_backtest,
                        "adaptive_lag": adaptive_lag,
                        "lag_kalman_equity": lag_kalman_equity,
                        "kalman": kalman_report,
                    }
                },
            }
            assets.append(asset)

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


@app.route('/api/crypto-ticker')
def crypto_ticker():
    try:
        assets = fetch_binance_ticker_snapshot()
        return jsonify(
            {
                "status": "SUCCESS",
                "assets": assets,
                "source": "Binance Public API",
                "server_time_ms": int(time.time() * 1000),
            }
        )
    except requests.RequestException as exc:
        print(f"BINANCE TICKER API ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": "Failed to call Binance API."}), 502
    except Exception as exc:
        print(f"CRYPTO TICKER ERROR: {exc}")
        return jsonify({"status": "ERROR", "error_msg": str(exc)}), 500

@app.route('/api/git-commands', methods=['GET', 'POST'])
def git_commands():
    gist_manager = get_gist_manager()
    if gist_manager is None:
        return gist_config_missing_response()
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
        return gist_config_missing_response()
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
