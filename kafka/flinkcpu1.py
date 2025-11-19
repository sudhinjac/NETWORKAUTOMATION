#!/usr/bin/env python3
"""
anomaly_clickhouse_writer.py

Consumes JSON anomaly messages from Kafka topic (telemetry-cpu-anomalies)
and inserts them into ClickHouse in batches.

Environment vars (defaults):
  KAFKA_BOOTSTRAP=localhost:9092
  ANOMALY_TOPIC=telemetry-cpu-anomalies
  KAFKA_GROUP=clickhouse-writer
  CLICKHOUSE_HOST=localhost
  CLICKHOUSE_PORT=9000
  CLICKHOUSE_DB=telemetry
  CLICKHOUSE_TABLE=cpu_anomalies
  CLICKHOUSE_USER=default
  CLICKHOUSE_PASSWORD=
  BATCH_SIZE=200
  FLUSH_INTERVAL=5.0
  RETRY_COUNT=3
  RETRY_BACKOFF=0.5
"""

import os
import signal
import sys
import json
import time
import logging
from threading import Event

from kafka import KafkaConsumer
from clickhouse_driver import Client, errors as ch_errors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("anomaly-writer")

# config from env
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
ANOMALY_TOPIC = os.getenv("ANOMALY_TOPIC", "telemetry-cpu-anomalies")
KAFKA_GROUP = os.getenv("KAFKA_GROUP", "clickhouse-writer")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "telemetry")
CLICKHOUSE_TABLE = os.getenv("CLICKHOUSE_TABLE", "cpu_anomalies")
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "Sudhin12")

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "200"))
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL", "5.0"))
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "0.5"))

shutdown_event = Event()

def signal_handler(signum, frame):
    logger.info("Received signal %s, shutting down...", signum)
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def create_consumer():
    consumer = KafkaConsumer(
        ANOMALY_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=1000  # so poll() returns even if no data (helps shutdown)
    )
    return consumer

def create_clickhouse_client():
    client = Client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT, user=CLICKHOUSE_USER,
                    password=CLICKHOUSE_PASSWORD, database=CLICKHOUSE_DB, connect_timeout=5)
    return client

def insert_rows(client, rows):
    if not rows:
        return
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            client.execute(
                f"INSERT INTO {CLICKHOUSE_TABLE} (host, timestamp, cpu_percent, reason) VALUES",
                rows
            )
            logger.info("Inserted %d rows into ClickHouse", len(rows))
            return True
        except ch_errors.Error as e:
            logger.warning("ClickHouse insert attempt %d/%d failed: %s", attempt, RETRY_COUNT, e)
            time.sleep(RETRY_BACKOFF * attempt)
        except Exception as e:
            logger.exception("Unexpected error inserting to ClickHouse: %s", e)
            time.sleep(RETRY_BACKOFF * attempt)
    logger.error("Dropping %d rows after %d failed attempts", len(rows), RETRY_COUNT)
    return False

def main():
    logger.info("Starting anomaly ClickHouse writer...")
    consumer = create_consumer()
    client = create_clickhouse_client()
    buffer = []
    last_flush_ts = time.time()

    try:
        while not shutdown_event.is_set():
            # poll consumer
            for msg in consumer:
                # msg.value is already json-decoded
                try:
                    record = msg.value
                    # expected fields: host, timestamp, cpu_percent, optional reason
                    host = record.get("host")
                    ts = int(record.get("timestamp"))
                    cpu = int(record.get("cpu_percent"))
                    reason = record.get("reason", "cpu>95")
                except Exception:
                    logger.exception("Malformed record, skipping: %s", msg.value)
                    continue

                buffer.append((host, ts, cpu, reason))

                # flush by size
                if len(buffer) >= BATCH_SIZE:
                    insert_rows(client, buffer)
                    buffer = []
                    last_flush_ts = time.time()

                # check shutdown
                if shutdown_event.is_set():
                    break

            # timeout or no messages: flush by time
            now = time.time()
            if buffer and (now - last_flush_ts) >= FLUSH_INTERVAL:
                insert_rows(client, buffer)
                buffer = []
                last_flush_ts = now

        # graceful shutdown: flush remaining
        if buffer:
            logger.info("Flushing remaining %d rows before exit", len(buffer))
            insert_rows(client, buffer)

    except Exception as e:
        logger.exception("Fatal error in writer: %s", e)
    finally:
        try:
            consumer.close()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass
        logger.info("Writer stopped.")

if __name__ == "__main__":
    main()
