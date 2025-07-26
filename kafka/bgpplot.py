import json
from kafka import KafkaConsumer
import streamlit as st
import pandas as pd
import time

KAFKA_TOPIC = "bgp-telemetry"
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"  # adjust if needed
REFRESH_INTERVAL = 10  # seconds

st.set_page_config(page_title="BGP Telemetry Dashboard", layout="wide")

st.title("📡 BGP Telemetry Dashboard")
st.markdown(f"Auto-refreshing every `{REFRESH_INTERVAL}` seconds. Click below to refresh manually.")

# Manual refresh button
if st.button("🔁 Refresh Now"):
    st.rerun()

# Placeholder for warning if no data
no_data_warning = st.empty()

@st.cache_data(ttl=REFRESH_INTERVAL)
def consume_kafka_messages():
    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='latest',
        enable_auto_commit=True,
        group_id='bgp-streamlit',
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
        consumer_timeout_ms=3000,
    )

    messages = []
    try:
        for msg in consumer:
            messages.append(msg.value)
    except Exception as e:
        st.error(f"Error reading from Kafka: {e}")
    finally:
        consumer.close()
    return messages

messages = consume_kafka_messages()

if not messages:
    no_data_warning.warning("⚠️ No messages received from Kafka.")
    st.stop()

no_data_warning.empty()

# Latest timestamp
latest_time = messages[-1]['timestamp']
st.subheader(f"🕒 Latest Telemetry Timestamp: `{latest_time}`")

# --- BGP Neighbors Table ---
st.markdown("### 🧭 BGP Neighbors Status")
bgp_rows = []
for msg in messages[-10:]:  # show last 10
    for neighbor in msg.get("bgp_neighbors", []):
        bgp_rows.append({
            "Router": msg.get("router", "N/A"),
            "Neighbor IP": neighbor.get("neighbor_ip", "N/A"),
            "State": neighbor.get("state", "UNKNOWN"),
            "Timestamp": msg.get("timestamp", "N/A"),
        })

if bgp_rows:
    df_bgp = pd.DataFrame(bgp_rows)
    st.dataframe(df_bgp, use_container_width=True)
else:
    st.info("No BGP neighbor data found.")

# --- Interface Packets Chart ---
st.markdown("### 📶 Interface Packet Count")
interface_rows = []
for msg in messages[-10:]:
    for iface in msg.get("interfaces", []):
        interface_rows.append({
            "Router": msg.get("router", "N/A"),
            "Interface": iface.get("name", "N/A"),
            "In Packets": iface.get("in_packets", 0),
            "Timestamp": msg.get("timestamp", "N/A"),
        })

if interface_rows:
    df_if = pd.DataFrame(interface_rows)
    df_chart = df_if.groupby(["Router", "Interface"]).agg({"In Packets": "mean"}).reset_index()
    chart = df_chart.pivot(index="Interface", columns="Router", values="In Packets").fillna(0)
    st.bar_chart(chart)
else:
    st.info("No interface packet data found.")
