from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable


class NeonDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    funding_rate REAL,
                    source TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    sample_rate REAL NOT NULL,
                    expected_return REAL NOT NULL,
                    confidence_ess REAL NOT NULL,
                    horizon_sec INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    due_ts_ms INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actual_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id INTEGER NOT NULL UNIQUE,
                    ts_ms INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    realized_return REAL NOT NULL,
                    actual_profit REAL NOT NULL,
                    abs_error REAL NOT NULL,
                    FOREIGN KEY(prediction_id) REFERENCES predictions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS node_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    node_label TEXT NOT NULL,
                    cpu_percent REAL,
                    mem_percent REAL,
                    gpu_percent REAL,
                    temp_c REAL,
                    mps_available INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def insert_market_rows(self, rows: Iterable[dict]) -> None:
        payload = [
            (
                int(r["ts_ms"]),
                r["asset"],
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
                float(r["volume"]),
                (None if r.get("funding_rate") is None else float(r["funding_rate"])),
                r.get("source", "binance"),
            )
            for r in rows
        ]
        if not payload:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO market_data(
                    ts_ms, asset, open, high, low, close, volume, funding_rate, source
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    def insert_prediction(
        self,
        ts_ms: int,
        asset: str,
        sample_rate: float,
        expected_return: float,
        confidence_ess: float,
        horizon_sec: int,
        entry_price: float,
    ) -> int:
        due_ts_ms = ts_ms + int(horizon_sec * 1000)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO predictions(
                    ts_ms, asset, sample_rate, expected_return, confidence_ess, horizon_sec, entry_price, due_ts_ms, status
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (
                    int(ts_ms),
                    asset,
                    float(sample_rate),
                    float(expected_return),
                    float(confidence_ess),
                    int(horizon_sec),
                    float(entry_price),
                    int(due_ts_ms),
                ),
            )
            return int(cur.lastrowid)

    def fetch_open_predictions_due(self, now_ms: int | None = None) -> list[sqlite3.Row]:
        target_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT *
                FROM predictions
                WHERE status='OPEN' AND due_ts_ms <= ?
                ORDER BY due_ts_ms ASC
                """,
                (target_ms,),
            )
            return cur.fetchall()

    def resolve_prediction(self, prediction_row: sqlite3.Row, current_price: float, now_ms: int) -> None:
        expected_return = float(prediction_row["expected_return"])
        entry_price = float(prediction_row["entry_price"])
        realized_return = (float(current_price) / entry_price) - 1.0
        actual_profit = realized_return
        abs_error = abs(realized_return - expected_return)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO actual_results(
                    prediction_id, ts_ms, asset, realized_return, actual_profit, abs_error
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    int(prediction_row["id"]),
                    int(now_ms),
                    prediction_row["asset"],
                    float(realized_return),
                    float(actual_profit),
                    float(abs_error),
                ),
            )
            conn.execute(
                "UPDATE predictions SET status='CLOSED' WHERE id=?",
                (int(prediction_row["id"]),),
            )

    def insert_node_metrics(self, ts_ms: int, rows: Iterable[dict]) -> None:
        payload = [
            (
                int(ts_ms),
                r["node_label"],
                r.get("cpu_percent"),
                r.get("mem_percent"),
                r.get("gpu_percent"),
                r.get("temp_c"),
                1 if r.get("mps_available") else 0,
            )
            for r in rows
        ]
        if not payload:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO node_metrics(ts_ms, node_label, cpu_percent, mem_percent, gpu_percent, temp_c, mps_available)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )

    def load_expected_vs_actual(self, limit: int = 1000) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT p.ts_ms, p.asset, p.expected_return, p.confidence_ess, a.actual_profit, a.abs_error
                FROM predictions p
                JOIN actual_results a ON a.prediction_id = p.id
                ORDER BY p.ts_ms DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            return cur.fetchall()

    def latest_node_metrics(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                WITH ranked AS (
                    SELECT *,
                           ROW_NUMBER() OVER (PARTITION BY node_label ORDER BY ts_ms DESC) AS rn
                    FROM node_metrics
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                ORDER BY node_label ASC
                """
            )
            return cur.fetchall()

