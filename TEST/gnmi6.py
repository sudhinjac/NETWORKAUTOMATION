import time
import csv
import re
from datetime import datetime, timezone
from pygnmi.client import gNMIclient
import matplotlib.pyplot as plt
import pandas as pd

# Device connection details
TARGET = ("192.168.255.138", 6030)
USERNAME = "sudhin"
PASSWORD = "sudhin"
POLL_INTERVAL = 10  # seconds
CSV_FILE = "bgp_neighbors_poll.csv"

# gNMI path to fetch all BGP neighbors' session states
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
    ) as client, open(CSV_FILE, mode="w", newline="") as csvfile:

        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "neighbor-address", "session-state"])

        for _ in range(6):  # poll 6 times = 60 seconds if interval is 10 sec
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

            csvfile.flush()
            time.sleep(POLL_INTERVAL)

def plot_bgp_states():
    df = pd.read_csv(CSV_FILE, parse_dates=["timestamp"])
    df["session-state"] = df["session-state"].str.capitalize()

    # Group by timestamp and count each state
    pivot = df.groupby(["timestamp", "session-state"]).size().unstack(fill_value=0)

    # Plot
    pivot.plot(marker='o')
    plt.title("BGP Neighbor Session States Over Time")
    plt.xlabel("Timestamp")
    plt.ylabel("Count")
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.legend(title="Session State")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    poll_bgp_neighbors()
    plot_bgp_states()