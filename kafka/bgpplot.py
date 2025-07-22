import streamlit as st
import pandas as pd
import json
from kafka import KafkaConsumer
from datetime import datetime
import plotly.express as px

# Kafka configuration
KAFKA_TOPIC = "bgp-telemetry"
KAFKA_BOOTSTRAP_SERVERS = ["localhost:9092"]  # Update if needed

st.set_page_config(page_title="BGP Kafka Monitor", layout="wide")

st.title("📡 BGP Session State Live Monitor")

# Initialize Kafka consumer only once
@st.cache_resource
def get_consumer():
    return KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda x: json.loads(x.decode("utf-8"))
    )

consumer = get_consumer()

# Session state to store data
if "bgp_data" not in st.session_state:
    st.session_state.bgp_data = []

# Read messages
def read_kafka_messages(max_msgs=50):
    new_msgs = []
    for msg in consumer.poll(timeout_ms=1000, max_records=max_msgs).values():
        for record in msg:
            new_msgs.append(record.value)
    return new_msgs

new_data = read_kafka_messages()
st.session_state.bgp_data.extend(new_data)

# Convert to DataFrame
if not st.session_state.bgp_data:
    st.warning("⏳ Waiting for BGP session data from Kafka...")
    st.stop()

df_raw = pd.DataFrame(st.session_state.bgp_data)
df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])

routers = df_raw["router"].unique()
selected_router = st.selectbox("Select Router", routers)

df_router = df_raw[df_raw["router"] == selected_router]

# ----------------------
# BGP Neighbors Section
# ----------------------
st.subheader("🔁 BGP Neighbor State")

bgp_records = []
for _, row in df_router.iterrows():
    for neighbor in row["bgp_neighbors"]:
        bgp_records.append({
            "timestamp": row["timestamp"],
            "router": row["router"],
            "neighbor": neighbor["ip"],
            "state": neighbor["state"]
        })

df_bgp = pd.DataFrame(bgp_records)
state_map = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
df_bgp["state_code"] = df_bgp["state"].map(state_map)

for neighbor_ip in df_bgp["neighbor"].unique():
    df_neighbor = df_bgp[df_bgp["neighbor"] == neighbor_ip]
    fig = px.line(df_neighbor, x="timestamp", y="state_code", title=f"BGP Neighbor {neighbor_ip} State", markers=True)
    fig.update_yaxes(tickvals=[0,1,2], ticktext=["IDLE", "ACTIVE", "ESTABLISHED"])
    st.plotly_chart(fig, use_container_width=True)

# ----------------------
# Interface Packets Section
# ----------------------
st.subheader("📦 Interface Packets")

iface_records = []
for _, row in df_router.iterrows():
    for iface in row["interfaces"]:
        iface_records.append({
            "timestamp": row["timestamp"],
            "interface": iface["name"],
            "in_packets": iface["in_packets"],
            "out_packets": iface["out_packets"]
        })

df_iface = pd.DataFrame(iface_records)

for iface_name in df_iface["interface"].unique():
    df_iface_i = df_iface[df_iface["interface"] == iface_name]
    
    fig1 = px.line(df_iface_i, x="timestamp", y="in_packets", title=f"Interface {iface_name} - In Packets", markers=True)
    fig2 = px.line(df_iface_i, x="timestamp", y="out_packets", title=f"Interface {iface_name} - Out Packets", markers=True)

    st.plotly_chart(fig1, use_container_width=True)
    st.plotly_chart(fig2, use_container_width=True)

st.success("✅ Live data stream updated.")