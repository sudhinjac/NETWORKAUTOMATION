# cpu_random_producer.py
import json
import time
import random
from kafka import KafkaProducer

KAFKA_BOOTSTRAP = "localhost:9092"
TOPIC = "telemetry-cpu"

producer = KafkaProducer(
    bootstrap_servers=KAFKA_BOOTSTRAP,
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

print("Producing random CPU values...")

while True:
    cpu_value = random.randint(0, 100)

    msg = {
        "host": "device-1",
        "timestamp": int(time.time() * 1000),
        "cpu_percent": cpu_value
    }

    print("Sending:", msg)
    producer.send(TOPIC, msg)
    producer.flush()
    time.sleep(1)
