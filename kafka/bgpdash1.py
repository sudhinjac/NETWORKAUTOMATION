# bgp_dashboard_colored.py
import streamlit as st
# MUST be the first Streamlit call
st.set_page_config(page_title="BGP Telemetry Dashboard (Colored Grid)", layout="wide")

import pandas as pd
import json
from kafka import KafkaConsumer
from datetime import datetime, timezone
import plotly.graph_objects as go
import plotly.express as px
import time

# ----------------------
# Config
# ----------------------
KAFKA_TOPIC = "bgp-telemetry"
KAFKA_BOOTSTRAP = ["localhost:9092"]
CONSUMER_GROUP = "bgp-streamlit-colored"
MAX_STORED_MESSAGES = 2000
POLL_MAX_RECORDS = 200

# State mapping and colors
STATE_ORDER = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "lightgray", "ACTIVE": "rgba(255,100,100,0.35)", "ESTABLISHED": "rgba(100,200,100,0.35)"}
STATE_LINE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# ----------------------
# Kafka consumer (cached)
# ----------------------
@st.cache_resource
def get_consumer():
    return KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=CONSUMER_GROUP,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=1000,
    )

consumer = get_consumer()

# ----------------------
# Session storage
# ----------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = []

# ----------------------
# Helpers
# ----------------------
def parse_timestamp(ts):
    if ts is None:
        return datetime.now(timezone.utc)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except Exception:
                return datetime.now(timezone.utc)
    try:
        ts_int = int(ts)
        if ts_int > 1_000_000_000_000:
            return datetime.fromtimestamp(ts_int / 1e9, tz=timezone.utc)
        return datetime.fromtimestamp(ts_int, tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def poll_kafka(max_records=POLL_MAX_RECORDS):
    try:
        polled = consumer.poll(timeout_ms=1000, max_records=max_records)
    except Exception as e:
        st.error(f"Error polling Kafka: {e}")
        return 0
    added = 0
    for tp, recs in polled.items():
        for r in recs:
            try:
                v = r.value
                if not isinstance(v, dict):
                    continue
                ts_dt = parse_timestamp(v.get("timestamp"))
                interfaces = v.get("interfaces", []) if isinstance(v.get("interfaces", []), list) else []
                bgp_neighbors = v.get("bgp_neighbors", []) if isinstance(v.get("bgp_neighbors", []), list) else []
                msg = {
                    "router": v.get("router") or v.get("router_name") or "unknown",
                    "timestamp": ts_dt.isoformat(),
                    "interfaces": interfaces,
                    "bgp_neighbors": bgp_neighbors,
                }
                st.session_state["messages"].append(msg)
                added += 1
            except Exception as e:
                print("parse error:", e)
                continue
    if len(st.session_state["messages"]) > MAX_STORED_MESSAGES:
        st.session_state["messages"] = st.session_state["messages"][-MAX_STORED_MESSAGES:]
    return added

def build_neighbor_dataframe(messages, router):
    rows = []
    for m in messages:
        if m.get("router") != router:
            continue
        try:
            ts = datetime.fromisoformat(m.get("timestamp"))
        except Exception:
            ts = datetime.now(timezone.utc)
        for nb in m.get("bgp_neighbors", []):
            if not isinstance(nb, dict):
                continue
            ip = nb.get("neighbor_ip") or nb.get("neighbor-address") or nb.get("ip") or nb.get("neighbor") or nb.get("neighbor_addr")
            state = (nb.get("state") or nb.get("session-state") or "").upper()
            if not ip or state == "":
                continue
            if state not in STATE_ORDER:
                continue
            rows.append({"router": router, "timestamp": ts, "neighbor": ip, "state": state, "state_code": STATE_ORDER[state]})
    return pd.DataFrame(rows)

def build_interface_dataframe(messages, router):
    rows = []
    for m in messages:
        if m.get("router") != router:
            continue
        try:
            ts = datetime.fromisoformat(m.get("timestamp"))
        except Exception:
            ts = datetime.now(timezone.utc)
        for inf in m.get("interfaces", []):
            if not isinstance(inf, dict):
                continue
            name = inf.get("name") or inf.get("interface") or inf.get("interface_name") or "unknown"
            in_p = inf.get("in_packets") or inf.get("in-octets") or 0
            out_p = inf.get("out_packets") or inf.get("out-octets") or 0
            try:
                in_p = int(in_p)
            except Exception:
                in_p = 0
            try:
                out_p = int(out_p)
            except Exception:
                out_p = 0
            rows.append({"router": router, "timestamp": ts, "interface": name, "in_packets": in_p, "out_packets": out_p})
    return pd.DataFrame(rows)

def neighbor_state_bands(df_nb):
    """
    Given df_nb sorted by timestamp for a single neighbor, produce list of (start, end, state)
    for consecutive same-state intervals. end is next timestamp; last end uses last timestamp.
    """
    if df_nb.empty:
        return []
    df_nb = df_nb.sort_values("timestamp").reset_index(drop=True)
    bands = []
    start = df_nb.loc[0, "timestamp"]
    cur_state = df_nb.loc[0, "state"]
    for i in range(1, len(df_nb)):
        if df_nb.loc[i, "state"] != cur_state:
            end = df_nb.loc[i, "timestamp"]
            bands.append((start, end, cur_state))
            start = end
            cur_state = df_nb.loc[i, "state"]
    # final band: extend a bit past last point to visualize
    final_end = df_nb.loc[len(df_nb)-1, "timestamp"]
    # extend by a small delta for visibility (e.g., 1 second)
    final_end = final_end + pd.Timedelta(seconds=1)
    bands.append((start, final_end, cur_state))
    return bands

# ----------------------
# UI: Controls
# ----------------------
st.title("📡 BGP Telemetry — Colored Grid View")
control_col, info_col = st.columns([3,1])
with control_col:
    refresh = st.button("🔁 Refresh now")
    auto_refresh = st.checkbox("Auto-refresh", value=False)
    interval = st.selectbox("Interval (s)", [1,2,3,5,10], index=2)
    cols_choice = st.selectbox("Charts/row (grid columns)", [1,2,3,4], index=2)
with info_col:
    st.write("Stored messages:", len(st.session_state["messages"]))
    st.write("Kafka brokers:", ", ".join(KAFKA_BOOTSTRAP))

if refresh:
    added = poll_kafka()
    st.success(f"Polled {added} new messages")

if auto_refresh:
    added = poll_kafka()
    st.info(f"Auto-polled {added} messages")
    time.sleep(interval)
    params = st.experimental_get_query_params()
    params["_r"] = [str(time.time())]
    st.experimental_set_query_params(**params)
    st.stop()

if not st.session_state["messages"]:
    st.warning("No messages yet. Click Refresh now after your collector writes to Kafka or enable Auto-refresh.")
    st.stop()

# Build router list
routers = sorted({m.get("router") for m in st.session_state["messages"] if m.get("router")})
selected_router = st.selectbox("Select router", routers)
st.caption("Neighbor charts are colored by state: green=ESTABLISHED, red=ACTIVE, gray=IDLE. Black line shows numeric state (0/1/2).")

# Build dataframes
df_nb_all = build_neighbor_dataframe(st.session_state["messages"], selected_router)
df_if_all = build_interface_dataframe(st.session_state["messages"], selected_router)

# ----------------------
# BGP neighbor grid (colored bands)
# ----------------------
st.subheader(f"🔁 BGP Neighbors — {selected_router}")

if df_nb_all.empty:
    st.info("No BGP neighbor records for this router yet.")
else:
    neighbors = sorted(df_nb_all["neighbor"].unique())
    ncols = cols_choice
    rows = (len(neighbors) + ncols - 1) // ncols
    idx = 0
    for r in range(rows):
        cols = st.columns(ncols)
        for c in range(ncols):
            if idx >= len(neighbors):
                break
            nb = neighbors[idx]
            df_nb = df_nb_all[df_nb_all["neighbor"] == nb].sort_values("timestamp")
            fig = go.Figure()
            # add colored bands for consecutive-state intervals
            bands = neighbor_state_bands(df_nb)
            for (start, end, state) in bands:
                fig.add_vrect(
                    x0=start, x1=end,
                    fillcolor=STATE_COLOR.get(state, "lightgray"),
                    opacity=1.0,
                    layer="below",
                    line_width=0,
                )
            # add the state line
            if not df_nb.empty:
                fig.add_trace(go.Scatter(
                    x=df_nb["timestamp"],
                    y=df_nb["state_code"],
                    mode="lines+markers",
                    line=dict(color="black", width=1),
                    marker=dict(size=6),
                    name="state_code",
                    hovertemplate="%{x}<br>state: %{y}<extra></extra>",
                ))
            fig.update_yaxes(tickmode="array", tickvals=[0,1,2], ticktext=["IDLE","ACTIVE","ESTABLISHED"], range=[-0.5,2.5])
            fig.update_layout(
                title_text=f"Neighbor {nb}",
                margin=dict(l=20,r=10,t=30,b=20),
                height=260,
                showlegend=False,
            )
            cols[c].plotly_chart(fig, use_container_width=True)
            idx += 1

# ----------------------
# Interface counters
# ----------------------
st.subheader(f"📦 Interface counters — {selected_router}")
if df_if_all.empty:
    st.info("No interface records for this router yet.")
else:
    df_if_all = df_if_all.sort_values("timestamp")
    iface_names = sorted(df_if_all["interface"].dropna().unique())
    for iface in iface_names:
        df_if = df_if_all[df_if_all["interface"] == iface]
        fig_in = px.line(df_if, x="timestamp", y="in_packets", title=f"{iface} — In packets", markers=False, height=240)
        fig_out = px.line(df_if, x="timestamp", y="out_packets", title=f"{iface} — Out packets", markers=False, height=240)
        st.plotly_chart(fig_in, use_container_width=True)
        st.plotly_chart(fig_out, use_container_width=True)

# Footer
st.markdown("---")
st.write("Tips:")
st.write("- If you don't see data, ensure your collector writes canonical JSON to Kafka topic `bgp-telemetry`.")
st.write("- Example neighbor JSON entry: `{ \"neighbor_ip\": \"192.168.1.2\", \"state\": \"ESTABLISHED\" }`")
