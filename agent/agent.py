from langchain.agents import initialize_agent, Tool
from langchain.agents.agent_types import AgentType
from langchain_ollama import ChatOllama
from pygnmi.client import gNMIclient
import json
import socket

# --------- Actual gNMI BGP Check Logic ---------
def check_bgp_and_troubleshoot(ip, username, password):
    try:
        # Connect to router with gNMI (no TLS)
        with gNMIclient(target=(ip, 6030), username=username, password=password, insecure=True) as client:
            # Fetch BGP neighbor state (Cisco/Juniper-style paths; adjust based on device)
            paths = [
                "/network-instances/network-instance[name=default]/protocols/protocol[name=BGP]/bgp/neighbors"
            ]
            response = client.get(path=paths, encoding='json', data_type='STATE')
            
            results = []
            neighbors_data = response.get("notification", [])[0].get("update", [])
            for neighbor in neighbors_data:
                address = neighbor["path"]["elem"][-1]["key"]["neighbor-address"]
                state = neighbor["val"].get("session-state", "UNKNOWN")
                output = f"BGP Neighbor {address} is in state: {state}"

                # Troubleshoot if not Established
                if state != "ESTABLISHED":
                    output += " ❌\nTroubleshooting:"
                    # 1. Try to resolve IP
                    try:
                        socket.gethostbyaddr(address)
                        output += "\n✅ Address resolves via DNS."
                    except:
                        output += "\n⚠️ Address does not resolve."

                    # 2. Ping test
                    response = client.get(path=[f"/ping/targets/target[address={address}]"], encoding='json', data_type='STATE')
                    latency = response.get("notification", [{}])[0].get("update", [{}])[0].get("val", {}).get("avg-round-trip-time", None)
                    if latency is not None:
                        output += f"\n✅ Ping successful. Avg RTT: {latency} ms"
                    else:
                        output += "\n⚠️ Ping failed or not supported"

                    # 3. Interface status (optional)
                    int_path = f"/interfaces/interface[name={address}]/state/admin-status"
                    int_response = client.get(path=[int_path], encoding='json', data_type='STATE')
                    admin_status = int_response.get("notification", [{}])[0].get("update", [{}])[0].get("val", "UNKNOWN")
                    output += f"\nInterface admin status: {admin_status}"

                else:
                    output += " ✅"

                results.append(output)

            return "\n\n".join(results)
    except Exception as e:
        return f"Error: {str(e)}"

# ---------- Wrapper for LangChain Agent ----------
def wrapped_bgp_tool(input_str: str) -> str:
    try:
        creds = json.loads(input_str)
        return check_bgp_and_troubleshoot(creds["ip"], creds["username"], creds["password"])
    except Exception as e:
        return f"Invalid input format. Expected JSON with ip, username, password. Error: {str(e)}"

# ---------- LangChain Tool + Agent Setup ----------
check_bgp_tool = Tool(
    name="bgp_troubleshoot_tool",
    func=wrapped_bgp_tool,
    description="Checks BGP status and performs troubleshooting. Input should be a JSON string with 'ip', 'username', and 'password'."
)

llm = ChatOllama(model="deepseek-r1:32b", temperature=0.2)

agent = initialize_agent(
    tools=[check_bgp_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# ---------- Run Agent ----------
input_data = {
    "ip": "192.168.255.138",
    "username": "sudhin",
    "password": "sudhin"
}
result = agent.run(f"Check BGP sessions and troubleshoot if not established. Input: {json.dumps(input_data)}")
print(result)
