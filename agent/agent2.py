import json
import subprocess
from langchain.agents import Tool, initialize_agent, AgentType
from langchain_community.chat_models import ChatOllama


# Define the tool function
def check_bgp_status(data: dict) -> str:
    try:
        # Build the gNMI command
        command = [
            "gnmic", "-a", f"{data['ip']}:6030", "-u", data["username"], "-p", data["password"],
            "--insecure", "get", "--path", "/network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state"
        ]

        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stdout

        if not output:
            return "❗ No BGP data found."

        neighbors_info = output.split('\n')
        status_report = []

        for line in neighbors_info:
            if "neighbor-address" in line:
                neighbor = line.split(":")[-1].strip()
            if "session-state" in line:
                state = line.split(":")[-1].strip()
                report = f"🔹 Neighbor {neighbor} — BGP state: **{state}**"

                if state.lower() in ["idle", "active"]:
                    ping_result = subprocess.run(["ping", "-c", "1", neighbor], capture_output=True, text=True)
                    if "1 received" in ping_result.stdout:
                        report += " | Ping: ✅ Reachable"
                    else:
                        report += " | Ping: ❌ Unreachable"
                status_report.append(report)

        return "\n".join(status_report) if status_report else "⚠️ No BGP neighbors found."

    except Exception as e:
        return f"🚨 Error checking BGP status: {e}"


def main():
    # Create the tool
    bgp_tool = Tool(
        name="check_bgp_status",
        func=check_bgp_status,
        description="Check BGP session and ping neighbors. Input must be a JSON string with 'ip', 'username', and 'password'."
    )

    # Load the Ollama model (DeepSeek or any)
    llm = ChatOllama(model="deepseek-r1:14b", temperature=0.3)

    # Initialize the agent
    agent = initialize_agent(
        tools=[bgp_tool],
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True
    )

    # BGP credentials input
    input_data = {
        "ip": "192.168.255.138",
        "username": "sudhin",
        "password": "sudhin"
    }

    # Convert to string since agent takes plain instructions
    prompt = f"""Check BGP neighbor status and ping any neighbors that are idle or active.
Here are the credentials:
{json.dumps(input_data)}"""

    print("🚀 Running agent...\n")
    result = agent.run(prompt)
    print("\n🤖 Agent Result:\n", result)


if __name__ == "__main__":
    main()
