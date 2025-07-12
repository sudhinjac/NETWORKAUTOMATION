package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/segmentio/kafka-go"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// Build the gNMI path to BGP session state
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

// Kafka writer setup
func createKafkaWriter(broker, topic string) *kafka.Writer {
	return &kafka.Writer{
		Addr:     kafka.TCP(broker),
		Topic:    topic,
		Balancer: &kafka.LeastBytes{},
	}
}

func main() {
	targetAddr := "192.168.255.138:6030"
	username := "sudhin"
	password := "sudhin"
	kafkaBroker := "localhost:9092"
	kafkaTopic := "bgp-status"

	// Connect to Kafka
	writer := createKafkaWriter(kafkaBroker, kafkaTopic)
	defer writer.Close()

	// Connect to gNMI device
	conn, err := grpc.Dial(targetAddr, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to gNMI: %v", err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	md := metadata.Pairs("username", username, "password", password)
	ctx := metadata.NewOutgoingContext(context.Background(), md)

	// gNMI subscription setup
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

	// Start subscription stream
	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("gNMI subscribe error: %v", err)
	}

	if err := stream.Send(req); err != nil {
		log.Fatalf("Failed to send subscription request: %v", err)
	}

	log.Println("📡 Subscribed to gNMI BGP state stream. Sending to Kafka...")

	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Fatalf("Stream receive error: %v", err)
		}

		switch response := resp.Response.(type) {
		case *gnmi.SubscribeResponse_Update:
			notif := response.Update
			for _, update := range notif.Update {
				valueJSON, _ := json.Marshal(update.Val)
				message := map[string]interface{}{
					"timestamp": notif.Timestamp,
					"path":      update.Path,
					"value":     string(valueJSON),
				}
				msgBytes, _ := json.Marshal(message)

				err := writer.WriteMessages(ctx, kafka.Message{
					Key:   []byte(fmt.Sprintf("bgp-%d", notif.Timestamp)),
					Value: msgBytes,
				})
				if err != nil {
					log.Printf("⚠️ Kafka write failed: %v", err)
				} else {
					log.Printf("✅ Sent to Kafka: %s", msgBytes)
				}
			}
		case *gnmi.SubscribeResponse_SyncResponse:
			log.Println("🔄 Initial sync complete.")
		case *gnmi.SubscribeResponse_Error:
			log.Printf("gNMI error: %v", response.Error.Message)
		}
	}
}
