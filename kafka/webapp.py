import streamlit as st
import json
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from confluent_kafka import Consumer
import threading
import time

# Kafka Configuration
conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-streamlit',
    'auto.offset.reset': 'latest'
}

# Mapping BGP states
STATE_YVAL = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# Shared Data
timestamps = []
state_values = []
state_labels = []
lock = threading.Lock()

# Kafka Consumer Thread
def consume_kafka():
    consumer = Consumer(conf)
    consumer.subscribe(['bgp-status'])
    while True:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        try:
            data = json.loads(msg.value().decode("utf-8"))
            ts_ns = int(data.get("timestamp", 0))
            val_str = data.get("value", "{}")
            val_json = json.loads(val_str)
            state = val_json.get("Value", {}).get("StringVal", "").upper()

            if state in STATE_YVAL:
                time_obj = datetime.fromtimestamp(ts_ns / 1e9)
                with lock:
                    timestamps.append(time_obj)
                    state_values.append(STATE_YVAL[state])
                    state_labels.append(state)

                    # Keep last 50 values
                    if len(timestamps) > 50:
                        timestamps.pop(0)
                        state_values.pop(0)
                        state_labels.pop(0)
        except Exception as e:
            print("Error:", e)

# Start Kafka thread
threading.Thread(target=consume_kafka, daemon=True).start()

# Streamlit UI
st.set_page_config(page_title="BGP Session Monitor", layout="wide")
st.title("📡 BGP Session State Live Stream (Kafka)")

chart = st.empty()

while True:
    with lock:
        if timestamps:
            fig, ax = plt.subplots()
            ax.set_title("BGP Session State Over Time")
            ax.set_xlabel("Time")
            ax.set_ylabel("State")
            ax.set_ylim(-0.5, 2.5)
            ax.set_yticks(list(STATE_YVAL.values()))
            ax.set_yticklabels(list(STATE_YVAL.keys()))
            ax.tick_params(axis='x', rotation=45)

            color = STATE_COLOR.get(state_labels[-1], "blue")
            ax.plot(timestamps, state_values, color=color, marker='o', linewidth=2)

            chart.pyplot(fig)
    time.sleep(2)