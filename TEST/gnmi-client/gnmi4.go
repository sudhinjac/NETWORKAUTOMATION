package main

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// Replace these with your device details
const (
	targetAddr   = "192.168.255.138:6030"
	username     = "sudhin"
	password     = "sudhin"
	pollInterval = 10 * time.Second
)

// gNMI path to BGP neighbor session state
// network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor/state/session-state
func buildPath() *gnmi.Path {
	return &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "network-instances"},
			{Name: "network-instance", Key: map[string]string{"name": "default"}},
			{Name: "protocols"},
			{Name: "protocol", Key: map[string]string{"identifier": "BGP", "name": "BGP"}},
			{Name: "bgp"},
			{Name: "neighbors"},
			{Name: "neighbor"},
			{Name: "state"},
			{Name: "session-state"},
		},
	}
}

func main() {
	// Dial insecure gRPC connection
	conn, err := grpc.Dial(targetAddr, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Prepare metadata with username and password
	md := metadata.Pairs(
		"username", username,
		"password", password,
	)

	ctx := metadata.NewOutgoingContext(context.Background(), md)

	path := buildPath()

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			getRequest := &gnmi.GetRequest{
				Path:     []*gnmi.Path{path},
				Encoding: gnmi.Encoding_JSON,
			}

			resp, err := client.Get(ctx, getRequest)
			if err != nil {
				log.Printf("gNMI Get error: %v", err)
				continue
			}

			// Print the raw response JSON notification
			for _, notif := range resp.Notification {
				for _, update := range notif.Update {
					// The path keys include neighbor-address
					neighborAddress := ""
					for _, elem := range update.Path.Elem {
						if elem.Name == "neighbor" {
							if val, ok := elem.Key["neighbor-address"]; ok {
								neighborAddress = val
							}
						}
					}

					// The val should be the session-state as string
					var sessionState string
					switch v := update.Val.Value.(type) {
					case *gnmi.TypedValue_StringVal:
						sessionState = v.StringVal
					default:
						// fallback: marshal val to json string for printing
						b, _ := json.Marshal(update.Val)
						sessionState = string(b)
					}

					log.Printf("Neighbor: %s, Session State: %s", neighborAddress, sessionState)
				}
			}
		}
	}
}
