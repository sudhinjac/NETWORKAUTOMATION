#!/bin/bash

mkdir -p certs
cd certs

# 1. Generate CA private key & self-signed cert
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -subj "/CN=MyCA" -days 365 -out ca.crt

# 2. Generate Server key & CSR
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "/CN=localhost" -out server.csr

# 3. Sign server cert with CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -sha256

echo "✅ Certificates generated in ./certs/"