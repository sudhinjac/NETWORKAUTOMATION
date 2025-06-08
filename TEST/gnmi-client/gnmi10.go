package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// buildBGPPath returns the gNMI path for BGP neighbors' session state
func buildBGPPath() *gnmi.Path {
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
	// gNMI target details
	targetAddr := "192.168.255.138:6030"
	username := "sudhin"
	password := "sudhin"

	// Establish gRPC connection
	conn, err := grpc.Dial(targetAddr, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to target: %v", err)
	}
	defer conn.Close()

	// Create gNMI client
	client := gnmi.NewGNMIClient(conn)

	// Add username/password metadata
	md := metadata.Pairs("username", username, "password", password)
	ctx := metadata.NewOutgoingContext(context.Background(), md)

	// Build SubscribeRequest with ONCE mode
	subscription := &gnmi.Subscription{
		Path: buildBGPPath(),
		Mode: gnmi.SubscriptionMode_ON_CHANGE, // Mode ignored in ONCE, but required
	}

	subList := &gnmi.SubscriptionList{
		Subscription: []*gnmi.Subscription{subscription},
		Mode:         gnmi.SubscriptionList_ONCE,
		Encoding:     gnmi.Encoding_JSON,
	}

	subReq := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{
			Subscribe: subList,
		},
	}

	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("Failed to subscribe: %v", err)
	}

	if err := stream.Send(subReq); err != nil {
		log.Fatalf("Failed to send SubscribeRequest: %v", err)
	}

	log.Println("Sent ONCE subscription request. Waiting for BGP neighbor state...")

	// Read responses
	for {
		resp, err := stream.Recv()
		if err != nil {
			break // ONCE mode ends after one response
		}

		switch response := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			for _, update := range response.Update.Update {
				jsonData, err := json.MarshalIndent(update, "", "  ")
				if err != nil {
					log.Printf("Failed to marshal update: %v", err)
					continue
				}
				fmt.Println(string(jsonData))
			}
		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("Sync complete.")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("gNMI Error: %v", response.Error.Message)
		}
	}
}
