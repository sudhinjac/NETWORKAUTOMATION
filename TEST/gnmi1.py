from pygnmi.client import gNMIclient, telemetryParser

# Device connection details
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
            'sample_interval': 10000000000  # 10 seconds
        },
        {
            'path': '/interfaces/interface[name=Ethernet1]/state/oper-status',
            'mode': 'on_change',
        },
    ],
    'mode': 'stream',
    'encoding': 'json'
}

def subscribe_with_pygnmi():
    with gNMIclient(
        target=(hostname, port),
        username=username,
        password=password,
        insecure=True
    ) as client:
        print("Starting gNMI subscription stream...")
        response = client.subscribe(subscribe=subscribe_request)
        for raw_response in response:
            parsed = telemetryParser(raw_response)
            print(parsed)

# Call the function
subscribe_with_pygnmi()