import json
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from confluent_kafka import Consumer

# Mapping state to numeric Y-values and colors
STATE_YVAL = {"IDLE": 0, "ACTIVE": 1, "ESTABLISHED": 2}
STATE_COLOR = {"IDLE": "gray", "ACTIVE": "red", "ESTABLISHED": "green"}

# Lists to store time series
timestamps = []
state_values = []

# Kafka config
conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-lineplot',
    'auto.offset.reset': 'latest'
}
consumer = Consumer(conf)
consumer.subscribe(['bgp-status'])

# Plot setup
fig, ax = plt.subplots()
line, = ax.plot([], [], lw=2, color='green')

def update(frame):
    msg = consumer.poll(1.0)
    if msg is None or msg.error():
        return line,

    try:
        data = json.loads(msg.value().decode("utf-8"))
        timestamp_ns = int(data.get("timestamp", 0))
        value_str = data.get("value", "{}")

        value_json = json.loads(value_str)
        state = value_json.get("Value", {}).get("StringVal", "").upper()

        if state in STATE_YVAL:
            time_obj = datetime.fromtimestamp(timestamp_ns / 1e9)
            timestamps.append(time_obj)
            state_values.append(STATE_YVAL[state])

            # Keep only last 50 entries
            if len(timestamps) > 50:
                timestamps.pop(0)
                state_values.pop(0)

            ax.clear()
            ax.set_title("BGP Session State Over Time")
            ax.set_xlabel("Time")
            ax.set_ylabel("State")
            ax.plot(timestamps, state_values, color=STATE_COLOR[state], marker='o')

            # Customize y-axis
            ax.set_yticks(list(STATE_YVAL.values()))
            ax.set_yticklabels(list(STATE_YVAL.keys()))
            ax.tick_params(axis='x', rotation=45)
            ax.set_ylim(-0.5, 2.5)

    except Exception as e:
        print("Error:", e)

    return line,

ani = FuncAnimation(fig, update, interval=1000)
plt.tight_layout()
plt.show()

# Cleanup
import atexit
atexit.register(lambda: consumer.close())