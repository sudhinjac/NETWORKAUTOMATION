import streamlit as st
# Must call set_page_config as the first Streamlit command
st.set_page_config(page_title="BGP Telemetry Dashboard", layout="wide")

import pandas as pd
import json
from kafka import KafkaConsumer
from datetime import datetime, timezone
import plotly.express as px
import time

# ----------------------
# Config
# ----------------------
KAFKA_TOPIC = "bgp-telemetry"
KAFKA_BOOTSTRAP = ["localhost:9092"]  # adjust if needed
CONSUMER_GROUP = "bgp-streamlit-dashboard"
MAX_STORED_MESSAGES = 2000           # keep last N messages in session state
POLL_MAX_RECORDS = 200               # max records to poll each refresh

# State mapping for plotting
STATE_ORDER = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_NAMES = {v: k for k, v in STATE_ORDER.items()}

# ----------------------
# Cached Kafka consumer (one per app instance)
# ----------------------
@st.cache_resource
def get_consumer():
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=1000
        )
        return consumer
    except Exception as e:
        # Let UI show error
        st.error(f"Failed creating Kafka consumer: {e}")
        raise

# instantiate consumer
consumer = get_consumer()

# ----------------------
# Session state for messages
# ----------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = []  # list of parsed messages (dicts)

# ----------------------
# Helpers
# ----------------------
def parse_timestamp(ts):
    """Normalize timestamp to a timezone-aware datetime."""
    if ts is None:
        return datetime.now(timezone.utc)
    # RFC3339 string
    if isinstance(ts, str):
        try:
            # handle trailing Z
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            try:
                # fallback parse with common formats
                return datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except Exception:
                return datetime.now(timezone.utc)
    # numeric: seconds or nanoseconds
    try:
        ts_int = int(ts)
        if ts_int > 1_000_000_000_000:  # likely nanoseconds
            return datetime.fromtimestamp(ts_int / 1e9, tz=timezone.utc)
        # else seconds
        return datetime.fromtimestamp(ts_int, tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)

def poll_kafka(max_records=POLL_MAX_RECORDS):
    """Poll Kafka and append parsed messages to session_state['messages']. Returns count."""
    try:
        polled = consumer.poll(timeout_ms=1000, max_records=max_records)
    except Exception as e:
        st.error(f"Error polling Kafka: {e}")
        return 0

    count = 0
    for tp, records in polled.items():
        for rec in records:
            try:
                val = rec.value
                # Expect canonical JSON: {router, timestamp, interfaces: [...], bgp_neighbors: [...] }
                if not isinstance(val, dict):
                    continue

                ts_dt = parse_timestamp(val.get("timestamp"))

                interfaces = val.get("interfaces", [])
                bgp_neighbors = val.get("bgp_neighbors", [])

                msg = {
                    "router": val.get("router") or val.get("router_name") or "unknown",
                    "timestamp": ts_dt.isoformat(),
                    "interfaces": interfaces if isinstance(interfaces, list) else [],
                    "bgp_neighbors": bgp_neighbors if isinstance(bgp_neighbors, list) else []
                }

                st.session_state["messages"].append(msg)
                count += 1
            except Exception as e:
                # skip problematic message but log to console
                print("Kafka message parse error:", e)
                continue

    # keep only last N messages
    if len(st.session_state["messages"]) > MAX_STORED_MESSAGES:
        st.session_state["messages"] = st.session_state["messages"][-MAX_STORED_MESSAGES:]
    return count

# ----------------------
# UI: Header / Controls
# ----------------------
st.title(f"📡 BGP Telemetry Dashboard — topic: {KAFKA_TOPIC}")

col_control, col_info = st.columns([3, 1])
with col_control:
    refresh_now = st.button("🔁 Refresh now")
    auto_refresh = st.checkbox("Auto-refresh", value=False)
    refresh_interval = st.selectbox("Interval (seconds)", [1, 2, 3, 5, 10], index=2)

with col_info:
    st.write("Messages stored:", len(st.session_state["messages"]))
    st.write("Kafka brokers:", ", ".join(KAFKA_BOOTSTRAP))

# If refresh_now pressed or auto_refresh true -> poll
if refresh_now:
    new = poll_kafka()
    st.success(f"Polled {new} new messages from Kafka")

if auto_refresh:
    # poll once now, then sleep for interval and force rerun via query param
    new = poll_kafka()
    st.info(f"Auto-refreshed — polled {new} messages")
    time.sleep(refresh_interval)
    params = st.experimental_get_query_params()
    params["_r"] = [str(time.time())]
    st.experimental_set_query_params(**params)
    st.stop()

# ----------------------
# Build DataFrames from stored messages
# ----------------------
if not st.session_state["messages"]:
    st.warning("⏳ No data yet — click *Refresh now* after your collector writes to Kafka or enable Auto-refresh.")
    st.stop()

# Convert stored messages -> DataFrame rows for BGP neighbors and interfaces
bgp_rows = []
iface_rows = []
router_list = set()

