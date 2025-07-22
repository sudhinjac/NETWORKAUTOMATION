package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/Shopify/sarama"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	gpb "github.com/openconfig/gnmi/proto/gnmi"
)

type RouterConfig struct {
	Name     string
	Address  string
	Username string
	Password string
}

var routers = []RouterConfig{
	{"Router1", "192.168.1.1:57400", "admin", "admin"},
	{"Router2", "192.168.1.2:57400", "admin", "admin"},
	{"Router3", "192.168.1.3:57400", "admin", "admin"},
}

type InterfaceStat struct {
	InterfaceName string `json:"interface_name"`
	InPackets     uint64 `json:"in_packets"`
	OutPackets    uint64 `json:"out_packets"`
}

type BGPNeighbor struct {
	NeighborIP string `json:"neighbor_ip"`
	State      string `json:"state"`
}

type KafkaMessage struct {
	RouterName   string          `json:"router_name"`
	Timestamp    string          `json:"timestamp"`
	Interfaces   []InterfaceStat `json:"interfaces"`
	BGPNeighbors []BGPNeighbor   `json:"bgp_neighbors"`
}

var kafkaTopic = "bgp-telemetry"

func main() {
	producer := initKafkaProducer()
	defer producer.Close()

	for _, router := range routers {
		go collectTelemetry(router, producer)
	}

	select {} // block forever
}

func initKafkaProducer() sarama.SyncProducer {
	config := sarama.NewConfig()
	config.Producer.Return.Successes = true
	producer, err := sarama.NewSyncProducer([]string{"localhost:9092"}, config)
	if err != nil {
		log.Fatalf("Kafka producer error: %v", err)
	}
	return producer
}

func collectTelemetry(router RouterConfig, producer sarama.SyncProducer) {
	conn, err := grpc.Dial(router.Address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Printf("Failed to connect to %s: %v", router.Name, err)
		return
	}
	defer conn.Close()

	client := gpb.NewGNMIClient(conn)
	ctx := context.Background()

	req := &gpb.SubscribeRequest{
		Request: &gpb.SubscribeRequest_Subscribe{
			Subscribe: &gpb.SubscriptionList{
				Mode: gpb.SubscriptionList_STREAM,
				Subscription: []*gpb.Subscription{
					{Path: toPath("interfaces/interface/state/in-octets"), Mode: gpb.SubscriptionMode_ON_CHANGE},
					{Path: toPath("interfaces/interface/state/out-octets"), Mode: gpb.SubscriptionMode_ON_CHANGE},
					{Path: toPath("network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state/session-state"), Mode: gpb.SubscriptionMode_ON_CHANGE},
				},
			},
		},
	}

	stream, err := client.Subscribe(ctx)
	if err != nil {
		log.Printf("[%s] Subscribe error: %v", router.Name, err)
		return
	}

	if err := stream.Send(req); err != nil {
		log.Printf("[%s] Send error: %v", router.Name, err)
		return
	}

	var mu sync.Mutex
	interfaceData := map[string]*InterfaceStat{}
	neighborData := map[string]*BGPNeighbor{}

	ticker := time.NewTicker(5 * time.Second)
	go func() {
		for range ticker.C {
			mu.Lock()
			msg := KafkaMessage{
				RouterName:   router.Name,
				Timestamp:    time.Now().Format(time.RFC3339),
				BGPNeighbors: []BGPNeighbor{},
				Interfaces:   []InterfaceStat{},
			}
			for _, v := range neighborData {
				msg.BGPNeighbors = append(msg.BGPNeighbors, *v)
			}
			for _, v := range interfaceData {
				msg.Interfaces = append(msg.Interfaces, *v)
			}

			data, _ := json.Marshal(msg)
			produceKafkaMessageJSON(data, producer)
			mu.Unlock()
		}
	}()

	for {
		resp, err := stream.Recv()
		if err != nil {
			log.Printf("[%s] Stream receive error: %v", router.Name, err)
			break
		}

		if update, ok := resp.Response.(*gpb.SubscribeResponse_Update); ok {
			for _, u := range update.Update.Update {
				pathStr := pathToString(u.Path)
				value := u.Val.GetUintVal()
				mu.Lock()
				switch {
				case strings.Contains(pathStr, "session-state"):
					ip := extractIP(pathStr)
					if neighborData[ip] == nil {
						neighborData[ip] = &BGPNeighbor{}
					}
					neighborData[ip].NeighborIP = ip
					neighborData[ip].State = u.Val.GetStringVal()

				case strings.Contains(pathStr, "in-octets"):
					ifName := extractInterface(pathStr)
					if interfaceData[ifName] == nil {
						interfaceData[ifName] = &InterfaceStat{InterfaceName: ifName}
					}
					interfaceData[ifName].InPackets = value

				case strings.Contains(pathStr, "out-octets"):
					ifName := extractInterface(pathStr)
					if interfaceData[ifName] == nil {
						interfaceData[ifName] = &InterfaceStat{InterfaceName: ifName}
					}
					interfaceData[ifName].OutPackets = value
				}
				mu.Unlock()
			}
		}
	}
}

func parseUpdate(routerName string, resp *gpb.SubscribeResponse) string {
	if update, ok := resp.Response.(*gpb.SubscribeResponse_Update); ok {
		for _, u := range update.Update.Update {
			pathStr := pathToString(u.Path)
			valueStr := fmt.Sprintf("%v", u.Val.GetValue())
			switch {
			case strings.Contains(pathStr, "session-state"):
				return fmt.Sprintf("Router:%s BGP Neighbour:%s STATE:%s", routerName, extractIP(pathStr), valueStr)
			case strings.Contains(pathStr, "in-octets"):
				return fmt.Sprintf("Router:%s Interface:%s inpackets:%s", routerName, extractInterface(pathStr), valueStr)
			case strings.Contains(pathStr, "out-octets"):
				return fmt.Sprintf("Router:%s Interface:%s outpackets:%s", routerName, extractInterface(pathStr), valueStr)
			}
		}
	}
	return ""
}

func toPath(p string) *gpb.Path {
	elems := strings.Split(p, "/")
	var pathElems []*gpb.PathElem
	for _, elem := range elems {
		if elem != "" {
			pathElems = append(pathElems, &gpb.PathElem{Name: elem})
		}
	}
	return &gpb.Path{Elem: pathElems}
}

func pathToString(p *gpb.Path) string {
	parts := []string{}
	for _, e := range p.Elem {
		parts = append(parts, e.Name)
	}
	return strings.Join(parts, "/")
}

func extractIP(path string) string {
	parts := strings.Split(path, "/")
	for i, part := range parts {
		if part == "neighbor" && i+1 < len(parts) {
			return parts[i+1]
		}
	}
	return "unknown"
}

func extractInterface(path string) string {
	parts := strings.Split(path, "/")
	for i, part := range parts {
		if part == "interface" && i+1 < len(parts) {
			return parts[i+1]
		}
	}
	return "unknown"
}

func produceKafkaMessageJSON(data []byte, producer sarama.SyncProducer) {
	msg := &sarama.ProducerMessage{
		Topic: kafkaTopic,
		Value: sarama.ByteEncoder(data),
	}
	_, _, err := producer.SendMessage(msg)
	if err != nil {
		log.Printf("Kafka send error: %v", err)
	}
}
