import streamlit as st
import matplotlib.pyplot as plt
from confluent_kafka import Consumer
from datetime import datetime
import threading
import time
import json
import re

# Kafka configuration
conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-graph-group',
    'auto.offset.reset': 'earliest'
}

# Mapping BGP states to Y-axis values
STATE_YVAL = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# Shared data per neighbor
timestamps = {}        # Dict[str, List[datetime]]
state_values = {}      # Dict[str, List[int]]
state_labels = {}      # Dict[str, List[str]]
lock = threading.Lock()

def consume_kafka():
    consumer = Consumer(conf)
    consumer.subscribe(['bgp-status'])

    while True:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue

        try:
            data = json.loads(msg.value().decode("utf-8"))
            raw_msg = data.get("message", "")
            ts_ns = int(data.get("timestamp", 0))

            # Extract IP and state using regex
            match = re.match(r"BGP_NEIGHBOR:(\S+) STATE:(\S+)", raw_msg)
            if not match:
                continue
            neighbor_ip, state = match.groups()
            state = state.upper()

            if state not in STATE_YVAL:
                continue

            ts = datetime.fromtimestamp(ts_ns / 1e9)

            with lock:
                if neighbor_ip not in timestamps:
                    timestamps[neighbor_ip] = []
                    state_values[neighbor_ip] = []
                    state_labels[neighbor_ip] = []

                timestamps[neighbor_ip].append(ts)
                state_values[neighbor_ip].append(STATE_YVAL[state])
                state_labels[neighbor_ip].append(state)

                # Keep only last 100 records
                if len(timestamps[neighbor_ip]) > 100:
                    timestamps[neighbor_ip].pop(0)
                    state_values[neighbor_ip].pop(0)
                    state_labels[neighbor_ip].pop(0)

        except Exception as e:
            print("⚠️ Kafka parse error:", e)

# Start Kafka consumer thread
threading.Thread(target=consume_kafka, daemon=True).start()

# Streamlit UI
st.set_page_config(page_title="BGP Status Monitor", layout="wide")
st.title("📡 BGP Session State Live Stream from Kafka")

chart_area = st.empty()

while True:
    with lock:
        if not timestamps:
            st.info("⏳ Waiting for BGP session data from Kafka...")
        else:
            fig, axs = plt.subplots(len(timestamps), 1, figsize=(10, 4 * len(timestamps)))
            if len(timestamps) == 1:
                axs = [axs]  # Make iterable if only one plot

            for i, neighbor in enumerate(timestamps):
                ax = axs[i]
                ax.set_title(f"Neighbor: {neighbor}")
                ax.set_xlabel("Time")
                ax.set_ylabel("BGP State")
                ax.set_ylim(-0.5, 2.5)
                ax.set_yticks(list(STATE_YVAL.values()))
                ax.set_yticklabels(list(STATE_YVAL.keys()))
                ax.tick_params(axis='x', rotation=45)

                color = STATE_COLOR.get(state_labels[neighbor][-1], "blue")
                ax.plot(timestamps[neighbor], state_values[neighbor], color=color, linewidth=2, marker='o')

            plt.tight_layout()
            chart_area.pyplot(fig)

    time.sleep(2)