for m in st.session_state["messages"]:
    router = m.get("router", "unknown")
    router_list.add(router)
    try:
        ts = datetime.fromisoformat(m.get("timestamp"))
    except Exception:
        ts = datetime.now(timezone.utc)
    # neighbors: list of {neighbor_ip, state}
    for nb in m.get("bgp_neighbors", []):
        if isinstance(nb, dict):
            ip = nb.get("neighbor_ip") or nb.get("neighbor-address") or nb.get("ip") or nb.get("neighbor") or nb.get("neighbor_addr")
            state = (nb.get("state") or nb.get("session-state") or "").upper()
            if not ip or state == "":
                continue
            bgp_rows.append({"router": router, "timestamp": ts, "neighbor": ip, "state": state})
    # interfaces: list of {name, in_packets, out_packets} or {in-octets, out-octets, name}
    for inf in m.get("interfaces", []):
        if isinstance(inf, dict):
            name = inf.get("name") or inf.get("interface") or inf.get("interface_name")
            in_p = inf.get("in_packets") or inf.get("in-octets") or inf.get("inOctets") or 0
            out_p = inf.get("out_packets") or inf.get("out-octets") or inf.get("outOctets") or 0
            try:
                in_p = int(in_p)
            except Exception:
                in_p = 0
            try:
                out_p = int(out_p)
            except Exception:
                out_p = 0
            if not name:
                name = "unknown"
            iface_rows.append({"router": router, "timestamp": ts, "interface": name, "in_packets": in_p, "out_packets": out_p})

# Create dataframes
df_bgp = pd.DataFrame(bgp_rows)
df_iface = pd.DataFrame(iface_rows)

# Router selector
routers = sorted(list(router_list))
if not routers:
    st.warning("No router names found in messages.")
    st.stop()

selected_router = st.selectbox("Select router", routers)

# Filter for selected router
df_bgp_r = df_bgp[df_bgp["router"] == selected_router].copy() if not df_bgp.empty else pd.DataFrame()
df_iface_r = df_iface[df_iface["router"] == selected_router].copy() if not df_iface.empty else pd.DataFrame()

# ----------------------
# BGP Neighbor Plots
# ----------------------
st.subheader(f"🔁 BGP Neighbors — {selected_router}")

if df_bgp_r.empty:
    st.info("No BGP neighbor records for this router yet.")
else:
    df_bgp_r["state"] = df_bgp_r["state"].astype(str).str.upper()
    df_bgp_r = df_bgp_r[df_bgp_r["state"].isin(STATE_ORDER.keys())]
    if df_bgp_r.empty:
        st.info("Neighbor states present but none match IDLE/ACTIVE/ESTABLISHED.")
    else:
        df_bgp_r["state_code"] = df_bgp_r["state"].map(STATE_ORDER)
        df_bgp_r = df_bgp_r.sort_values("timestamp")

        neighbors = df_bgp_r["neighbor"].unique()
        for nb in sorted(neighbors):
            df_nb = df_bgp_r[df_bgp_r["neighbor"] == nb]
            if df_nb.empty:
                continue
            fig = px.line(df_nb, x="timestamp", y="state_code", title=f"Neighbor {nb}", markers=False, height=240)
            fig.update_yaxes(tickmode="array", tickvals=[0,1,2], ticktext=["IDLE","ACTIVE","ESTABLISHED"], range=[-0.5,2.5])
            fig.update_xaxes(showgrid=True)
            st.plotly_chart(fig, use_container_width=True)

# ----------------------
# Interface Plots
# ----------------------
st.subheader(f"📦 Interface counters — {selected_router}")

if df_iface_r.empty:
    st.info("No interface records for this router yet.")
else:
    df_iface_r = df_iface_r.sort_values("timestamp")
    for iface_name in sorted(df_iface_r["interface"].dropna().unique()):
        df_if = df_iface_r[df_iface_r["interface"] == iface_name]
        if df_if.empty:
            continue
        fig_in = px.line(df_if, x="timestamp", y="in_packets", title=f"{iface_name} — In packets", markers=False, height=300)
        fig_in.update_xaxes(showgrid=True)
        fig_out = px.line(df_if, x="timestamp", y="out_packets", title=f"{iface_name} — Out packets", markers=False, height=300)
        fig_out.update_xaxes(showgrid=True)

        st.plotly_chart(fig_in, use_container_width=True)
        st.plotly_chart(fig_out, use_container_width=True)

# ----------------------
# Footer / tips
# ----------------------
st.markdown("---")
st.write("Tips:")
st.write("- If you don't see data, ensure your collector is writing canonical JSON to Kafka topic `bgp-telemetry` on the broker listed above.")
st.write("- Click **Refresh now** to poll new messages, or enable **Auto-refresh**.")
st.write("- If your dataset is large, increase `MAX_STORED_MESSAGES` or filter the collector to reduce traffic.")
