package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log"
	"time"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

func main() {
	var (
		targetAddr = flag.String("address", "192.168.255.138:6030", "gNMI target address")
		username   = flag.String("username", "sudhin", "Username for authentication")
		password   = flag.String("password", "sudhin", "Password for authentication")
	)
	flag.Parse()

	// Dial gRPC insecurely (modify for TLS if needed)
	conn, err := grpc.Dial(*targetAddr, grpc.WithInsecure(), grpc.WithBlock(), grpc.WithTimeout(5*time.Second))
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Create metadata with username/password for basic auth
	ctx := context.Background()
	if *username != "" && *password != "" {
		md := metadata.Pairs("username", *username, "password", *password)
		ctx = metadata.NewOutgoingContext(ctx, md)
	}

	// Build the path for BGP neighbors
	path := &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "network-instances"},
			{Name: "network-instance", Key: map[string]string{"name": "default"}},
			{Name: "protocols"},
			{Name: "protocol", Key: map[string]string{"name": "BGP", "identifier": "BGP"}},
			{Name: "bgp"},
			{Name: "neighbors"},
			{Name: "neighbor"}, // subscribe all neighbors
		},
	}

	// Create SubscribeRequest for a STREAM subscription
	subReq := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{
			Subscribe: &gnmi.SubscriptionList{
				Mode: gnmi.SubscriptionList_STREAM, // streaming updates
				Subscription: []*gnmi.Subscription{
					{
						Path:           path,
						Mode:           gnmi.SubscriptionMode_SAMPLE, // sample updates
						SampleInterval: 10 * 1e9,                     // 10 seconds in nanoseconds
					},
				},
				Encoding: gnmi.Encoding_JSON,
			},
		},
	}

	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("Subscribe failed: %v", err)
	}

	// Send the initial subscription request
	if err := stream.Send(subReq); err != nil {
		log.Fatalf("Failed to send subscribe request: %v", err)
	}

	log.Println("Subscribed to BGP neighbor state updates. Waiting for notifications...")

	// Receive subscription responses
	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			log.Println("Subscription stream closed by server")
			break
		}
		if err != nil {
			log.Fatalf("Error receiving subscription response: %v", err)
		}

		switch response := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			update := response.Update
			fmt.Printf("Notification Timestamp: %v\n", update.Timestamp)
			for _, upd := range update.Update {
				fmt.Printf("Path: %v\n", upd.Path)
				fmt.Printf("Value: %s\n", upd.Val.GetJsonVal())
			}
			fmt.Println("-----")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("Subscription error: %v", response.Error)
		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("SyncResponse received")
		default:
			log.Printf("Unknown subscription response: %v", resp)
		}
	}
}
