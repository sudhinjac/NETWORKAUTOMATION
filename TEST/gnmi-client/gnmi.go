package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"time"

	"github.com/openconfig/gnmi/proto/gnmi"
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

	// Create metadata with username/password for basic auth (gNMI uses grpc metadata)
	ctx := context.Background()
	if *username != "" && *password != "" {
		md := metadata.Pairs("username", *username, "password", *password)
		ctx = metadata.NewOutgoingContext(ctx, md)
	}

	// Build the path for BGP neighbors
	// Path elems must be separate name/key pairs
	path := &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "network-instances"},
			{Name: "network-instance", Key: map[string]string{"name": "default"}},
			{Name: "protocols"},
			{Name: "protocol", Key: map[string]string{"name": "BGP", "identifier": "BGP"}},
			{Name: "bgp"},
			{Name: "neighbors"},
			{Name: "neighbor"}, // will get all neighbors
		},
	}

	req := &gnmi.GetRequest{
		Path:     []*gnmi.Path{path},
		Encoding: gnmi.Encoding_JSON,
	}

	resp, err := client.Get(ctx, req)
	if err != nil {
		log.Fatalf("gNMI Get failed: %v", err)
	}

	// Print the results
	for _, notif := range resp.Notification {
		for _, update := range notif.Update {
			fmt.Printf("Path: %v\n", update.Path)
			fmt.Printf("Value: %s\n", update.Val.GetJsonVal())
		}
	}
}
