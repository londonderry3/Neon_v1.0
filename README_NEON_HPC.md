# Neon HPC Cluster System

## 1) Install Dependencies

```bash
pip install streamlit ray psutil torch plotly pyobjc-framework-Metal requests pandas
```

## 2) Start Ray Cluster (M4 Master + M2 Worker)

### Master (M4 Mac Mini)

```bash
ray stop
ray start --head --port=6379 --resources='{"m4": 1}'
```

### Worker (M2 MacBook)

```bash
ray stop
ray start --address='MASTER_IP:6379' --resources='{"m2": 1}'
```

## 3) Run Streamlit UI

```bash
streamlit run streamlit_neon.py
```

## Notes

- Asymmetric particle allocation:
  - M4: `10,000`
  - M2: `5,000`
- SQLite DB path: `analysis/neon_hpc.db`
- Zero-OOS policy:
  - Predictions are logged at decision time.
  - `actual_results` are written only after `due_ts` passes.
- GPU(MPS) metric:
  - Uses `pyobjc-Framework-Metal` + PyTorch MPS allocated-memory proxy.
  - Direct hardware utilization is not exposed by Metal public API on macOS.

