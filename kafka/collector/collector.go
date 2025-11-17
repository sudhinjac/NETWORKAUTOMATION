// collector.go
//
// Connect to a set of gNMI servers (simulators), subscribe to BGP neighbor session-state
// and interface counters, normalize values and write canonical JSON to Kafka topic.
//
// Usage: go run collector.go
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/segmentio/kafka-go"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// Config
var (
	kafkaBroker = "localhost:9092"
	kafkaTopic  = "bgp-telemetry"
	basePort    = 6000
	nRouters    = 100
)

// Canonical message structure
type InterfaceStat struct {
	Name       string `json:"name"`
	InPackets  uint64 `json:"in_packets,omitempty"`
	OutPackets uint64 `json:"out_packets,omitempty"`
}

type BgpNeighbor struct {
	NeighborIP string `json:"neighbor_ip"`
	State      string `json:"state"`
}

type CanonicalMessage struct {
	Router       string          `json:"router"`
	Timestamp    string          `json:"timestamp"` // RFC3339
	Interfaces   []InterfaceStat `json:"interfaces"`
	BGPNeighbors []BgpNeighbor   `json:"bgp_neighbors"`
}

// helper: build the gNMI path for subscription
func pathForBGPState() *gnmi.Path {
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

func pathForInterfaceIn() *gnmi.Path {
	return &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "interfaces"},
			{Name: "interface"},
			{Name: "state"},
			{Name: "in-octets"},
		},
	}
}

func pathForInterfaceOut() *gnmi.Path {
	return &gnmi.Path{
		Elem: []*gnmi.PathElem{
			{Name: "interfaces"},
			{Name: "interface"},
			{Name: "state"},
			{Name: "out-octets"},
		},
	}
}

// decodeTypedValue returns parsed JSON or scalar value
func decodeTypedValue(tv *gnmi.TypedValue) (interface{}, error) {
	if tv == nil {
		return nil, nil
	}
	// prefer json_ietf_val
	if b := tv.GetJsonIetfVal(); len(b) > 0 {
		var v interface{}
		if err := json.Unmarshal(b, &v); err == nil {
			return v, nil
		}
		return string(b), nil
	}
	// fallback: json_val (OpenConfig)
	if b := tv.GetJsonVal(); len(b) > 0 {
		var v interface{}
		if err := json.Unmarshal(b, &v); err == nil {
			return v, nil
		}
		return string(b), nil
	}
	if s := tv.GetStringVal(); s != "" {
		return s, nil
	}
	if u := tv.GetUintVal(); u != 0 {
		return u, nil
	}
	if i := tv.GetIntVal(); i != 0 {
		return i, nil
	}
	if b := tv.GetBytesVal(); len(b) > 0 {
		return b, nil
	}
	if b := tv.GetBoolVal(); b {
		return b, nil
	}
	return nil, nil
}

func pathToString(p *gnmi.Path) string {
	parts := make([]string, 0, len(p.Elem))
	for _, e := range p.Elem {
		if len(e.Key) > 0 {
			// produce name[key=val] style
			kv := make([]string, 0, len(e.Key))
			for k, v := range e.Key {
				kv = append(kv, fmt.Sprintf("%s=%s", k, v))
			}
			parts = append(parts, fmt.Sprintf("%s[%s]", e.Name, strings.Join(kv, ",")))
		} else {
			parts = append(parts, e.Name)
		}
	}
	return "/" + strings.Join(parts, "/")
}

// normalize a path string to extract neighbor ip or interface name
func extractNeighborFromPath(p *gnmi.Path) (string, bool) {
	for _, e := range p.Elem {
		if e.Name == "neighbor" {
			if ip, ok := e.Key["neighbor-address"]; ok {
				return ip, true
			}
		}
	}
	return "", false
}

func extractInterfaceFromPath(p *gnmi.Path) (string, bool) {
	for _, e := range p.Elem {
		if e.Name == "interface" {
			if name, ok := e.Key["name"]; ok {
				return name, true
			}
		}
	}
	return "", false
}

