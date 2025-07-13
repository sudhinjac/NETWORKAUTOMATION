from confluent_kafka import Consumer
import json

conf = {
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'bgp-test',
    'auto.offset.reset': 'earliest'
}

consumer = Consumer(conf)
consumer.subscribe(['bgp-status'])

print("Reading Kafka messages...")
while True:
    msg = consumer.poll(1.0)
    if msg is None:
        continue
    if msg.error():
        print("Error:", msg.error())
        continue

    try:
        data = json.loads(msg.value().decode("utf-8"))
        print(data)
    except Exception as e:
        print("Failed to parse:", e)