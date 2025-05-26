import time
import csv
import re
import threading
from datetime import datetime, timezone
from pygnmi.client import gNMIclient
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Connection Details
TARGET = ("192.168.255.138", 6030)
USERNAME = "sudhin"
PASSWORD = "sudhin"
POLL_INTERVAL = 10  # seconds
CSV_FILE = "bgp_neighbors_poll.csv"

# gNMI path to fetch BGP session state of all neighbors
PATH = [
    "network-instances/network-instance[name=default]/"
    "protocols/protocol[identifier=BGP][name=BGP]/"
    "bgp/neighbors/neighbor/state/session-state"
]

def extract_neighbor_from_path(path_str):
    match = re.search(r"neighbor\[neighbor-address=(.*?)\]", path_str)
    return match.group(1) if match else "unknown"

def poll_bgp_neighbors():
    with gNMIclient(
        target=TARGET,
        username=USERNAME,
        password=PASSWORD,
        insecure=True
    ) as client:

        # Create CSV with header if it doesn't exist
        try:
            with open(CSV_FILE, "x", newline="") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["timestamp", "neighbor-address", "session-state"])
        except FileExistsError:
            pass

        while True:
            timestamp = datetime.now(timezone.utc).isoformat()

            try:
                response = client.get(path=PATH, encoding="json")
            except Exception as e:
                print(f"{timestamp} - Error: {e}")
                time.sleep(POLL_INTERVAL)
                continue

            notifications = response.get("notification", [])
            if not notifications:
                print(f"{timestamp} - No data received")
                time.sleep(POLL_INTERVAL)
                continue

            with open(CSV_FILE, mode="a", newline="") as csvfile:
                writer = csv.writer(csvfile)

                for notif in notifications:
                    updates = notif.get("update", [])
                    for update in updates:
                        path = update.get("path", "")
                        neighbor_address = extract_neighbor_from_path(path)

                        val = update.get("val", {})
                        session_state = val.get("session-state") if isinstance(val, dict) else str(val)

                        if neighbor_address and session_state:
                            print(f"{timestamp} - Neighbor: {neighbor_address}, State: {session_state}")
                            writer.writerow([timestamp, neighbor_address, session_state])

            time.sleep(POLL_INTERVAL)

def plot_bgp_states():
    fig, ax = plt.subplots(figsize=(10, 6))

    def update(frame):
        try:
            df = pd.read_csv(CSV_FILE, parse_dates=["timestamp"])

            # Clean session-state strings to consistent title-case
            df["session-state"] = df["session-state"].str.strip().str.capitalize()

            # Pivot the data to count how many neighbors in each state at each timestamp
            pivot = df.groupby(["timestamp", "session-state"]).size().unstack(fill_value=0)

            ax.clear()
            pivot.plot(ax=ax, marker='o', linewidth=2)

            ax.set_title("Live BGP Neighbor Session States Over Time")
            ax.set_xlabel("Timestamp (UTC)")
            ax.set_ylabel("Neighbor Count")
            ax.tick_params(axis='x', rotation=45)
            ax.legend(title="BGP Session State", loc='upper left')
            ax.grid(True)
            plt.tight_layout()
        except Exception as e:
            print(f"[Plot] Error: {e}")

    ani = FuncAnimation(fig, update, interval=10000)  # Refresh every 10 seconds
    plt.show()

if __name__ == "__main__":
    # Run polling in a background thread
    threading.Thread(target=poll_bgp_neighbors, daemon=True).start()

    # Start the live graph in the main thread
    plot_bgp_states()