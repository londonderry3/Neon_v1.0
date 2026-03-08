from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ClusterConfig:
    ray_address: str = "auto"
    m4_particles: int = 10_000
    m2_particles: int = 5_000
    # Start Ray nodes with matching custom resources, e.g. --resources='{"m4": 1}'
    resource_labels: dict[str, str] = field(
        default_factory=lambda: {"m4": "m4", "m2": "m2"}
    )


@dataclass(frozen=True)
class EngineConfig:
    assets: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "XRPUSDT")
    bar_interval: str = "1m"
    lookback_bars: int = 180
    horizon_steps: int = 8  # 8x1m default, tune from UI
    loop_interval_sec: float = 1.0
    decision_threshold: float = 0.0005
    aggressiveness: float = 1.0


@dataclass(frozen=True)
class StorageConfig:
    db_path: Path = Path("analysis/neon_hpc.db")


@dataclass(frozen=True)
class NeonConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

