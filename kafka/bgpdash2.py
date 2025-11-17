# bgp_clickhouse_dashboard.py
# Streamlit dashboard that reads from ClickHouse table `net.mv_kafka_to_events`
# Expects columns: router (String), ts (DateTime), bgp_neighbors (String JSON array), interfaces (String JSON array)

import json
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
import clickhouse_connect

# ----------------------
# Page config - MUST be first Streamlit command
# ----------------------
st.set_page_config(page_title="BGP Telemetry (ClickHouse)", layout="wide")

# ----------------------
# Configuration - edit as needed
# ----------------------
CLICKHOUSE_HOST = "localhost"
CLICKHOUSE_PORT = 8123       # HTTP port used by clickhouse-connect
CLICKHOUSE_USER = "default"
CLICKHOUSE_PASS = "Sudhin12"         # set if required
CLICKHOUSE_DB = "net"
CLICKHOUSE_TABLE = "mv_kafka_to_events"

MAX_ROWS = 5000    # how many rows to fetch
STATE_ORDER = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"ESTABLISHED": "#2ecc71", "ACTIVE": "#ff6b6b", "IDLE": "#bdbdbd"}

# ----------------------
# ClickHouse client (cached)
# ----------------------
@st.cache_resource
def get_ch_client():
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASS,
        database=CLICKHOUSE_DB,
        connect_timeout=5
    )

client = get_ch_client()

# ----------------------
# UI controls
# ----------------------
st.title("📡 BGP Telemetry Dashboard — ClickHouse")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    refresh_now = st.button("🔁 Refresh now")
    auto_refresh = st.checkbox("Auto-refresh", value=False)
    refresh_interval = st.selectbox("Auto-refresh interval (s)", [1, 2, 3, 5, 10], index=2)
with c2:
    st.text(f"ClickHouse: {CLICKHOUSE_HOST}:{CLICKHOUSE_PORT}")
    st.text(f"DB: {CLICKHOUSE_DB}  Table: {CLICKHOUSE_TABLE}")
with c3:
    st.text(f"Max rows: {MAX_ROWS}")

# If auto_refresh is selected, treat it like refresh_now
if auto_refresh:
    refresh_now = True

# ----------------------
# Query ClickHouse
# ----------------------
def fetch_rows(limit=MAX_ROWS):
    # Use the exact column names from your DESCRIBE result: router, ts, bgp_neighbors, interfaces
    q = f"""
    SELECT router, ts, bgp_neighbors, interfaces
    FROM {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE}
    ORDER BY ts DESC
    LIMIT {limit}
    """
    try:
        df = client.query_df(q)
        return df
    except Exception as e:
        st.error(f"ClickHouse query failed: {e}")
        return pd.DataFrame()

if refresh_now:
    df_raw = fetch_rows()
else:
    # initial load on first run
    df_raw = fetch_rows()

if df_raw is None or df_raw.empty:
    st.warning("⚠️ No data returned from ClickHouse. Check connection, DB/table, or that collector wrote rows.")
    st.stop()

# ----------------------
# Normalize & parse JSON strings
# ----------------------
def parse_json_list(val):
    """Given a ClickHouse string that should be JSON array, return list of dicts (or [])."""
    if val is None:
        return []
    # If already list (rare), return
    if isinstance(val, list):
        return val
    s = str(val).strip()
    if s == "":
        return []
    # Try direct json.loads
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return []
    except Exception:
        # sometimes ClickHouse stores single quotes or escaped; attempt to clean common issues
        try:
            s2 = s.replace("'", '"')
            parsed = json.loads(s2)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return []

# Convert ClickHouse ts column to timezone-aware datetimes
def to_dt(v):
    if pd.isna(v):
        return datetime.now(timezone.utc)
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
    try:
        return pd.to_datetime(v, utc=True).to_pydatetime()
    except Exception:
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)

# Build normalized rows
bgp_rows = []
iface_rows = []
routers_set = set()

# ClickHouse query returned rows in descending ts order -> convert to chronological while iterating
df_raw = df_raw.reset_index(drop=True)
df_chron = df_raw.sort_values("ts").reset_index(drop=True)

for _, row in df_chron.iterrows():
    router = row.get("router") or "unknown"
    routers_set.add(router)
    ts = to_dt(row.get("ts"))

    # parse bgp_neighbors and interfaces strings (they are JSON stored as String)
    nb_list = parse_json_list(row.get("bgp_neighbors"))
    if_list = parse_json_list(row.get("interfaces"))

    for nb in nb_list:
        if not isinstance(nb, dict):
            continue
        ip = nb.get("neighbor_ip") or nb.get("neighbor") or nb.get("ip")
        state = (nb.get("state") or nb.get("session-state") or "").upper()
        if not ip or not state:
            continue
        bgp_rows.append({"router": router, "timestamp": ts, "neighbor": ip, "state": state})

    for inf in if_list:
        if not isinstance(inf, dict):
            continue
        name = inf.get("name") or inf.get("interface") or inf.get("ifname")
        in_p = inf.get("in_packets") or inf.get("in-octets") or inf.get("in") or 0
        out_p = inf.get("out_packets") or inf.get("out-octets") or inf.get("out") or 0
        # safe coercion
        try:
            in_p = int(in_p)
        except Exception:
            in_p = 0
        try:
            out_p = int(out_p)
        except Exception:
            out_p = 0
        iface_rows.append({"router": router, "timestamp": ts, "interface": name, "in_packets": in_p, "out_packets": out_p})

