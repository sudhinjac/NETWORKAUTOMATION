import time
import csv
import threading
import re
from datetime import datetime, timezone
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import Counter, deque

from pygnmi.client import gNMIclient

# Device connection details
TARGET = ("192.168.255.138", 6030)
USERNAME = "sudhin"
PASSWORD = "sudhin"
CSV_FILE = "bgp_neighbors_poll.csv"
POLL_INTERVAL = 10  # seconds

# gNMI path for BGP session state
PATH = [
    "network-instances/network-instance[name=default]/"
    "protocols/protocol[identifier=BGP][name=BGP]/"
    "bgp/neighbors/neighbor/state/session-state"
]

# Thread-safe queue to store latest BGP state counts
state_data = deque(maxlen=100)

# To store CSV writing lock
csv_lock = threading.Lock()

def extract_neighbor_from_path(path_str):
    """Extract neighbor IP from gNMI path string."""
    match = re.search(r"neighbor\[neighbor-address=(.*?)\]", path_str)
    return match.group(1) if match else "unknown"

def poll_bgp_neighbors():
    """Poll BGP neighbors continuously and write to CSV."""
    with gNMIclient(
        target=TARGET,
        username=USERNAME,
        password=PASSWORD,
        insecure=True,
    ) as client, open(CSV_FILE, mode="w", newline="") as csvfile:

        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "neighbor-address", "session-state"])

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

            # Count states for live plot
            state_counter = Counter()

            for notif in notifications:
                updates = notif.get("update", [])
                for update in updates:
                    path = update.get("path", "")
                    neighbor_address = extract_neighbor_from_path(path)

                    val = update.get("val", {})
                    session_state = val.get("session-state") if isinstance(val, dict) else str(val)

                    if neighbor_address and session_state:
                        print(f"{timestamp} - Neighbor: {neighbor_address}, State: {session_state}")

                        with csv_lock:
                            writer.writerow([timestamp, neighbor_address, session_state])

                        state_counter[session_state.lower()] += 1

            csvfile.flush()
            state_data.append(state_counter)
            time.sleep(POLL_INTERVAL)

def plot_bgp_states():
    """Plot live BGP states counts from shared state_data."""
    plt.style.use('ggplot')
    fig, ax = plt.subplots()
    ax.set_title("Live BGP Neighbor Session States")
    ax.set_xlabel("Time (latest polls)")
    ax.set_ylabel("Count")

    # States we want to track
    tracked_states = ["established", "active", "connect", "init", "idle", "openconfirm", "opensent"]

    # Store lines for each state
    lines = {}
    for state in tracked_states:
        lines[state], = ax.plot([], [], label=state.capitalize())

    ax.legend(loc='upper left')
    ax.set_ylim(0, 10)  # adjust max count as needed
    ax.set_xlim(0, 50)  # number of points to show on X-axis

    def update(frame):
        # frame is ignored; update from state_data deque
        xdata = list(range(-len(state_data)+1, 1))  # negative time steps: -49 ... 0
        for state in tracked_states:
            ydata = [counts.get(state, 0) for counts in state_data]
            lines[state].set_data(xdata, ydata)
        return lines.values()

    ani = FuncAnimation(fig, update, interval=1000)
    plt.show()

if __name__ == "__main__":
    # Run polling in background thread
    polling_thread = threading.Thread(target=poll_bgp_neighbors, daemon=True)
    polling_thread.start()

    # Start live plotting in main thread
    plot_bgp_states()