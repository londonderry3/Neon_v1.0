from __future__ import annotations

import platform
import time
from typing import Any

import psutil
import ray

try:
    import Metal  # type: ignore
except Exception:
    Metal = None  # type: ignore

try:
    import torch
except Exception:
    torch = None  # type: ignore


def _read_temperature_c() -> float | None:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        if not temps:
            return None
        for group in temps.values():
            for item in group:
                if getattr(item, "current", None) is not None:
                    return float(item.current)
    except Exception:
        return None
    return None


def _read_mps_gpu_usage() -> tuple[float | None, bool]:
    if platform.system() != "Darwin":
        return None, False
    if Metal is None:
        return None, False
    mps_available = bool(torch is not None and hasattr(torch, "backends") and torch.backends.mps.is_available())
    try:
        device = Metal.MTLCreateSystemDefaultDevice()
        if device is None:
            return None, mps_available
        # Metal doesn't expose direct utilization on macOS without privileged APIs.
        # We infer pressure from allocated bytes vs. recommended max set.
        recommended = float(getattr(device, "recommendedMaxWorkingSetSize", 0.0) or 0.0)
        allocated = 0.0
        if torch is not None and mps_available and hasattr(torch, "mps"):
            getter = getattr(torch.mps, "current_allocated_memory", None)
            if callable(getter):
                allocated = float(getter())
        gpu_percent = None
        if recommended > 0 and allocated >= 0:
            gpu_percent = max(0.0, min(100.0, (allocated / recommended) * 100.0))
        return gpu_percent, mps_available
    except Exception:
        return None, mps_available


@ray.remote
def collect_node_resources(node_label: str) -> dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.1)
    mem_percent = psutil.virtual_memory().percent
    temp_c = _read_temperature_c()
    gpu_percent, mps_available = _read_mps_gpu_usage()
    return {
        "ts_ms": int(time.time() * 1000),
        "node_label": node_label,
        "cpu_percent": float(cpu_percent),
        "mem_percent": float(mem_percent),
        "gpu_percent": (None if gpu_percent is None else float(gpu_percent)),
        "temp_c": (None if temp_c is None else float(temp_c)),
        "mps_available": bool(mps_available),
    }

