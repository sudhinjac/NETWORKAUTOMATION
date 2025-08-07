# Simulated network flows (telemetry logs)
network_flows = [
    {"src": "192.168.10.5", "dst": "192.168.20.10"},  # Guest -> Finance (violation)
    {"src": "192.168.30.2", "dst": "192.168.20.10"}   # Employee -> Finance (ok)
]

# Defined network intent
intent = {
    "policy": "block_guest_from_finance",
    "guest_network": "192.168.10.0/24",
    "finance_server": "192.168.20.10"
}

# Simulated Access Control List (ACL) table
acl_table = []

# Check if a flow violates the intent
def violates_intent(flow, intent):
    return flow["src"].startswith("192.168.10.") and flow["dst"] == intent["finance_server"]

# Deploy ACL automatically (self-healing action)
def deploy_acl(intent):
    acl_rule = f"deny ip {intent['guest_network']} host {intent['finance_server']}"
    if acl_rule not in acl_table:
        acl_table.append(acl_rule)
        print(f"[SELF-HEAL] Applied ACL: {acl_rule}")
    else:
        print(f"[INFO] ACL already applied: {acl_rule}")

# Intent-Based Troubleshooting with Self-Healing
def intent_based_troubleshooting(flows, intent):
    print("=== Intent-Based Troubleshooting (Self-Healing) ===")
    for flow in flows:
        if violates_intent(flow, intent):
            print(f"[ALERT] Violation detected: Guest {flow['src']} accessing Finance {flow['dst']}")
            deploy_acl(intent)
        else:
            print(f"[OK] Flow {flow['src']} → {flow['dst']} complies with intent")

# Run the self-healing troubleshooting
intent_based_troubleshooting(network_flows, intent)

# Show the final ACL table
print("\n[FINAL ACL TABLE]", acl_table)