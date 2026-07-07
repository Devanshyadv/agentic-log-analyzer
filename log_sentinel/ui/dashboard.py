import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE = "http://localhost:8000"
REFRESH_INTERVAL = 5  # seconds between auto-refresh

st.set_page_config(
    page_title="LogSentinel",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get(path: str, params: dict = None):
    try:
        r = requests.get(f"{API_BASE}{path}", params=params or {}, timeout=3)
        return r.json() if r.ok else []
    except Exception:
        return []


def _post(path: str, payload: dict):
    try:
        r = requests.post(f"{API_BASE}{path}", json=payload, timeout=5)
        return r.json() if r.ok else {}
    except Exception:
        return {}


# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────

st.sidebar.title("🛡️ LogSentinel")
service_filter = st.sidebar.selectbox(
    "Filter by service", ["All", "nginx", "python_app", "kubernetes"]
)
level_filter = st.sidebar.selectbox(
    "Filter by level", ["All", "ERROR", "WARNING", "INFO", "DEBUG"]
)
st.sidebar.divider()

if st.sidebar.button("💉 Inject Test Anomaly (error_storm)", use_container_width=True):
    resp = _post("/inject-anomaly", {"service": "nginx", "anomaly_type": "error_storm"})
    st.sidebar.success(f"Injected: {resp.get('status', 'done')}")

anomaly_type = st.sidebar.selectbox(
    "Anomaly type", ["error_storm", "latency_spike", "memory_leak", "disk_full", "connection_pool"]
)
if st.sidebar.button("💉 Custom Inject", use_container_width=True):
    resp = _post("/inject-anomaly", {"service": "nginx", "anomaly_type": anomaly_type})
    st.sidebar.success(resp.get("status", "done"))

st.sidebar.divider()
st.sidebar.caption(f"Auto-refresh every {REFRESH_INTERVAL}s")

# ──────────────────────────────────────────────
# Fetch data
# ──────────────────────────────────────────────

params = {}
if service_filter != "All":
    params["service"] = service_filter
if level_filter != "All":
    params["level"] = level_filter

logs = _get("/logs", {**params, "limit": 200})
anomalies = _get("/anomalies", {"limit": 20})
health = _get("/health") or {}

# ──────────────────────────────────────────────
# Row 1 — Metric cards
# ──────────────────────────────────────────────

st.title("🛡️ LogSentinel — AI-Powered DevOps Co-Pilot")

c1, c2, c3, c4 = st.columns(4)
total_logs = len(logs)
error_logs = [l for l in logs if l.get("level") in ("ERROR", "CRITICAL")]
error_rate = len(error_logs) / total_logs if total_logs else 0.0
active_anomalies = len(anomalies)
last_alert_time = anomalies[-1].get("detected_at", "—") if anomalies else "—"

c1.metric("Total Logs (visible)", f"{total_logs:,}")
c2.metric("Error Rate", f"{error_rate:.1%}", delta=None)
c3.metric("Active Anomalies", active_anomalies)
c4.metric("Last Anomaly", last_alert_time[:19] if len(str(last_alert_time)) > 19 else str(last_alert_time))

st.divider()

# ──────────────────────────────────────────────
# Row 2 — Log stream + anomaly timeline
# ──────────────────────────────────────────────

col_logs, col_chart = st.columns([6, 4])

with col_logs:
    st.subheader("📋 Live Log Stream")
    if logs:
        df = pd.DataFrame(logs)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.sort_values("timestamp", ascending=False)
        if "message" in df.columns:
            df["message"] = df["message"].str[:80]

        def _row_style(row):
            if row.get("level") in ("ERROR", "CRITICAL"):
                return ["background-color: #ff4444; color: white"] * len(row)
            if row.get("level") == "WARNING":
                return ["background-color: #ffaa00; color: black"] * len(row)
            return [""] * len(row)

        display_cols = [c for c in ["timestamp", "level", "service", "message"] if c in df.columns]
        styled = df[display_cols].head(100).style.apply(_row_style, axis=1)
        st.dataframe(styled, use_container_width=True, height=420)
    else:
        st.info("No logs yet — start watching a log file or inject an anomaly.")

with col_chart:
    st.subheader("📈 Anomaly Timeline")
    if anomalies:
        chart_data = []
        for a in anomalies:
            ts = a.get("detected_at") or a.get("window_start")
            er = a.get("error_rate", a.get("features", {}).get("error_rate", 0))
            chart_data.append({"ts": ts, "error_rate": er, "is_anomaly": True})

        fig = go.Figure()
        ts_vals = [d["ts"] for d in chart_data]
        er_vals = [d["error_rate"] for d in chart_data]

        fig.add_trace(go.Scatter(
            x=ts_vals, y=er_vals, mode="lines+markers",
            name="Error Rate",
            line=dict(color="#4a90d9"),
        ))
        fig.add_trace(go.Scatter(
            x=ts_vals, y=er_vals, mode="markers",
            name="Anomaly",
            marker=dict(color="red", size=12, symbol="circle"),
            text=[a.get("severity", "") for a in anomalies],
            hovertemplate="%{text}<br>error_rate=%{y:.1%}<extra></extra>",
        ))
        fig.update_layout(
            height=420,
            margin=dict(l=0, r=0, t=20, b=0),
            yaxis_tickformat=".0%",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No anomalies detected yet.")

st.divider()

# ──────────────────────────────────────────────
# Row 3 — Latest LLM Analysis
# ──────────────────────────────────────────────

st.subheader("🤖 Latest LLM Analysis")

latest = anomalies[-1] if anomalies else None
analysis = latest.get("analysis") if latest else None

if not analysis:
    st.info("🔍 Monitoring… No anomalies detected yet.")
else:
    sev = latest.get("severity", "LOW")
    sev_color = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")

    cols = st.columns([2, 6, 2])
    cols[0].markdown(f"### {sev_color} {sev}")
    cols[1].markdown(f"**{analysis.get('anomaly_summary', '')}**")
    cols[2].metric("Confidence", f"{analysis.get('confidence', 0):.0%}")

    st.markdown(f"**Root Cause:** {analysis.get('root_cause', 'Unknown')}")

    fix_steps = analysis.get("fix_steps", [])
    if fix_steps:
        st.markdown("**Fix Steps:**")
        for i, step in enumerate(fix_steps, 1):
            st.checkbox(f"{i}. {step}", key=f"fix_{i}", value=False)

    cmds = analysis.get("run_these_commands", [])
    if cmds:
        st.markdown("**Run These Commands:**")
        st.code("\n".join(cmds), language="bash")

    similar = analysis.get("similar_incidents", [])
    if similar:
        with st.expander("🗃️ Similar Past Incidents"):
            for inc in similar:
                st.markdown(f"- {inc}")

# ──────────────────────────────────────────────
# Auto-refresh
# ──────────────────────────────────────────────

time.sleep(REFRESH_INTERVAL)
st.rerun()
