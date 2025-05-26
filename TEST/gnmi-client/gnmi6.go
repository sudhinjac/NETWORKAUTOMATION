package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"regexp"
	"time"

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
			{Name: "neighbor"},
			{Name: "state"},
			{Name: "session-state"},
		},
	}
}

// Extracts IP from path string
func extractNeighborIP(path *gnmi.Path) string {
	re := regexp.MustCompile(`neighbor-address=([^\]]+)`)
	for _, elem := range path.Elem {
		if val, ok := elem.Key["neighbor-address"]; ok {
			return val
		}
		// fallback from string version if needed
		if match := re.FindStringSubmatch(elem.Name); len(match) == 2 {
			return match[1]
		}
	}
	return "unknown"
}

func main() {
	targetAddr := "192.168.255.138:6030"
	username := "sudhin"
	password := "sudhin"
	csvFile := "bgp_states.csv"

	// Open CSV file
	file, err := os.Create(csvFile)
	if err != nil {
		log.Fatalf("Failed to create CSV file: %v", err)
	}
	defer file.Close()

	writer := csv.NewWriter(file)
	defer writer.Flush()
	writer.Write([]string{"timestamp", "neighbor-address", "session-state"})

	// gRPC connection
	conn, err := grpc.Dial(targetAddr, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	md := metadata.Pairs("username", username, "password", password)
	ctx := metadata.NewOutgoingContext(context.Background(), md)

	subscription := &gnmi.Subscription{
		Path:           buildBGPPath(),
		Mode:           gnmi.SubscriptionMode_SAMPLE,
		SampleInterval: uint64(10 * time.Second.Nanoseconds()),
	}

	subList := &gnmi.SubscriptionList{
		Subscription: []*gnmi.Subscription{subscription},
		Mode:         gnmi.SubscriptionList_STREAM,
		Encoding:     gnmi.Encoding_JSON,
	}

	req := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{
			Subscribe: subList,
		},
	}

	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("Failed to start subscription: %v", err)
	}

	if err := stream.Send(req); err != nil {
		log.Fatalf("Failed to send subscription request: %v", err)
	}

	log.Println("Subscribed to BGP session state. Listening for updates...")

	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Fatalf("Error receiving gNMI response: %v", err)
		}

		switch response := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			notif := response.Update
			timestamp := time.Now().Format(time.RFC3339)

			for _, update := range notif.Update {
				neighborIP := extractNeighborIP(update.Path)

				var sessionState string
				if update.Val != nil {
					rawVal, _ := json.Marshal(update.Val)
					json.Unmarshal(rawVal, &sessionState)
				}

				// Log to screen
				fmt.Printf("[%s] Neighbor: %s, State: %s\n", timestamp, neighborIP, sessionState)

				// Write to CSV
				writer.Write([]string{timestamp, neighborIP, sessionState})
				writer.Flush()
			}
		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("Initial sync complete.")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("gNMI error: %v", response.Error.Message)
		}
	}
}
