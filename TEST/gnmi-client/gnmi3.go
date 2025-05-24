package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"text/tabwriter"
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

	// Connect insecurely
	conn, err := grpc.Dial(*targetAddr, grpc.WithInsecure(), grpc.WithBlock(), grpc.WithTimeout(5*time.Second))
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Metadata for authentication
	ctx := context.Background()
	if *username != "" && *password != "" {
		md := metadata.Pairs("username", *username, "password", *password)
		ctx = metadata.NewOutgoingContext(ctx, md)
	}

	// Create CSV file
	csvFile, err := os.Create("bgp_updates.csv")
	if err != nil {
		log.Fatalf("Failed to create CSV file: %v", err)
	}
	defer csvFile.Close()

	csvWriter := csv.NewWriter(csvFile)
	defer csvWriter.Flush()

	// Write CSV header
	csvWriter.Write([]string{"Timestamp", "Neighbor Address", "Field", "Value"})

	// Subscribe path to all neighbors
	path := &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "network-instances"},
			{Name: "network-instance", Key: map[string]string{"name": "default"}},
			{Name: "protocols"},
			{Name: "protocol", Key: map[string]string{"identifier": "BGP", "name": "BGP"}},
			{Name: "bgp"},
			{Name: "neighbors"},
		},
	}

	subReq := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{
			Subscribe: &gnmi.SubscriptionList{
				Mode: gnmi.SubscriptionList_STREAM,
				Subscription: []*gnmi.Subscription{
					{
						Path:           path,
						Mode:           gnmi.SubscriptionMode_SAMPLE,
						SampleInterval: 5 * 1e9, // 5 seconds
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

	if err := stream.Send(subReq); err != nil {
		log.Fatalf("Failed to send subscribe request: %v", err)
	}

	log.Println("Subscribed to BGP neighbor telemetry...\n")

	// Tabular output
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, "Timestamp\tNeighbor Address\tField\tValue")

	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			log.Println("Stream closed by server")
			break
		}
		if err != nil {
			log.Fatalf("Recv error: %v", err)
		}

		switch r := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			timestamp := time.Unix(0, r.Update.Timestamp).Format(time.RFC3339)

			for _, upd := range r.Update.Update {
				var neighborAddr string
				var field string

				// Get neighbor-address from path keys
				for _, elem := range upd.Path.Elem {
					if elem.Name == "neighbor" {
						if val, ok := elem.Key["neighbor-address"]; ok {
							neighborAddr = val
						}
					}
				}

				// Build field name
				for _, elem := range upd.Path.Elem {
					if elem.Name != "neighbor" && len(elem.Key) == 0 {
						field += elem.Name + "/"
					}
				}
				if len(field) > 0 {
					field = field[:len(field)-1] // trim trailing slash
				}

				// Extract value
				var value string
				if upd.Val != nil {
					switch v := upd.Val.Value.(type) {
					case *gnmi.TypedValue_StringVal:
						value = v.StringVal
					case *gnmi.TypedValue_IntVal:
						value = fmt.Sprintf("%d", v.IntVal)
					case *gnmi.TypedValue_UintVal:
						value = fmt.Sprintf("%d", v.UintVal)
					case *gnmi.TypedValue_BoolVal:
						value = fmt.Sprintf("%t", v.BoolVal)
					case *gnmi.TypedValue_JsonVal:
						var jsonMap map[string]interface{}
						err := json.Unmarshal(v.JsonVal, &jsonMap)
						if err == nil {
							b, _ := json.Marshal(jsonMap)
							value = string(b)
						}
					default:
						value = fmt.Sprintf("%v", upd.Val)
					}
				}

				// Print and write to CSV
				if neighborAddr != "" && field != "" && value != "" {
					fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", timestamp, neighborAddr, field, value)
					w.Flush()

					csvWriter.Write([]string{timestamp, neighborAddr, field, value})
					csvWriter.Flush()
				}
			}

		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("Initial sync complete.")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("Subscription error: %v", r.Error)
		default:
			log.Printf("Unknown response: %v", resp)
		}
	}
}
