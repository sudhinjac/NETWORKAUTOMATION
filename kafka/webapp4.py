import streamlit as st
import json
from datetime import datetime
import matplotlib.pyplot as plt
from confluent_kafka import Consumer
import threading
import time
import re

# Kafka Configuration
conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-monitor-group',
    'auto.offset.reset': 'latest'
}

# Map BGP state to numeric Y-axis values
STATE_YVAL = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# Shared data structure
timestamps = {}
states = {}
state_labels = {}
lock = threading.Lock()

# Kafka consumer thread
def consume_kafka():
    consumer = Consumer(conf)
    consumer.subscribe(['bgp-status'])

    while True:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        try:
            data = json.loads(msg.value().decode('utf-8'))
            message = data.get("message", "")
            timestamp_ns = data.get("timestamp", 0)

            # Parse neighbor IP and state from message
            match = re.search(r"BGP_NEIGHBOR:(\S+)\s+STATE:(\S+)", message)
            if not match:
                continue

            neighbor_ip = match.group(1)
            state_str = match.group(2).upper()

            if state_str not in STATE_YVAL:
                continue

            time_obj = datetime.fromtimestamp(timestamp_ns / 1e9)

            with lock:
                if neighbor_ip not in timestamps:
                    timestamps[neighbor_ip] = []
                    states[neighbor_ip] = []
                    state_labels[neighbor_ip] = []

                timestamps[neighbor_ip].append(time_obj)
                states[neighbor_ip].append(STATE_YVAL[state_str])
                state_labels[neighbor_ip].append(state_str)

                if len(timestamps[neighbor_ip]) > 50:
                    timestamps[neighbor_ip].pop(0)
                    states[neighbor_ip].pop(0)
                    state_labels[neighbor_ip].pop(0)

        except Exception as e:
            print("⚠️ Error parsing Kafka message:", e)

# Start the Kafka consumer thread
threading.Thread(target=consume_kafka, daemon=True).start()

# Streamlit UI
st.set_page_config(page_title="BGP Session Monitor", layout="wide")
st.title("📡 BGP Session State Live Stream (Kafka)")

chart_area = st.empty()

# Polling loop
while True:
    with lock:
        if not timestamps:
            st.warning("⏳ Waiting for BGP session data from Kafka...")
        else:
            for neighbor, ts_list in timestamps.items():
                if not ts_list:
                    continue

                fig, ax = plt.subplots()
                ax.set_title(f"BGP State for Neighbor {neighbor}")
                ax.set_xlabel("Time")
                ax.set_ylabel("State")
                ax.set_ylim(-0.5, 2.5)
                ax.set_yticks([0, 1, 2])
                ax.set_yticklabels(["IDLE", "ACTIVE", "ESTABLISHED"])
                ax.tick_params(axis='x', rotation=45)

                state_vals = states[neighbor]
                label = state_labels[neighbor][-1] if state_labels[neighbor] else "IDLE"
                color = STATE_COLOR.get(label, "blue")

                ax.plot(ts_list, state_vals, marker='o', linewidth=2, color=color)

                chart_area.pyplot(fig)
    time.sleep(3)
