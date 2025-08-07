from langchain.agents import Tool, AgentExecutor, initialize_agent
from langchain.agents.agent_types import AgentType
from langchain_ollama import ChatOllama
from pygnmi.client import gNMIclient
import socket
import json

# ----- Tool: BGP Troubleshooting -----
def bgp_troubleshoot_tool(input_str: str) -> str:
    try:
        creds = json.loads(input_str)
        ip = creds["ip"]
        username = creds["username"]
        password = creds["password"]

        with gNMIclient(target=(ip, 6030), username=username, password=password, insecure=True) as client:
            paths = [
                "/network-instances/network-instance[name=default]/protocols/protocol[name=BGP]/bgp/neighbors"
            ]
            response = client.get(path=paths, encoding='json', data_type='STATE')
            neighbors_data = response.get("notification", [])[0].get("update", [])

            full_report = []
            for neighbor in neighbors_data:
                address = neighbor["path"]["elem"][-1]["key"]["neighbor-address"]
                state = neighbor["val"].get("session-state", "UNKNOWN")
                report = f"BGP Neighbor {address} is in state: {state}"

                if state != "ESTABLISHED":
                    report += " ❌ Troubleshooting Steps:\n"

                    # DNS resolution
                    try:
                        socket.gethostbyaddr(address)
                        report += "- DNS ✅\n"
                    except:
                        report += "- DNS ❌\n"

                    # Ping check
                    try:
                        ping_path = [f"/ping/targets/target[address={address}]"]
                        ping_result = client.get(path=ping_path, encoding='json', data_type='STATE')
                        latency = ping_result.get("notification", [{}])[0].get("update", [{}])[0].get("val", {}).get("avg-round-trip-time", None)
                        if latency:
                            report += f"- Ping ✅ (RTT: {latency}ms)\n"
                        else:
                            report += "- Ping ❌\n"
                    except:
                        report += "- Ping ❌ (Exception)\n"

                    # Interface admin status
                    try:
                        int_path = f"/interfaces/interface[name={address}]/state/admin-status"
                        int_result = client.get(path=[int_path], encoding='json', data_type='STATE')
                        admin_status = int_result.get("notification", [{}])[0].get("update", [{}])[0].get("val", "UNKNOWN")
                        report += f"- Interface admin status: {admin_status}\n"
                    except:
                        report += "- Interface status check failed.\n"
                else:
                    report += " ✅ All OK.\n"

                full_report.append(report)

            return "\n\n".join(full_report)

    except Exception as e:
        return f"[ERROR]: {str(e)}"

# ----- LangChain Tool Wrapper -----
tool = Tool(
    name="bgp_troubleshoot",
    func=bgp_troubleshoot_tool,
    description="Check BGP neighbors and troubleshoot if session is not established. Takes a JSON string with 'ip', 'username', and 'password'."
)

# ----- LLM Setup -----
llm = ChatOllama(model="deepseek-r1:32b", temperature=0.1)

# ----- Autonomous Agent Setup -----
agent = initialize_agent(
    tools=[tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,  # Reason + Act Loop
    verbose=True
)

# ----- Run the Agent -----
input_data = {
    "ip": "192.168.255.138",
    "username": "sudhin",
    "password": "sudhin"
}

task = f"""
You are a network automation agent. Use the bgp_troubleshoot tool with this input: {json.dumps(input_data)}.
Then, based on the output, decide the best next action. If BGP sessions are not established, suggest:
- config fix
- ask human for manual verification
- retry after cooldown
- or suggest interface checks.

Only call tools or output final answers when appropriate.
"""

result = agent.run(task)
print(result)
