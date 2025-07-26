package main

import (
	"context"
	"encoding/json"
	"log"
	"strings"
	"time"

	"github.com/Shopify/sarama"
	"github.com/openconfig/gnmi/proto/gnmi"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type Router struct {
	Name     string
	Address  string
	Username string
	Password string
}

type basicAuth struct {
	username, password string
}

func (a *basicAuth) GetRequestMetadata(ctx context.Context, uri ...string) (map[string]string, error) {
	return map[string]string{
		"username": a.username,
		"password": a.password,
	}, nil
}
func (a *basicAuth) RequireTransportSecurity() bool { return false }

// Kafka
func connectKafka(brokerList []string) sarama.SyncProducer {
	config := sarama.NewConfig()
	config.Producer.Return.Successes = true
	producer, err := sarama.NewSyncProducer(brokerList, config)
	if err != nil {
		log.Fatalf("Kafka error: %v", err)
	}
	return producer
}

// gNMI Path helper
func gnmiPath(pathStr string) *gnmi.Path {
	elems := []*gnmi.PathElem{}
	for _, p := range strings.Split(pathStr, "/") {
		if p != "" {
			elems = append(elems, &gnmi.PathElem{Name: p})
		}
	}
	return &gnmi.Path{Elem: elems}
}

// Telemetry logic
func collectTelemetry(router Router, producer sarama.SyncProducer, topic string) {
	conn, err := grpc.Dial(
		router.Address,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithPerRPCCredentials(&basicAuth{username: router.Username, password: router.Password}),
	)
	if err != nil {
		log.Fatalf("[%s] gRPC dial error: %v", router.Name, err)
	}
	defer conn.Close()

	client := gnmi.NewGNMIClient(conn)

	// Subscribe to BGP and interface input counters
	subList := &gnmi.SubscriptionList{
		Mode: gnmi.SubscriptionList_STREAM,
		Subscription: []*gnmi.Subscription{
			{Path: gnmiPath("/interfaces/interface/state/counters/in-octets"), Mode: gnmi.SubscriptionMode_ON_CHANGE},
			{Path: gnmiPath("network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state/session-state"), Mode: gnmi.SubscriptionMode_ON_CHANGE},
		},
	}

	subReq := &gnmi.SubscribeRequest{
		Request: &gnmi.SubscribeRequest_Subscribe{Subscribe: subList},
	}

	ctx := context.Background()
	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Fatalf("[%s] Subscribe error: %v", router.Name, err)
	}
	if err := stream.Send(subReq); err != nil {
		log.Fatalf("[%s] Send request error: %v", router.Name, err)
	}

	// Store state
	interfaceMap := make(map[string]uint64)
	neighborMap := make(map[string]string)

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	go func() {
		for range ticker.C {
			// Compose Kafka message
			payload := map[string]interface{}{
				"router":    router.Name,
				"timestamp": time.Now().Format(time.RFC3339),
				"interfaces": func() []map[string]interface{} {
					var arr []map[string]interface{}
					for k, v := range interfaceMap {
						arr = append(arr, map[string]interface{}{"name": k, "in_packets": v})
					}
					return arr
				}(),
				"bgp_neighbors": func() []map[string]interface{} {
					var arr []map[string]interface{}
					for ip, state := range neighborMap {
						arr = append(arr, map[string]interface{}{"neighbor_ip": ip, "state": state})
					}
					return arr
				}(),
			}

			jsonData, _ := json.Marshal(payload)
			msg := &sarama.ProducerMessage{
				Topic: topic,
				Value: sarama.ByteEncoder(jsonData),
			}
			_, _, err := producer.SendMessage(msg)
			if err != nil {
				log.Printf("[%s] Kafka publish error: %v", router.Name, err)
			} else {
				log.Printf("[%s] Published telemetry update", router.Name)
			}
		}
	}()

	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Printf("[%s] Stream receive error: %v", router.Name, err)
			break
		}

		updateResp, ok := resp.Response.(*gnmi.SubscribeResponse_Update)
		if !ok {
			continue
		}

		for _, update := range updateResp.Update.Update {
			pathStr := pathToString(update.Path)
			if strings.Contains(pathStr, "in-octets") {
				ifName := extractKey(update.Path, "interface")
				interfaceMap[ifName] = update.Val.GetUintVal()
			}
			if strings.Contains(pathStr, "session-state") {
				neighborIP := extractKey(update.Path, "neighbor")
				neighborMap[neighborIP] = update.Val.GetStringVal()
			}
		}
	}
}

// Helper: extract keyed name from gNMI path
func extractKey(path *gnmi.Path, match string) string {
	for _, elem := range path.Elem {
		if elem.Name == match {
			for _, v := range elem.Key {
				return v
			}
		}
	}
	return "unknown"
}

func pathToString(p *gnmi.Path) string {
	parts := []string{}
	for _, e := range p.Elem {
		parts = append(parts, e.Name)
	}
	return strings.Join(parts, "/")
}

// MAIN
func main() {
	routers := []Router{
		{"Router1", "192.168.255.137:6030", "sudhin", "sudhin"},
		{"Router2", "192.168.255.138:6030", "sudhin", "sudhin"},
	}

	kafkaBrokers := []string{"localhost:9092"}
	kafkaTopic := "bgp-telemetry"
	producer := connectKafka(kafkaBrokers)
	defer producer.Close()

	for _, router := range routers {
		go collectTelemetry(router, producer, kafkaTopic)
	}

	select {} // block forever
}
