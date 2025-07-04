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

func buildBGPPath() *gnmi.Path {
	return &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "network-instances"},
			{Name: "network-instance", Key: map[string]string{"name": "default"}},
			{Name: "protocols"},
			{Name: "protocol", Key: map[string]string{"identifier": "BGP", "name": "BGP"}},
			{Name: "bgp"},
			{Name: "neighbors"},
		},
	}
}

func main() {
	target := "192.168.255.138:6030"
	username := "sudhin"
	password := "sudhin"

	// Dial gRPC
	conn, err := grpc.Dial(target, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Auth metadata
	md := metadata.Pairs("username", username, "password", password)
	ctx := metadata.NewOutgoingContext(context.Background(), md)

	// SubscribeRequest with ONCE mode
	req := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{
			Subscribe: &gnmi.SubscriptionList{
				Mode:     gnmi.SubscriptionList_ONCE,
				Encoding: gnmi.Encoding_JSON,
				Subscription: []*gnmi.Subscription{
					{
						Path: buildBGPPath(),
						Mode: gnmi.SubscriptionMode_TARGET_DEFINED,
					},
				},
			},
		},
	}

	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("Failed to start subscription: %v", err)
	}

	if err := stream.Send(req); err != nil {
		log.Fatalf("Failed to send request: %v", err)
	}

	log.Println("Sent ONCE subscription request. Waiting for data...")

	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Printf("Stream closed or error: %v", err)
			break
		}

		switch msg := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			// Print updates in JSON
			b, _ := json.MarshalIndent(msg.Update, "", "  ")
			fmt.Println("Update:\n", string(b))

		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("Sync complete. Snapshot received.")
			return
		case *gnmi.SubscribeResponse_Error:
			log.Printf("Error from server: %v", msg.Error.Message)
			return
		default:
			log.Println("Unknown message type.")
		}
	}
}
