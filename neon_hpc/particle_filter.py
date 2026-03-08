from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import ray
import torch


@dataclass
class PFOutput:
    expected_return: dict[str, float]
    confidence_ess: dict[str, float]
    pdf: dict[str, dict[str, list[float]]]


def _pick_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _safe_std(values: torch.Tensor) -> torch.Tensor:
    std = values.std(dim=1, unbiased=False)
    return torch.clamp(std, min=1e-6)


@ray.remote
def pf_predict_worker(
    assets: list[str],
    close_matrix: list[list[float]],
    funding_rates: list[float],
    num_particles: int,
    horizon_steps: int,
    aggressiveness: float,
    seed: int,
) -> dict[str, Any]:
    torch.manual_seed(seed)
    device = _pick_device()
    closes = torch.tensor(close_matrix, dtype=torch.float32, device=device)  # [A, T]
    funding = torch.tensor(funding_rates, dtype=torch.float32, device=device)  # [A]
    log_returns = torch.diff(torch.log(torch.clamp(closes, min=1e-8)), dim=1)  # [A, T-1]
    mu = log_returns.mean(dim=1, keepdim=True)  # [A, 1]
    vol = _safe_std(log_returns).unsqueeze(1)  # [A, 1]
    last_price = closes[:, -1:].repeat(1, num_particles)  # [A, P]

    # Prior particles around last observed price
    noise = torch.randn((len(assets), num_particles), device=device) * (vol * 0.5 + 1e-6)
    particles = last_price * torch.exp(noise)

    # Observation weight update from latest realized return (causal look-back only)
    last_obs_ret = log_returns[:, -1:].repeat(1, num_particles)
    innovation = noise - last_obs_ret
    obs_var = torch.clamp(vol**2, min=1e-6)
    log_w = -0.5 * (innovation**2 / obs_var)
    w = torch.softmax(log_w, dim=1)
    ess = 1.0 / torch.clamp((w**2).sum(dim=1), min=1e-12)
    ess_ratio = (ess / float(num_particles)).detach().cpu().numpy()

    # Forward trajectories to T+N
    drift = mu - 0.5 * vol**2 + funding.unsqueeze(1) * (0.02 * float(aggressiveness))
    for _ in range(int(max(1, horizon_steps))):
        eps = torch.randn((len(assets), num_particles), device=device)
        step_ret = drift + vol * eps
        particles = particles * torch.exp(step_ret)

    terminal_ret = (particles / last_price) - 1.0
    expected = (terminal_ret * w).sum(dim=1).detach().cpu().numpy()

    out_expected: dict[str, float] = {}
    out_ess: dict[str, float] = {}
    out_pdf: dict[str, dict[str, list[float]]] = {}
    terminal_cpu = terminal_ret.detach().cpu().numpy()
    for i, asset in enumerate(assets):
        out_expected[asset] = float(expected[i])
        out_ess[asset] = float(ess_ratio[i])
        hist, edges = np.histogram(terminal_cpu[i], bins=40, density=True)
        centers = ((edges[:-1] + edges[1:]) / 2.0).tolist()
        out_pdf[asset] = {"x": centers, "y": hist.tolist()}

    return {
        "particles": int(num_particles),
        "expected_return": out_expected,
        "confidence_ess": out_ess,
        "pdf": out_pdf,
    }


def merge_worker_outputs(assets: list[str], parts: list[dict[str, Any]]) -> PFOutput:
    total_particles = float(sum(max(1, p["particles"]) for p in parts))
    expected: dict[str, float] = {}
    ess: dict[str, float] = {}
    pdf: dict[str, dict[str, list[float]]] = {}
    for asset in assets:
        exp_val = 0.0
        ess_val = 0.0
        pdf_x = None
        pdf_y = None
        for p in parts:
            w = float(max(1, p["particles"])) / total_particles
            exp_val += float(p["expected_return"][asset]) * w
            ess_val += float(p["confidence_ess"][asset]) * w
            p_pdf = p["pdf"][asset]
            if pdf_x is None:
                pdf_x = list(p_pdf["x"])
                pdf_y = [0.0] * len(pdf_x)
            for i, val in enumerate(p_pdf["y"]):
                pdf_y[i] += float(val) * w
        expected[asset] = exp_val
        ess[asset] = ess_val
        pdf[asset] = {"x": pdf_x or [], "y": pdf_y or []}
    return PFOutput(expected_return=expected, confidence_ess=ess, pdf=pdf)

