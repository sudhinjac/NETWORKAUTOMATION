from pygnmi.client import gNMIclient

# gNMI target info
host = ('192.168.255.138', '6030')
username = 'sudhin'
password = 'sudhin'

# Paths for BGP status and AFTs using OpenConfig YANG models
bgp_paths = [
    '/network-instances/network-instance[name=default]/protocols/protocol[name=BGP][identifier=BGP]/bgp',
    '/network-instances/network-instance[name=default]/protocols/protocol[name=BGP][identifier=BGP]/bgp/neighbors',
    '/network-instances/network-instance[name=default]/protocols/protocol[name=BGP][identifier=BGP]/bgp/global'
]

aft_paths = [
    '/network-instances/network-instance[name=default]/afts',
    '/network-instances/network-instance[name=default]/afts/ipv4-unicast',
    '/network-instances/network-instance[name=default]/afts/ipv6-unicast'
]

# Execute gNMI requests
if __name__ == '__main__':
    with gNMIclient(target=host, username=username, password=password, insecure=True) as gc:
        print("Getting BGP data...")
        bgp_result = gc.get(path=bgp_paths)

        print("Getting AFTs data...")
        aft_result = gc.get(path=aft_paths)

        print("Getting Capabilities...")
        caps = gc.capabilities()

    # Write results to file
    with open("gnmi_output.json", "w") as f:
        f.write("=== BGP Data ===\n")
        f.write(str(bgp_result) + "\n\n")

        f.write("=== AFTs Data ===\n")
        f.write(str(aft_result) + "\n\n")

        f.write("=== gNMI Capabilities ===\n")
        f.write(str(caps) + "\n")

    print("Results saved to gnmi_output.json")
    print("BGP:", bgp_result)
    print("AFTs:", aft_result)
    print("Capabilities:", caps)