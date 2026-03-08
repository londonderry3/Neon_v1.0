from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import ray

from .config import NeonConfig
from .datafeed import BinanceDataFeed
from .db import NeonDB
from .monitor import collect_node_resources
from .particle_filter import PFOutput, merge_worker_outputs, pf_predict_worker


@dataclass
class TuneFactors:
    threshold: float
    aggressiveness: float
    horizon_steps: int
    sample_rate: float


class NeonEngine:
    def __init__(self, config: NeonConfig):
        self.config = config
        self.db = NeonDB(config.storage.db_path)
        self.feed = BinanceDataFeed()
        self._ray_ready = False

    def ensure_ray(self) -> None:
        if self._ray_ready and ray.is_initialized():
            return
        try:
            ray.init(address=self.config.cluster.ray_address, ignore_reinit_error=True, logging_level=40)
        except Exception:
            ray.init(ignore_reinit_error=True, logging_level=40)
        self._ray_ready = True

    def _with_resource(self, remote_fn: Any, label: str | None):
        if not label:
            return remote_fn
        cluster = ray.cluster_resources()
        if label in cluster:
            return remote_fn.options(resources={label: 0.001})
        return remote_fn

    async def _collect_cluster_metrics(self) -> list[dict[str, Any]]:
        labels = self.config.cluster.resource_labels
        tasks = [
            self._with_resource(collect_node_resources, labels.get("m4")).remote("M4"),
            self._with_resource(collect_node_resources, labels.get("m2")).remote("M2"),
        ]
        rows = ray.get(tasks)
        return [dict(r) for r in rows]

    async def _distributed_predict(
        self,
        assets: list[str],
        close_matrix: list[list[float]],
        funding_rates: list[float],
        tune: TuneFactors,
    ) -> PFOutput:
        labels = self.config.cluster.resource_labels
        m4_task = self._with_resource(pf_predict_worker, labels.get("m4")).remote(
            assets=assets,
            close_matrix=close_matrix,
            funding_rates=funding_rates,
            num_particles=self.config.cluster.m4_particles,
            horizon_steps=tune.horizon_steps,
            aggressiveness=tune.aggressiveness,
            seed=int(time.time() * 1000) % 2_147_483_647,
        )
        m2_task = self._with_resource(pf_predict_worker, labels.get("m2")).remote(
            assets=assets,
            close_matrix=close_matrix,
            funding_rates=funding_rates,
            num_particles=self.config.cluster.m2_particles,
            horizon_steps=tune.horizon_steps,
            aggressiveness=tune.aggressiveness,
            seed=(int(time.time() * 1000) + 17) % 2_147_483_647,
        )
        parts = ray.get([m4_task, m2_task])
        return merge_worker_outputs(assets, parts)

    async def run_once(self, tune: TuneFactors | None = None) -> dict[str, Any]:
        self.ensure_ray()
        cfg = self.config.engine
        tune = tune or TuneFactors(
            threshold=cfg.decision_threshold,
            aggressiveness=cfg.aggressiveness,
            horizon_steps=cfg.horizon_steps,
            sample_rate=1.0 / max(1.0, cfg.loop_interval_sec),
        )

        assets = list(cfg.assets)
        snapshots = self.feed.fetch_all(assets, interval=cfg.bar_interval, lookback_bars=cfg.lookback_bars)
        market_rows = []
        close_matrix: list[list[float]] = []
        funding_rates: list[float] = []
        latest_prices: dict[str, float] = {}
        now_ms = int(time.time() * 1000)
        for asset in assets:
            snap = snapshots[asset]
            for row in snap.ohlcv_rows[-2:]:
                market_rows.append(
                    {
                        **row,
                        "funding_rate": snap.funding_rate,
                    }
                )
            close_matrix.append([float(r["close"]) for r in snap.ohlcv_rows])
            funding_rates.append(float(snap.funding_rate))
            latest_prices[asset] = float(snap.last_price)
        self.db.insert_market_rows(market_rows)

        pf = await self._distributed_predict(
            assets=assets,
            close_matrix=close_matrix,
            funding_rates=funding_rates,
            tune=tune,
        )

        horizon_sec = int(tune.horizon_steps * 60)  # 1m base interval
        decisions: list[dict[str, Any]] = []
        for asset in assets:
            expected = float(pf.expected_return[asset])
            ess = float(pf.confidence_ess[asset])
            entry_price = float(latest_prices[asset])
            pred_id = self.db.insert_prediction(
                ts_ms=now_ms,
                asset=asset,
                sample_rate=tune.sample_rate,
                expected_return=expected,
                confidence_ess=ess,
                horizon_sec=horizon_sec,
                entry_price=entry_price,
            )
            decisions.append(
                {
                    "prediction_id": pred_id,
                    "asset": asset,
                    "expected_return": expected,
                    "confidence_ess": ess,
                    "entry_price": entry_price,
                    "signal": "LONG" if expected > tune.threshold else ("SHORT" if expected < -tune.threshold else "FLAT"),
                }
            )

        due_rows = self.db.fetch_open_predictions_due(now_ms=now_ms)
        for row in due_rows:
            asset = str(row["asset"])
            if asset in latest_prices:
                self.db.resolve_prediction(row, current_price=latest_prices[asset], now_ms=now_ms)

        node_metrics = await self._collect_cluster_metrics()
        self.db.insert_node_metrics(ts_ms=now_ms, rows=node_metrics)

        return {
            "ts_ms": now_ms,
            "decisions": decisions,
            "pdf": pf.pdf,
            "expected_return": pf.expected_return,
            "confidence_ess": pf.confidence_ess,
            "node_metrics": node_metrics,
        }

    async def run_forever(self, tune: TuneFactors | None = None) -> None:
        interval = max(0.1, float(self.config.engine.loop_interval_sec))
        while True:
            await self.run_once(tune=tune)
            await asyncio.sleep(interval)

