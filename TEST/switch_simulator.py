#!/usr/bin/env python3
"""
switch_simulator.py
A tiny Flask app that simulates a switch exposing:
 - GET /yang    -> returns the switch.yang text
 - GET /switch  -> returns JSON data following the YANG model
"""

from flask import Flask, jsonify, Response
import random
import json

app = Flask(__name__)

# The YANG module served by the simulator (as text)
SWITCH_YANG = """module switch {
    namespace "http://sudhin.com";
    prefix "l2sw";

   container switch {
    leaf hostname {
        type string;
    }

    list interface {
        key name;
        leaf name {
          type string {
            pattern ".*Ethernet0/[0-9]+";
          }
        }
        leaf description {
            type string {
                length "4..50";
            }
        }
        leaf speed{
            type uint32;
            units "Mbps";
            config false;
        }
        leaf mode {
            type enumeration {
                enum access;
                enum trunk;
            }
        }
        choice access-or-trunk {
            case access {
                leaf access-vlan {
                    type uint16 {
                        range "1..4094";
                    }
                }
                when "mode='access'";
            }
            case trunk {
                leaf-list trunked-vlan {
                    type uint16 {
                        range "1..4094";
                    }
                }
                when "mode='trunk'";
            }
        }
    }
   }
}"""

# Simulated runtime state/config for the "switch"
def make_sample_switch():
    # We'll create 3 interfaces demonstrating access/trunk
    interfaces = [
        {
            "name": "Ethernet0/1",
            "description": "Uplink",
            "speed": 1000,         # operational (config false) value
            "mode": "trunk",
            "trunked-vlan": [10, 20, 30]
        },
        {
            "name": "Ethernet0/2",
            "description": "Downlink",
            "speed": 100,
            "mode": "access",
            "access-vlan": 100
        },
        {
            "name": "Ethernet0/3",
            "description": "Access",
            "speed": 100,
            "mode": "access",
            "access-vlan": 200
        },
    ]

    # Add a random speed jitter to show operational changes
    for itf in interfaces:
        # small random variation
        itf["speed"] = itf["speed"] + random.choice([0, 0, 0, -10, 10])

        # ensure fields match YANG naming:
        # trunked-vlan -> trunked-vlan (list)
        # access-vlan -> access-vlan (leaf)
    return {
        "switch": {
            "hostname": "sudhin",
            "interface": interfaces
        }
    }

@app.route("/yang", methods=["GET"])
def yang():
    return Response(SWITCH_YANG, mimetype="text/plain")

@app.route("/switch", methods=["GET"])
def get_switch():
    data = make_sample_switch()
    # Return JSON using "json_ietf"-like structure (simple)
    return jsonify(data)

if __name__ == "__main__":
    print("Starting switch simulator on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)