package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// Common connection settings
const (
	targetAddr = "192.168.255.138:6030"
	username   = "sudhin"
	password   = "sudhin"
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
			{Name: "neighbor"},
			{Name: "state"},
			{Name: "session-state"},
		},
	}
}

func subscribe(mode gnmi.SubscriptionList_Mode, subMode gnmi.SubscriptionMode, interval time.Duration) {
	conn, err := grpc.Dial(targetAddr, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)
	md := metadata.Pairs("username", username, "password", password)
	ctx := metadata.NewOutgoingContext(context.Background(), md)
	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("Failed to start subscription: %v", err)
	}

	sub := &gnmi.Subscription{
		Path: buildBGPPath(),
		Mode: subMode,
	}
	if interval > 0 {
		sub.SampleInterval = uint64(interval.Nanoseconds())
	}

	subList := &gnmi.SubscriptionList{
		Subscription: []*gnmi.Subscription{sub},
		Mode:         mode,
		Encoding:     gnmi.Encoding_JSON,
	}

	req := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{Subscribe: subList},
	}

	if err := stream.Send(req); err != nil {
		log.Fatalf("Failed to send subscription request: %v", err)
	}

	if mode == gnmi.SubscriptionList_POLL {
		log.Println("Sending first POLL request...")
		if err := stream.Send(&gnmi.SubscribeRequest{Request: &gnmi.SubscribeRequest_Poll{}}); err != nil {
			log.Fatalf("Failed to send POLL request: %v", err)
		}
	}

	log.Printf("Listening for updates in %s mode...\n", mode)
	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Fatalf("Recv error: %v", err)
		}

		switch x := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			for _, update := range x.Update.Update {
				valueJSON, _ := json.Marshal(update.Val)
				fmt.Printf("[%s] %v = %s\n", time.Now().Format(time.RFC3339), update.Path, valueJSON)
			}
		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("Initial sync complete.")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("gNMI error: %v\n", x.Error.Message)
		}

		if mode == gnmi.SubscriptionList_ONCE {
			break
		}
	}
}

func main() {
	fmt.Println("\n--- ONCE MODE ---")
	subscribe(gnmi.SubscriptionList_ONCE, gnmi.SubscriptionMode_TARGET_DEFINED, 0)

	fmt.Println("\n--- POLL MODE ---")
	subscribe(gnmi.SubscriptionList_POLL, gnmi.SubscriptionMode_TARGET_DEFINED, 0)

	fmt.Println("\n--- STREAM SAMPLE MODE (10s) ---")
	subscribe(gnmi.SubscriptionList_STREAM, gnmi.SubscriptionMode_SAMPLE, 10*time.Second)

	fmt.Println("\n--- STREAM ON_CHANGE MODE ---")
	subscribe(gnmi.SubscriptionList_STREAM, gnmi.SubscriptionMode_ON_CHANGE, 0)
}