# DataFrames
df_bgp = pd.DataFrame(bgp_rows)
df_iface = pd.DataFrame(iface_rows)

if df_bgp.empty and df_iface.empty:
    st.warning("Parsed no BGP neighbors or interface rows. Showing a sample row for debugging:")
    st.write(df_raw.head(1).to_dict(orient="records"))
    st.stop()

# ----------------------
# Router selector
# ----------------------
routers = sorted(list(routers_set))
if not routers:
    st.warning("No router names detected.")
    st.stop()

selected_router = st.selectbox("Select router", routers)

df_bgp_r = df_bgp[df_bgp["router"] == selected_router].copy() if not df_bgp.empty else pd.DataFrame()
df_iface_r = df_iface[df_iface["router"] == selected_router].copy() if not df_iface.empty else pd.DataFrame()

# ----------------------
# Topology grid (latest state per neighbor) with color-coding
# ----------------------
st.subheader(f"Topology overview — {selected_router}")

if df_bgp_r.empty:
    st.info("No BGP neighbor records for this router yet.")
else:
    last_state = df_bgp_r.sort_values("timestamp").groupby("neighbor", as_index=False).last()
    per_row = 4
    neighs = last_state.to_dict("records")
    rows = [neighs[i:i+per_row] for i in range(0, len(neighs), per_row)]
    for row_group in rows:
        cols = st.columns(per_row)
        for i, nb in enumerate(row_group):
            ip = nb.get("neighbor", "unknown")
            state = nb.get("state", "UNKNOWN")
            ts = nb.get("timestamp")
            color = STATE_COLOR.get(state, "#ffffff")
            cols[i].markdown(
                f"<div style='padding:10px;border-radius:6px;background:{color};text-align:center'>"
                f"<b>{ip}</b><br/>{state}<br/><small>{ts}</small></div>",
                unsafe_allow_html=True
            )

# ----------------------
# BGP neighbor history (per-neighbor small charts)
# ----------------------
st.subheader(f"BGP neighbor history — {selected_router}")

if df_bgp_r.empty:
    st.info("No neighbor history to plot.")
else:
    df_bgp_r["state"] = df_bgp_r["state"].astype(str).str.upper()
    df_bgp_r = df_bgp_r[df_bgp_r["state"].isin(STATE_ORDER.keys())]
    if df_bgp_r.empty:
        st.info("Neighbor states present but none match IDLE/ACTIVE/ESTABLISHED.")
    else:
        df_bgp_r["state_code"] = df_bgp_r["state"].map(STATE_ORDER)
        df_bgp_r = df_bgp_r.sort_values("timestamp")
        neighbors = sorted(df_bgp_r["neighbor"].unique())

        # show charts in a 2-column grid
        cols_per_row = 2
        for idx, nb in enumerate(neighbors):
            if idx % cols_per_row == 0:
                chart_cols = st.columns(cols_per_row)
            df_nb = df_bgp_r[df_bgp_r["neighbor"] == nb]
            if df_nb.empty:
                continue
            fig = px.line(df_nb, x="timestamp", y="state_code", title=f"{nb}", markers=False, height=240)
            fig.update_yaxes(tickvals=[0,1,2], ticktext=["IDLE","ACTIVE","ESTABLISHED"], range=[-0.5,2.5])
            last_state = df_nb["state"].iloc[-1]
            # color-line according to last state to make it easy to spot
            fig.update_traces(line=dict(color=STATE_COLOR.get(last_state, "#333333"), width=3))
            chart_cols[idx % cols_per_row].plotly_chart(fig, use_container_width=True)

# ----------------------
# Interface counters
# ----------------------
st.subheader(f"Interface counters — {selected_router}")

if df_iface_r.empty:
    st.info("No interface counters for this router yet.")
else:
    df_iface_r = df_iface_r.sort_values("timestamp")
    for iface_name in sorted(df_iface_r["interface"].dropna().unique()):
        df_if = df_iface_r[df_iface_r["interface"] == iface_name]
        if df_if.empty:
            continue
        fig_in = px.line(df_if, x="timestamp", y="in_packets", title=f"{iface_name} — In packets", markers=False, height=300)
        fig_out = px.line(df_if, x="timestamp", y="out_packets", title=f"{iface_name} — Out packets", markers=False, height=300)
        st.plotly_chart(fig_in, use_container_width=True)
        st.plotly_chart(fig_out, use_container_width=True)

# ----------------------
# Auto-refresh: trigger a query param change to make Streamlit rerun
# ----------------------
if auto_refresh:
    time.sleep(refresh_interval)
    # update a query param to force rerun
    params = st.experimental_get_query_params()
    params["_r"] = [str(time.time())]
    st.experimental_set_query_params(**params)
    st.stop()

# Footer
st.markdown("---")
st.write("Notes:")
st.write("- This app expects `bgp_neighbors` and `interfaces` stored as JSON strings (String column).")
st.write("- If you store them as ClickHouse arrays/nested types, tell me your exact schema and I will adapt the parser.")
