// simulator.go
//
// Simulate N routers each running a minimal gNMI Subscribe server.
// Each router simulates 100 BGP neighbors (flapping) + interfaces with counters.
// Uses JSON_IETF encoded TypedValue in SubscribeResponse_Update notifications.
//
// Usage: go run simulator.go
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math/rand"
	"net"
	"sync"
	"time"

	"google.golang.org/grpc"

	gnmi "github.com/openconfig/gnmi/proto/gnmi"
)

// Configuration
var (
	basePort       = flag.Int("base-port", 6000, "starting port for simulated routers")
	nRouters       = flag.Int("routers", 100, "number of simulated routers")
	nNeighbors     = flag.Int("neighbors", 100, "number of BGP neighbors per router")
	updateInterval = flag.Duration("interval", 2*time.Second, "notification interval")
)

// Router state structures
type SimInterface struct {
	Name      string `json:"name"`
	InOctets  uint64 `json:"in-octets"`
	OutOctets uint64 `json:"out-octets"`
}

type SimNeighbor struct {
	IP    string `json:"neighbor-address"`
	State string `json:"session-state"` // "ESTABLISHED"/"ACTIVE"/"IDLE"
}

type SimRouterState struct {
	sync.Mutex
	Name       string          `json:"router"`
	Interfaces []*SimInterface `json:"interfaces"`
	Neighbors  []*SimNeighbor  `json:"bgp_neighbors"`
}

// gNMI server implementing only Subscribe for streaming updates
type GnmiServer struct {
	gnmi.UnimplementedGNMIServer
	router   *SimRouterState
	interval time.Duration
}

func (s *GnmiServer) Subscribe(stream gnmi.GNMI_SubscribeServer) error {
	// For simplicity: read first SubscribeRequest and then start streaming notifications
	// (do not support multiple different subscription lists)
	req, err := stream.Recv()
	if err != nil {
		return err
	}
	_ = req // we ignore requested paths for simulator - always send bgp + interfaces updates

	ticker := time.NewTicker(s.interval)
	defer ticker.Stop()

	for {
		select {
		case <-stream.Context().Done():
			return stream.Context().Err()
		case t := <-ticker.C:
			// Build notifications for BGP neighbors and interface counters
			s.router.Lock()
			// create copy to avoid concurrency issues
			neighbors := make([]*SimNeighbor, len(s.router.Neighbors))
			for i, n := range s.router.Neighbors {
				neighbors[i] = &SimNeighbor{IP: n.IP, State: n.State}
			}
			ifaces := make([]*SimInterface, len(s.router.Interfaces))
			for i, inf := range s.router.Interfaces {
				ifaces[i] = &SimInterface{Name: inf.Name, InOctets: inf.InOctets, OutOctets: inf.OutOctets}
			}
			s.router.Unlock()

			// send one notification per neighbor and per interface (simpler for parsing)
			// Timestamp in nanoseconds:
			ts := t.UnixNano()

			// send neighbors updates (session-state)
			for _, n := range neighbors {
				// Path: /network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP,name=BGP]/bgp/neighbors/neighbor[neighbor-address=<ip>]/state/session-state
				path := &gnmi.Path{
					Elem: []*gnmi.PathElem{
						{Name: "network-instances"},
						{Name: "network-instance", Key: map[string]string{"name": "default"}},
						{Name: "protocols"},
						{Name: "protocol", Key: map[string]string{"identifier": "BGP", "name": "BGP"}},
						{Name: "bgp"},
						{Name: "neighbors"},
						{Name: "neighbor", Key: map[string]string{"neighbor-address": n.IP}},
						{Name: "state"},
						{Name: "session-state"},
					},
				}
				valMap := map[string]interface{}{"session-state": n.State}
				b, _ := json.Marshal(valMap)
				tv := &gnmi.TypedValue{Value: &gnmi.TypedValue_JsonIetfVal{JsonIetfVal: b}}
				update := &gnmi.Update{Path: path, Val: tv}
				notif := &gnmi.Notification{Timestamp: ts, Update: []*gnmi.Update{update}}
				resp := &gnmi.SubscribeResponse{Response: &gnmi.SubscribeResponse_Update{Update: notif}}
				if err := stream.Send(resp); err != nil {
					return err
				}
			}

			// send interface counters updates
			for _, inf := range ifaces {
				// in-octets
				pathIn := &gnmi.Path{
					Elem: []*gnmi.PathElem{
						{Name: "interfaces"},
						{Name: "interface", Key: map[string]string{"name": inf.Name}},
						{Name: "state"},
						{Name: "in-octets"},
					},
				}
				valIn := map[string]interface{}{"in-octets": inf.InOctets}
				bIn, _ := json.Marshal(valIn)
				tvIn := &gnmi.TypedValue{Value: &gnmi.TypedValue_JsonIetfVal{JsonIetfVal: bIn}}
				updateIn := &gnmi.Update{Path: pathIn, Val: tvIn}
				notifIn := &gnmi.Notification{Timestamp: ts, Update: []*gnmi.Update{updateIn}}
				respIn := &gnmi.SubscribeResponse{Response: &gnmi.SubscribeResponse_Update{Update: notifIn}}
				if err := stream.Send(respIn); err != nil {
					return err
				}

				// out-octets
				pathOut := &gnmi.Path{
					Elem: []*gnmi.PathElem{
						{Name: "interfaces"},
						{Name: "interface", Key: map[string]string{"name": inf.Name}},
						{Name: "state"},
						{Name: "out-octets"},
					},
				}
				valOut := map[string]interface{}{"out-octets": inf.OutOctets}
				bOut, _ := json.Marshal(valOut)
				tvOut := &gnmi.TypedValue{Value: &gnmi.TypedValue_JsonIetfVal{JsonIetfVal: bOut}}
				updateOut := &gnmi.Update{Path: pathOut, Val: tvOut}
				notifOut := &gnmi.Notification{Timestamp: ts, Update: []*gnmi.Update{updateOut}}
				respOut := &gnmi.SubscribeResponse{Response: &gnmi.SubscribeResponse_Update{Update: notifOut}}
				if err := stream.Send(respOut); err != nil {
					return err
				}
			}
		}
	}
}

