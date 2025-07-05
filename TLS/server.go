ckage main

import (
	"crypto/tls"
	"fmt"
	"log"
	"net/http"
)

func main() {
	certFile := "certs/server.crt"
	keyFile := "certs/server.key"

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, "Hello from secure TLS server!\n")
	})

	server := &http.Server{
		Addr:    ":8443",
		Handler: mux,
		TLSConfig: &tls.Config{
			MinVersion: tls.VersionTLS13,
		},
	}

	log.Println("🔐 TLS server started at https://localhost:8443")
	log.Fatal(server.ListenAndServeTLS(certFile, keyFile))
}