from __future__ import annotations

import asyncio
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from neon_hpc.config import NeonConfig
from neon_hpc.engine import NeonEngine, TuneFactors


st.set_page_config(page_title="Neon Cluster Trading Engine", layout="wide")


@st.cache_resource
def get_engine() -> NeonEngine:
    return NeonEngine(NeonConfig())


def gauge_chart(title: str, value: float, max_value: float = 100.0, color: str = "#73daca") -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(value),
            title={"text": title},
            gauge={
                "axis": {"range": [0, max_value]},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, 50], "color": "rgba(115,218,202,0.20)"},
                    {"range": [50, 80], "color": "rgba(224,175,104,0.25)"},
                    {"range": [80, 100], "color": "rgba(247,118,142,0.30)"},
                ],
            },
        )
    )
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def render_pdf_grid(pdf_data: dict[str, dict[str, list[float]]]) -> None:
    cols = st.columns(5)
    for idx, (asset, dist) in enumerate(pdf_data.items()):
        with cols[idx % 5]:
            fig = go.Figure(
                data=[go.Scatter(x=dist["x"], y=dist["y"], mode="lines", fill="tozeroy", name=asset)]
            )
            fig.update_layout(
                title=f"{asset} Return PDF (T+N)",
                height=220,
                margin=dict(l=10, r=10, t=35, b=25),
                xaxis_title="Return",
                yaxis_title="Density",
            )
            st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    cfg = NeonConfig()
    engine = get_engine()

    st.title("Neon: High-Performance Crypto Trading Engine")
    st.caption("Ray Cluster + Particle Filter + SQLite + Real-time Streamlit Monitoring")

    with st.sidebar:
        st.header("Global Tune Factors")
        threshold = st.slider("Threshold", 0.0, 0.01, float(cfg.engine.decision_threshold), 0.0001)
        aggressiveness = st.slider("Aggressiveness", 0.1, 3.0, float(cfg.engine.aggressiveness), 0.1)
        horizon_steps = st.slider("Horizon Steps (T+N)", 1, 30, int(cfg.engine.horizon_steps), 1)
        loop_interval = st.slider("Loop Interval (sec)", 0.2, 5.0, float(cfg.engine.loop_interval_sec), 0.1)
        auto_run = st.toggle("Auto Run", value=True)
        run_once_btn = st.button("Run One Tick")

    tune = TuneFactors(
        threshold=threshold,
        aggressiveness=aggressiveness,
        horizon_steps=horizon_steps,
        sample_rate=1.0 / max(0.001, loop_interval),
    )

    if "last_tick" not in st.session_state:
        st.session_state["last_tick"] = None
    if "last_exec_ms" not in st.session_state:
        st.session_state["last_exec_ms"] = 0

    should_tick = run_once_btn
    if auto_run:
        now_ms = int(time.time() * 1000)
        if now_ms - int(st.session_state["last_exec_ms"]) >= int(loop_interval * 1000):
            should_tick = True

    if should_tick:
        tick = asyncio.run(engine.run_once(tune=tune))
        st.session_state["last_tick"] = tick
        st.session_state["last_exec_ms"] = int(time.time() * 1000)

    tick = st.session_state["last_tick"]

    row1 = st.empty()
    row2 = st.empty()
    row3 = st.empty()

    with row1.container():
        st.subheader("Row 1: System Status")
        metrics_rows = engine.db.latest_node_metrics()
        m4 = next((r for r in metrics_rows if r["node_label"] == "M4"), None)
        m2 = next((r for r in metrics_rows if r["node_label"] == "M2"), None)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("M4 CPU", f"{(m4['cpu_percent'] if m4 else 0.0):.1f}%")
            st.metric("M4 RAM", f"{(m4['mem_percent'] if m4 else 0.0):.1f}%")
        with c2:
            st.metric("M2 CPU", f"{(m2['cpu_percent'] if m2 else 0.0):.1f}%")
            st.metric("M2 RAM", f"{(m2['mem_percent'] if m2 else 0.0):.1f}%")
        with c3:
            st.plotly_chart(
                gauge_chart("M4 Cluster Health", float((m4["cpu_percent"] + m4["mem_percent"]) / 2.0) if m4 else 0.0),
                use_container_width=True,
            )
        with c4:
            st.plotly_chart(
                gauge_chart("M2 Cluster Health", float((m2["cpu_percent"] + m2["mem_percent"]) / 2.0) if m2 else 0.0),
                use_container_width=True,
            )

    with row2.container():
        st.subheader("Row 2: Algorithm Visualization")
        left, right = st.columns([3, 1])
        with left:
            if tick and tick.get("pdf"):
                render_pdf_grid(tick["pdf"])
            else:
                st.info("No PDF data yet. Run at least one tick.")
        with right:
            if tick and tick.get("confidence_ess"):
                labels = list(tick["confidence_ess"].keys())
                values = [max(0.0001, float(tick["confidence_ess"][a])) for a in labels]
                fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.6))
                fig.update_layout(title="Dynamic Weight Donut (ESS)", height=300)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No ESS data yet.")

    with row3.container():
        st.subheader("Row 3: Performance Validation (Zero-OOS Windowing)")
        rows = engine.db.load_expected_vs_actual(limit=4000)
        if rows:
            df = pd.DataFrame([dict(r) for r in rows]).sort_values("ts_ms")
            df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms")
            c1, c2 = st.columns(2)
            with c1:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df["ts"], y=df["expected_return"], mode="lines", name="Expected Return"))
                fig.add_trace(go.Scatter(x=df["ts"], y=df["actual_profit"], mode="lines", name="Actual Profit"))
                fig.update_layout(height=320, title="Expected vs Actual Profit (OOS-free)")
                st.plotly_chart(fig, use_container_width=True)
            with c2:
                accuracy = 1.0 - (df["abs_error"] / (df["actual_profit"].abs() + 1e-9))
                fig = go.Figure(
                    data=[
                        go.Scatter(
                            x=df["confidence_ess"],
                            y=accuracy,
                            mode="markers",
                            marker={"size": 6, "opacity": 0.65},
                            text=df["asset"],
                        )
                    ]
                )
                fig.update_layout(height=320, title="Confidence(ESS) vs Prediction Accuracy")
                fig.update_xaxes(title="Confidence ESS")
                fig.update_yaxes(title="Accuracy Proxy")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No realized results yet. Wait for horizon maturity.")

    if tick:
        with st.expander("Latest Decisions", expanded=False):
            st.dataframe(pd.DataFrame(tick["decisions"]), use_container_width=True)

    if auto_run:
        time.sleep(max(0.05, loop_interval))
        st.rerun()


if __name__ == "__main__":
    main()