// helper: create simulated router state
func newSimRouter(name string, nNeighbors int) *SimRouterState {
	r := &SimRouterState{
		Name: name,
	}
	// create a few interfaces
	r.Interfaces = []*SimInterface{
		{Name: "Ethernet1", InOctets: uint64(rand.Intn(1e6)), OutOctets: uint64(rand.Intn(1e6))},
		{Name: "Ethernet2", InOctets: uint64(rand.Intn(1e6)), OutOctets: uint64(rand.Intn(1e6))},
		{Name: "Management1", InOctets: uint64(rand.Intn(1e6)), OutOctets: uint64(rand.Intn(1e6))},
	}
	// neighbors
	r.Neighbors = make([]*SimNeighbor, 0, nNeighbors)
	for i := 0; i < nNeighbors; i++ {
		ip := fmt.Sprintf("10.%d.%d.%d", rand.Intn(250), rand.Intn(250), 10+i%240)
		state := []string{"ESTABLISHED", "ACTIVE", "IDLE"}[rand.Intn(3)]
		r.Neighbors = append(r.Neighbors, &SimNeighbor{IP: ip, State: state})
	}
	return r
}

// background updater that flaps neighbors and increments counters
func startBackgroundUpdater(r *SimRouterState, interval time.Duration) {
	go func() {
		t := time.NewTicker(interval / 2)
		defer t.Stop()
		for range t.C {
			r.Lock()
			// flap neighbors: small chance to toggle state
			for _, n := range r.Neighbors {
				// random flip
				if rand.Float64() < 0.05 { // 5% chance to change state
					n.State = []string{"ESTABLISHED", "ACTIVE", "IDLE"}[rand.Intn(3)]
				}
			}
			// increment interface counters with random deltas
			for _, inf := range r.Interfaces {
				inf.InOctets += uint64(100 + rand.Intn(10000))
				inf.OutOctets += uint64(50 + rand.Intn(8000))
			}
			r.Unlock()
		}
	}()
}

func startRouterServer(port int, routerName string, nNeighbors int, interval time.Duration, wg *sync.WaitGroup) {
	defer wg.Done()
	addr := fmt.Sprintf(":%d", port)
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("failed to listen on %s: %v", addr, err)
	}
	grpcServer := grpc.NewServer()
	state := newSimRouter(routerName, nNeighbors)
	startBackgroundUpdater(state, interval)

	gnmiServer := &GnmiServer{router: state, interval: interval}
	gnmi.RegisterGNMIServer(grpcServer, gnmiServer)

	log.Printf("Router %s listening on %s (neighbors=%d)", routerName, addr, nNeighbors)
	if err := grpcServer.Serve(lis); err != nil {
		log.Printf("Router %s server stopped: %v", routerName, err)
	}
}

func main() {
	flag.Parse()
	rand.Seed(time.Now().UnixNano())

	var wg sync.WaitGroup
	for i := 0; i < *nRouters; i++ {
		wg.Add(1)
		port := *basePort + i
		routerName := fmt.Sprintf("Router-%03d", i+1)
		go startRouterServer(port, routerName, *nNeighbors, *updateInterval, &wg)
		// small stagger to avoid bursts
		time.Sleep(5 * time.Millisecond)
	}
	wg.Wait()
}
