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
        metadata = (("username", username), ("password", password))
        channel = grpc.insecure_channel(f"{ip}:6030")
        stub = gnmi_pb2_grpc.gNMIStub(channel)

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
            for ip_addr, data in neighbor.items():
                status = data.get("state", {}).get("session-state", "unknown")
                result += f"- Neighbor: {ip_addr} | Session State: {status}\n"

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
    description="Checks BGP neighbor status using gNMI. Input must be a JSON string with 'ip', 'username', 'password'."
)

# -------- LangChain Agent (DeepSeek via Ollama) --------
llm = ChatOllama(model="deepseek-r1:14b", temperature=0.2)

agent = initialize_agent(
    tools=[check_bgp_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
    handle_parsing_errors=True  # ✅ Prevents LLM output parsing failure
)

# -------- Run the agent --------
if __name__ == "__main__":
    input_data = {
        "ip": "192.168.255.138",
        "username": "sudhin",
        "password": "sudhin"
    }

    # ✅ Explicit prompt to guide the LLM
    prompt = (
        "You are a network automation assistant.\n"
        "Use the `check_bgp_status` tool with the following JSON input:\n"
        f"{json.dumps(input_data)}\n"
        "Return the BGP neighbor session status."
    )

    result = agent.run(prompt)
    print("\n🔍 Final Output:\n", result)