// collector per-router: subscribe and emit canonical messages periodically
func collectRouter(routerName, addr string, writer *kafka.Writer, wg *sync.WaitGroup) {
	defer wg.Done()
	// keep trying to connect
	for {
		log.Printf("[%s] Connecting to %s ...", routerName, addr)
		conn, err := grpc.Dial(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
		if err != nil {
			log.Printf("[%s] dial error: %v; retrying in 2s", routerName, err)
			time.Sleep(2 * time.Second)
			continue
		}
		client := gnmi.NewGNMIClient(conn)
		ctx := context.Background()

		// Build subscription list
		subList := &gnmi.SubscriptionList{
			Mode: gnmi.SubscriptionList_STREAM,
			Subscription: []*gnmi.Subscription{
				{Path: pathForBGPState(), Mode: gnmi.SubscriptionMode_ON_CHANGE},
				{Path: pathForInterfaceIn(), Mode: gnmi.SubscriptionMode_ON_CHANGE},
				{Path: pathForInterfaceOut(), Mode: gnmi.SubscriptionMode_ON_CHANGE},
			},
			Encoding: gnmi.Encoding_JSON_IETF,
		}
		req := &gnmi.SubscribeRequest{Request: &gnmi.SubscribeRequest_Subscribe{Subscribe: subList}}

		stream, err := client.Subscribe(ctx)
		if err != nil {
			log.Printf("[%s] Subscribe error: %v; reconnecting...", routerName, err)
			conn.Close()
			time.Sleep(2 * time.Second)
			continue
		}

		// send request
		if err := stream.Send(req); err != nil {
			log.Printf("[%s] send SubscribeRequest error: %v; reconnecting...", routerName, err)
			conn.Close()
			time.Sleep(2 * time.Second)
			continue
		}

		// local state maps to assemble per-router canonical message
		var mu sync.Mutex
		ifaces := map[string]InterfaceStat{}
		neighs := map[string]BgpNeighbor{}
		lastEmit := time.Now()

		// spawn reader goroutine
		readerDone := make(chan struct{})
		go func() {
			defer close(readerDone)
			for {
				resp, err := stream.Recv()
				if err != nil {
					log.Printf("[%s] stream.Recv error: %v", routerName, err)
					return
				}
				switch r := resp.Response.(type) {
				case *gnmi.SubscribeResponse_Update:
					notif := r.Update
					ts := time.Unix(0, notif.GetTimestamp())
					for _, u := range notif.Update {
						decoded, err := decodeTypedValue(u.Val)
						if err != nil {
							continue
						}
						// check if neighbor
						if ip, ok := extractNeighborFromPath(u.Path); ok {
							// decoded may be map[string]interface{}{"session-state":"ESTABLISHED"}
							state := ""
							switch vv := decoded.(type) {
							case string:
								state = strings.ToUpper(vv)
							case map[string]interface{}:
								// try common keys
								if s, found := vv["session-state"]; found {
									if ss, ok := s.(string); ok {
										state = strings.ToUpper(ss)
									}
								} else {
									// fallback: search for string values
									for _, v2 := range vv {
										if ss, ok := v2.(string); ok {
											state = strings.ToUpper(ss)
											break
										}
									}
								}
							}
							mu.Lock()
							neighs[ip] = BgpNeighbor{NeighborIP: ip, State: state}
							mu.Unlock()
							_ = ts
						} else if ifName, ok := extractInterfaceFromPath(u.Path); ok {
							// is it in or out?
							leaf := ""
							if len(u.Path.Elem) > 0 {
								leaf = u.Path.Elem[len(u.Path.Elem)-1].Name
							}
							mu.Lock()
							is := ifaces[ifName]
							is.Name = ifName
							switch v := decoded.(type) {
							case float64:
								// JSON numbers decode as float64
								if leaf == "in-octets" {
									is.InPackets = uint64(v)
								} else if leaf == "out-octets" {
									is.OutPackets = uint64(v)
								}
							case map[string]interface{}:
								// might be {"in-octets":1234}
								if leaf == "in-octets" {
									if vv, ok := v["in-octets"]; ok {
										if fv, ok2 := vv.(float64); ok2 {
											is.InPackets = uint64(fv)
										}
									}
								} else if leaf == "out-octets" {
									if vv, ok := v["out-octets"]; ok {
										if fv, ok2 := vv.(float64); ok2 {
											is.OutPackets = uint64(fv)
										}
									}
								}
							case string:
								// try parse
							case uint64:
								if leaf == "in-octets" {
									is.InPackets = v
								} else if leaf == "out-octets" {
									is.OutPackets = v
								}
							case int64:
								if leaf == "in-octets" {
									is.InPackets = uint64(v)
								} else if leaf == "out-octets" {
									is.OutPackets = uint64(v)
								}
							}
							ifaces[ifName] = is
							mu.Unlock()
						} else {
							// unknown path - ignore
						}
					}
				case *gnmi.SubscribeResponse_SyncResponse:
					log.Printf("[%s] sync response", routerName)
				case *gnmi.SubscribeResponse_Error:
					log.Printf("[%s] gnmi error: %v", routerName, r.Error)
				default:
					// ignore
				}

				// periodically write an aggregated message (e.g., every 3 seconds)
				if time.Since(lastEmit) > 3*time.Second {
					lastEmit = time.Now()
					mu.Lock()
					cm := CanonicalMessage{
						Router:       routerName,
						Timestamp:    time.Now().UTC().Format(time.RFC3339),
						Interfaces:   make([]InterfaceStat, 0, len(ifaces)),
						BGPNeighbors: make([]BgpNeighbor, 0, len(neighs)),
					}
					for _, v := range ifaces {
						cm.Interfaces = append(cm.Interfaces, v)
					}
					for _, v := range neighs {
						cm.BGPNeighbors = append(cm.BGPNeighbors, v)
					}
					mu.Unlock()
					// marshal and write to kafka
					b, _ := json.Marshal(cm)
					msg := kafka.Message{
						Key:   []byte(routerName),
						Value: b,
					}
					// try write with timeout
					ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
					_ = writer.WriteMessages(ctx, msg)
					cancel()
					log.Printf("[%s] wrote %d bytes to kafka", routerName, len(b))
				}
			}
		}()

		// wait for reader to end (error) then reconnect
		<-readerDone
		conn.Close()
		log.Printf("[%s] disconnected; will reconnect in 2s", routerName)
		time.Sleep(2 * time.Second)
	}
}

func main() {
	// create kafka writer
	w := kafka.NewWriter(kafka.WriterConfig{
		Brokers:  []string{kafkaBroker},
		Topic:    kafkaTopic,
		Balancer: &kafka.LeastBytes{},
	})
	defer w.Close()

	// spawn collectors for all routers
	var wg sync.WaitGroup
	for i := 0; i < nRouters; i++ {
		wg.Add(1)
		port := basePort + i
		routerName := fmt.Sprintf("Router-%03d", i+1)
		addr := fmt.Sprintf("localhost:%d", port)
		go collectRouter(routerName, addr, w, &wg)
		// slight stagger
		time.Sleep(5 * time.Millisecond)
	}

	wg.Wait()
}
