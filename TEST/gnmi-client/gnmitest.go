package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

func main() {
	addr := "192.168.255.138:6030" // Arista gNMI address and port
	username := "sudhin"
	password := "sudhin"

	// Create output file
	f, err := os.Create("output.txt")
	if err != nil {
		log.Fatalf("Failed to create output file: %v", err)
	}
	defer f.Close()

	// Use insecure connection (no TLS)
	opts := []grpc.DialOption{
		grpc.WithInsecure(),
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	conn, err := grpc.DialContext(ctx, addr, opts...)
	if err != nil {
		log.Fatalf("Failed to dial gNMI target: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Add username/password metadata for basic auth
	md := metadata.Pairs(
		"username", username,
		"password", password,
	)
	ctx = metadata.NewOutgoingContext(ctx, md)

	// 1. Call Capabilities RPC
	fmt.Fprintln(f, "Calling Capabilities RPC...")
	capsResp, err := client.Capabilities(ctx, &gnmi.CapabilityRequest{})
	if err != nil {
		log.Fatalf("Capabilities RPC failed: %v", err)
	}

	fmt.Fprintln(f, "Supported Models:")
	for _, model := range capsResp.SupportedModels {
		fmt.Fprintf(f, " - Name: %s, Version: %s\n", model.Name, model.Version)
	}

	fmt.Fprintln(f, "Supported Encodings:")
	for _, enc := range capsResp.SupportedEncodings {
		fmt.Fprintf(f, " - %s\n", enc.String())
	}

	// 2. Build GetRequest to fetch /system subtree for exploration
	path := &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "system"},
		},
	}

	getRequest := &gnmi.GetRequest{
		Encoding: gnmi.Encoding_JSON_IETF, // Use JSON for easy reading
		Path:     []*gnmi.Path{path},
		Type:     gnmi.GetRequest_ALL, // all data (state + config)
	}

	fmt.Fprintln(f, "\nCalling Get RPC for /system subtree...")
	resp, err := client.Get(ctx, getRequest)
	if err != nil {
		log.Fatalf("Get RPC failed: %v", err)
	}

	for _, notif := range resp.Notification {
		for _, update := range notif.Update {
			fmt.Fprintf(f, "Path: %v\n", update.Path)
			fmt.Fprintf(f, "Value: %v\n\n", update.Val)
		}
	}

	fmt.Println("Output written to output.txt")
}
