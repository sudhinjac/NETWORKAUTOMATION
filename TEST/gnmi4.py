from pygnmi.client import gNMIclient
import json

# gNMI target info
host = ('192.168.255.138', '6030')
username = 'sudhin'
password = 'sudhin'

# Target path for BGP neighbor states using OpenConfig
bgp_neighbor_path = [
    '/network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor'
]

# Execute gNMI requests
if __name__ == '__main__':
    with gNMIclient(target=host, username=username, password=password, insecure=True) as gc:
        print("Getting BGP neighbor states...")
        neighbor_result = gc.get(path=bgp_neighbor_path, encoding='json')

        print("Getting Capabilities...")
        caps = gc.capabilities()

    # Write results to file
    with open("gnmi_bgp_neighbors.json", "w") as f:
        f.write("=== BGP Neighbor States ===\n")
        f.write(json.dumps(neighbor_result, indent=2) + "\n\n")

       # f.write("=== gNMI Capabilities ===\n")
       # f.write(json.dumps(caps, indent=2) + "\n")

    print("Results saved to gnmi_bgp_neighbors.json")
    print("Neighbor States:", json.dumps(neighbor_result, indent=2))
    #print("Capabilities:", json.dumps(caps, indent=2))