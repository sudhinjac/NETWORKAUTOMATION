from pygnmi.client import gNMIclient

# Variables
host = ('192.168.255.138', '6030')

# Body
if __name__ == '__main__':
    with gNMIclient(target=host, username='sudhin', password='sudhin', insecure=True) as gc:
        result = gc.get(path=['/interfaces', '/acl'])

    with gNMIclient(target=host, username='sudhin', password='sudhin', insecure=True) as gc:
        caps = gc.capabilities()

    # Write to file
    with open("gnmi_output.json", "w") as f:
        f.write("=== gNMI Get Result ===\n")
        f.write(str(result) + "\n\n")

        f.write("=== gNMI Capabilities ===\n")
        f.write(str(caps) + "\n")

    print("Output written to gnmi_output.txt")
    print(result)
    print(caps)