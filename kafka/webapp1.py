import streamlit as st
import json
from datetime import datetime
import matplotlib.pyplot as plt
from confluent_kafka import Consumer
import threading
import time

# Kafka Configuration
conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-streamlit-group',
    'auto.offset.reset': 'latest'
}

# Mapping BGP states to numeric values and colors
STATE_YVAL = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# Shared data structure for each neighbor
data = {}
data_lock = threading.Lock()

# Kafka Consumer Thread
def consume_kafka():
    consumer = Consumer(conf)
    consumer.subscribe(['bgp-status'])

    while True:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        try:
            raw_data = json.loads(msg.value().decode("utf-8"))
            ts_ns = int(raw_data.get("timestamp", 0))
            path = raw_data.get("path", {}).get("elem", [])
            value_json = json.loads(raw_data.get("value", "{}"))
            state = value_json.get("Value", {}).get("StringVal", "").upper()

            # Extract neighbor IP
            neighbor_ip = "unknown"
            for elem in path:
                if elem.get("name") == "neighbor":
                    neighbor_ip = elem.get("key", {}).get("neighbor-address", "unknown")

            if state not in STATE_YVAL:
                continue

            timestamp = datetime.fromtimestamp(ts_ns / 1e9)

            with data_lock:
                if neighbor_ip not in data:
                    data[neighbor_ip] = {"timestamps": [], "states": [], "labels": []}
                d = data[neighbor_ip]
                d["timestamps"].append(timestamp)
                d["states"].append(STATE_YVAL[state])
                d["labels"].append(state)

                # Keep only last 100 values per neighbor
                if len(d["timestamps"]) > 100:
                    d["timestamps"].pop(0)
                    d["states"].pop(0)
                    d["labels"].pop(0)

        except Exception as e:
            print("⚠️ Kafka parse error:", e)

# Start Kafka consumer thread
threading.Thread(target=consume_kafka, daemon=True).start()

# Streamlit UI
st.set_page_config(page_title="📡 BGP State Monitor", layout="wide")
st.title("📶 BGP Neighbor Session State Monitor (Kafka + Streamlit)")
chart = st.empty()

# Auto-update chart
while True:
    with data_lock:
        if not data:
            st.warning("⏳ Waiting for BGP session data from Kafka...")
        else:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.set_title("BGP Session States Over Time (Per Neighbor)")
            ax.set_xlabel("Time")
            ax.set_ylabel("State")
            ax.set_yticks(list(STATE_YVAL.values()))
            ax.set_yticklabels(list(STATE_YVAL.keys()))
            ax.set_ylim(-0.5, 2.5)
            ax.tick_params(axis='x', rotation=45)

            for neighbor_ip, d in data.items():
                if not d["timestamps"]:
                    continue
                color = STATE_COLOR.get(d["labels"][-1], "blue")
                ax.plot(d["timestamps"], d["states"], label=neighbor_ip, color=color, linewidth=2, marker='o')

            ax.legend(title="Neighbor IPs")
            chart.pyplot(fig)

    time.sleep(2)
