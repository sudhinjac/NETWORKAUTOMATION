from pygnmi.client import gNMIclient, telemetryParser
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import time

# Device info
username = "sudhin"
password = "sudhin"
hostname = "192.168.255.138"
port = "6030"

# Subscription request
subscribe_request = {
    'subscription': [
        {
            'path': '/interfaces/interface[name=Ethernet1]/state/counters/in-octets',
            'mode': 'sample',
            'sample_interval': 1000000000  # 1 second
        },
    ],
    'mode': 'stream',
    'encoding': 'json'
}

# Lists to store plot data
times = []
values = []

plt.style.use("seaborn-v0_8-darkgrid")
fig, ax = plt.subplots()
line, = ax.plot_date(times, values, linestyle='solid', marker=None)
ax.set_title("Live In-Octets Counter")
ax.set_xlabel("Time")
ax.set_ylabel("In-Octets")
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))

plt.tight_layout()
plt.ion()
plt.show()

def subscribe_and_plot():
    with gNMIclient(
        target=(hostname, port),
        username=username,
        password=password,
        insecure=True
    ) as client:
        print("Subscribed...")
        response = client.subscribe(subscribe=subscribe_request)
        for raw in response:
            parsed = telemetryParser(raw)
            try:
                # Extract timestamp and in-octets value
                updates = parsed.get("update", {}).get("update", [])
                timestamp_ns = parsed.get("update", {}).get("timestamp")

                for item in updates:
                    path = item["path"]
                    val = item["val"]

                    if "in-octets" in str(path):
                        timestamp = datetime.fromtimestamp(timestamp_ns / 1e9)
                        print(f"{timestamp} → {val}")

                        times.append(timestamp)
                        values.append(val)

                        # Limit to last 50 points
                        times_trimmed = times[-50:]
                        values_trimmed = values[-50:]

                        line.set_data(times_trimmed, values_trimmed)
                        ax.relim()
                        ax.autoscale_view()

                        plt.gcf().autofmt_xdate()
                        plt.pause(0.01)
            except Exception as e:
                print(f"Error parsing response: {e}")
                continue

subscribe_and_plot()