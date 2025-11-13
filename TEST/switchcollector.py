#!/usr/bin/env python3
import json
from pygnmi.client import gNMIclient, gNMIException

# gNMI target
TARGET = {
    'address': '127.0.0.1',
    'port': '50051',
    'username': '',
    'password': '',
    'insecure': True
}

# Paths for GET
GET_PATHS = [
    "/switch/hostname",
    "/switch/interface[name=Ethernet0/1]/speed",
    "/switch/interface[name=Ethernet0/2]/speed",
    "/switch/interface[name=Ethernet0/3]/speed",
]

# Paths for subscription
SUBSCRIBE_PATHS = [
    "/switch/interface[name=Ethernet0/1]/speed",
    "/switch/interface[name=Ethernet0/2]/speed",
    "/switch/interface[name=Ethernet0/3]/speed",
]

def main():
    print(f"Connecting to gNMI simulator at {TARGET['address']}:{TARGET['port']}\n")
    try:
        with gNMIclient(
            target=(TARGET['address'], TARGET['port']),
            username=TARGET['username'],
            password=TARGET['password'],
            insecure=True,
            debug=True
        ) as gc:

            # Capabilities
            print("--- Capabilities ---")
            capabilities = gc.capabilities()
            print(capabilities, "\n")

            # GET requests
            print("--- Fetch switch state using Get ---")
            for path in GET_PATHS:
                try:
                    result = gc.get(path, encoding='json')
                    for notif in result.get('notification', []):
                        for update in notif.get('update', []):
                            val = update.get('val')
                            if val:
                                # Handle json_val or string_val
                                if 'json_val' in val:
                                    data = json.loads(val['json_val'])
                                elif 'string_val' in val:
                                    data = json.loads(val['string_val'])
                                else:
                                    data = val
                                print(f"GET result for {path}:")
                                print(json.dumps(data, indent=2))
                except gNMIException as e:
                    print(f"Error during GET for path {path}: {e}")

            # SUBSCRIBE
            print("\n--- Subscribe to interface speeds (press Ctrl+C to stop) ---")
            try:
                for response in gc.subscribe(SUBSCRIBE_PATHS):
                    for notif in response.get('update', []):
                        val = notif.get('val')
                        if val:
                            if 'json_val' in val:
                                data = json.loads(val['json_val'])
                            elif 'string_val' in val:
                                data = json.loads(val['string_val'])
                            else:
                                data = val
                            for iface in data['switch']['interface']:
                                print(f"Interface {iface['name']} speed: {iface['speed']}")
            except KeyboardInterrupt:
                print("Subscription stopped by user.")

    except Exception as e:
        print(f"Failed to connect or run gNMI client: {e}")

if __name__ == "__main__":
    main()
