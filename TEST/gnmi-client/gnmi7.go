package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// buildBGPPath constructs the gNMI path for BGP neighbor session state
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

// extractNeighborIP tries to extract the neighbor-address key from the Path
func extractNeighborIP(path *gnmi.Path) string {
	for _, elem := range path.Elem {
		if elem.Name == "neighbor" {
			if ip, ok := elem.Key["neighbor-address"]; ok {
				return ip
			}
		}
	}
	return "unknown"
}

func main() {
	targetAddr := "192.168.255.138:6030"
	username := "sudhin"
	password := "sudhin"

	// CSV setup
	csvFile, err := os.OpenFile("bgp_session_state.csv", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Fatalf("Failed to open CSV file: %v", err)
	}
	defer csvFile.Close()
	writer := csv.NewWriter(csvFile)
	defer writer.Flush()

	// Write header if file is empty
	info, _ := csvFile.Stat()
	if info.Size() == 0 {
		writer.Write([]string{"timestamp", "neighbor-ip", "session-state"})
		writer.Flush()
	}

	// Connect to gNMI
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
			for _, update := range notif.Update {
				timestamp := time.Now().Format(time.RFC3339)
				neighborIP := extractNeighborIP(update.Path)

				var sessionState string
				if update.Val != nil {
					switch val := update.Val.Value.(type) {
					case *gnmi.TypedValue_StringVal:
						sessionState = val.StringVal
					case *gnmi.TypedValue_AsciiVal:
						sessionState = val.AsciiVal
					case *gnmi.TypedValue_JsonVal:
						var data map[string]interface{}
						_ = json.Unmarshal(val.JsonVal, &data)
						if s, ok := data["session-state"]; ok {
							sessionState = fmt.Sprintf("%v", s)
						}
					case *gnmi.TypedValue_JsonIetfVal:
						var data map[string]interface{}
						_ = json.Unmarshal(val.JsonIetfVal, &data)
						if s, ok := data["session-state"]; ok {
							sessionState = fmt.Sprintf("%v", s)
						}
					default:
						sessionState = fmt.Sprintf("unsupported type: %T", val)
					}
				}

				// Print to screen
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
