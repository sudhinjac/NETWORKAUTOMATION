#!/usr/bin/env python3
import time
import random
from concurrent import futures
import grpc
import gnmi_pb2
import gnmi_pb2_grpc

# Simulated switch state
STATE = {
    "switch": {
        "hostname": "sudhin",
        "interface": [
            {"name": "Ethernet0/1", "description": "Uplink", "speed": 1000, "mode": "trunk", "trunked-vlan": [10, 20]},
            {"name": "Ethernet0/2", "description": "Downlink", "speed": 100, "mode": "access", "access-vlan": 100},
            {"name": "Ethernet0/3", "description": "Access", "speed": 100, "mode": "access", "access-vlan": 200},
        ]
    }
}

def get_path_value(path):
    """
    Traverse STATE to find the value for a gNMI Path.
    Only returns the scalar value requested by the path.
    """
    node = STATE
    for elem in path.elem:
        if elem.name == "switch":
            node = node["switch"]
        elif elem.name == "hostname":
            return node["hostname"]
        elif elem.name == "interface":
            key = elem.key.get("name")
            iface = next((i for i in node["interface"] if i["name"] == key), None)
            node = iface
        elif elem.name == "speed":
            return node.get("speed")
        elif elem.name == "description":
            return node.get("description")
        else:
            return None
    return node

class GnmiService(gnmi_pb2_grpc.gNMIServicer):

    def Capabilities(self, request, context):
        return gnmi_pb2.CapabilityResponse(
            supported_models=[gnmi_pb2.ModelData(name="switch", organization="sudhin", version="1.0")],
            supported_encodings=[gnmi_pb2.Encoding.JSON]
        )

    def Get(self, request, context):
        notifications = []
        for path in request.path:
            val = get_path_value(path)
            if val is not None:
                # Choose the correct TypedValue type
                if isinstance(val, int):
                    typed_val = gnmi_pb2.TypedValue(int_val=val)
                elif isinstance(val, str):
                    typed_val = gnmi_pb2.TypedValue(string_val=val)
                else:
                    # fallback: convert other types to string
                    typed_val = gnmi_pb2.TypedValue(string_val=str(val))

                notif = gnmi_pb2.Notification(
                    timestamp=int(time.time() * 1e9),
                    update=[gnmi_pb2.Update(path=path, val=typed_val)]
                )
                notifications.append(notif)
        return gnmi_pb2.GetResponse(notification=notifications)

    def Subscribe(self, request_iterator, context):
        for req in request_iterator:
            if req.subscribe:
                while True:
                    updates = []
                    for path in req.subscribe.path:
                        val = get_path_value(path)
                        if val is not None:
                            if isinstance(val, int):
                                typed_val = gnmi_pb2.TypedValue(int_val=val)
                            elif isinstance(val, str):
                                typed_val = gnmi_pb2.TypedValue(string_val=val)
                            else:
                                typed_val = gnmi_pb2.TypedValue(string_val=str(val))
                            updates.append(gnmi_pb2.Update(path=path, val=typed_val))

                    notif = gnmi_pb2.Notification(
                        timestamp=int(time.time() * 1e9),
                        update=updates
                    )
                    yield gnmi_pb2.SubscribeResponse(update=notif)
                    # Simulate interface speed changes
                    for iface in STATE["switch"]["interface"]:
                        iface["speed"] += random.choice([-10, 0, 10])
                        if iface["speed"] < 0:
                            iface["speed"] = 10
                    time.sleep(5)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
    gnmi_pb2_grpc.add_gNMIServicer_to_server(GnmiService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("gNMI switch simulator running on port 50051")
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
