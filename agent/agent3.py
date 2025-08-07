import grpc
import json
from langchain.agents import Tool, initialize_agent
from langchain.agents.agent_types import AgentType
from langchain_ollama import ChatOllama
from google.protobuf.json_format import MessageToDict
from gnmi.proto import gnmi_pb2, gnmi_pb2_grpc

# -------- gNMI Logic (no TLS) --------
def fetch_bgp_neighbors(ip, username, password):
    try:
        # Metadata for authentication (if required by gNMI server)
        metadata = (("username", username), ("password", password))

        # Open insecure gRPC channel
        channel = grpc.insecure_channel(f"{ip}:50051")
        stub = gnmi_pb2_grpc.gNMIStub(channel)

        # Set the BGP neighbors path
        path = gnmi_pb2.Path(elem=[
            gnmi_pb2.PathElem(name="network-instances"),
            gnmi_pb2.PathElem(name="network-instance", key={"name": "default"}),
            gnmi_pb2.PathElem(name="protocols"),
            gnmi_pb2.PathElem(name="protocol", key={"identifier": "BGP", "name": "default"}),
            gnmi_pb2.PathElem(name="bgp"),
            gnmi_pb2.PathElem(name="neighbors")
        ])

        get_request = gnmi_pb2.GetRequest(
            path=[path],
            type=gnmi_pb2.GetRequest.DataType.Value("ALL"),
            encoding=gnmi_pb2.Encoding.Value("JSON_IETF")
        )

        # Send the gNMI Get request
        response = stub.Get(get_request, metadata=metadata)
        neighbors_info = []

        for notif in response.notification:
            for update in notif.update:
                neighbor_data = MessageToDict(update.val)
                neighbors_info.append(neighbor_data)

        if not neighbors_info:
            return "⚠️ No BGP neighbors found."

        result = "✅ BGP Neighbors:\n"
        for neighbor in neighbors_info:
            for ip, data in neighbor.items():
                status = data.get("state", {}).get("session-state", "unknown")
                result += f"- Neighbor: {ip} | Session State: {status}\n"

        return result

    except grpc.RpcError as e:
        return f"[gRPC Error] Could not fetch BGP neighbors: {e}"
    except Exception as ex:
        return f"[Error] Unexpected failure: {ex}"

# -------- LangChain Tool wrapper --------
def wrapped_check_bgp_status(input_str: str) -> str:
    try:
        params = json.loads(input_str)
        return fetch_bgp_neighbors(params["ip"], params["username"], params["password"])
    except Exception as e:
        return f"❌ Invalid input: {e}"

check_bgp_tool = Tool(
    name="check_bgp_status",
    func=wrapped_check_bgp_status,
    description="Checks BGP status via gNMI. Input must be a JSON string with 'ip', 'username', 'password'."
)

# -------- LangChain Agent (DeepSeek or LLaMA) --------
llm = ChatOllama(model="deepseek-coder:6.7b", temperature=0.2)

agent = initialize_agent(
    tools=[check_bgp_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# -------- Run the agent --------
if __name__ == "__main__":
    input_data = {
        "ip": "192.168.255.138",
        "username": "sudhin",
        "password": "sudhin"
    }

    prompt = f"Check the BGP neighbor status using this input: {json.dumps(input_data)}"
    result = agent.run(prompt)
    print("\n🔍 Final Output:\n", result)
