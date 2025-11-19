#!/usr/bin/env python3
"""
telemetry_to_kafka_clickhouse_fixed.py

Single-process pipeline:
  Kafka(telemetry-cpu) --consume--> detect cpu >= CPU_THRESHOLD -->
    1) produce anomaly JSON -> Kafka(telemetry-cpu-anomalies)
    2) insert anomaly rows -> ClickHouse table telemetry.cpu_anomalies_v2 (includes event_id)
  Offsets are committed only after produce+insert succeed for the processed batch.

This variant:
 - does a ClickHouse connectivity test at startup,
 - will CREATE TABLE IF NOT EXISTS telemetry.cpu_anomalies_v2 (POC friendly),
 - logs detailed insert failures and a sample of failed rows.
"""

import os
import json
import time
import logging
import signal
import uuid
from threading import Event

from kafka import KafkaConsumer, KafkaProducer
from clickhouse_driver import Client, errors as ch_errors

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("telemetry-pipeline-fixed")

# ----------------------------
# Config (env)
# ----------------------------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
INPUT_TOPIC = os.getenv("INPUT_TOPIC", "telemetry-cpu")
ANOMALY_TOPIC = os.getenv("ANOMALY_TOPIC", "telemetry-cpu-anomalies")
KAFKA_GROUP = os.getenv("KAFKA_GROUP", "telemetry-to-clickhouse")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "9000"))
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "telemetry")
CLICKHOUSE_TABLE = os.getenv("CLICKHOUSE_TABLE", "cpu_anomalies_v2")  # write into v2 by default
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "Sudhin12")

CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "95.0"))

BATCH_SIZE = int(os.getenv("BATCH_SIZE", "500"))              # number of messages to poll/process before periodic actions
ANOMALY_BATCH_SIZE = int(os.getenv("ANOMALY_BATCH_SIZE", "200"))  # rows to insert to ClickHouse per insert
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL", "5.0"))    # seconds
RETRY_COUNT = int(os.getenv("RETRY_COUNT", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "0.5"))

shutdown_event = Event()

# ----------------------------
# Signal handling
# ----------------------------
def signal_handler(sig, frame):
    logger.info("Received signal %s, shutting down...", sig)
    shutdown_event.set()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ----------------------------
# Kafka helpers
# ----------------------------
def create_consumer():
    consumer = KafkaConsumer(
        INPUT_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=KAFKA_GROUP,
        enable_auto_commit=False,   # manual commit after successful persist
        auto_offset_reset="earliest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8"))
    )
    return consumer

def create_producer():
    # acks should be integer (1) or 'all' (string). Use integer 1 for lower latency, or 'all' for stronger durability.
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        linger_ms=5,
        acks=1
    )
    return producer

# ----------------------------
# ClickHouse helpers (with checks & auto-create)
# ----------------------------
CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DB}.{CLICKHOUSE_TABLE} (
  event_id String,
  host String,
  ts UInt64,
  cpu_percent UInt8,
  reason String
) ENGINE = MergeTree()
ORDER BY (ts, host, event_id)
"""

def create_clickhouse_client_and_ensure_table():
    client = Client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DB,
        connect_timeout=5
    )

    # connectivity test
    try:
        client.execute("SELECT 1")
        logger.info("Connected to ClickHouse at %s:%s (db=%s)", CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_DB)
    except Exception as e:
        logger.exception("ClickHouse connection test failed: %s", e)
        raise

    # ensure database exists (some ClickHouse installs need explicit CREATE DATABASE)
    try:
        client.execute(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DB}")
    except Exception:
        logger.exception("Failed to ensure ClickHouse database exists; continuing (may already exist)")

    # create table if missing
    try:
        client.execute(CREATE_TABLE_SQL)
        logger.info("Ensured ClickHouse table %s.%s exists (POC create_table_if_missing)", CLICKHOUSE_DB, CLICKHOUSE_TABLE)
    except Exception as e:
        logger.exception("Failed to create/verify ClickHouse table: %s", e)
        raise

    return client

def insert_clickhouse_rows(client, rows):
    """
    rows: list of tuples shaped for the target table:
      (event_id, host, ts, cpu_percent, reason)
    """
    if not rows:
        return True
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            client.execute(
                f"INSERT INTO {CLICKHOUSE_TABLE} (event_id, host, ts, cpu_percent, reason) VALUES",
                rows
            )
            logger.info("Inserted %d rows into ClickHouse table %s.%s", len(rows), CLICKHOUSE_DB, CLICKHOUSE_TABLE)
            return True
        except ch_errors.Error as e:
            logger.warning("ClickHouse insert attempt %d/%d failed: %s", attempt, RETRY_COUNT, e)
            # log a small sample of rows to help debugging (do not print entire huge batches)
            try:
                logger.warning("Sample rows that failed insert: %s", rows[:5])
            except Exception:
                pass
            time.sleep(RETRY_BACKOFF * attempt)
        except Exception as e:
            logger.exception("Unexpected ClickHouse error on attempt %d/%d: %s", attempt, RETRY_COUNT, e)
            try:
                logger.warning("Sample rows that failed insert: %s", rows[:5])
            except Exception:
                pass
            time.sleep(RETRY_BACKOFF * attempt)
    # all retries exhausted
    logger.error("Failed to insert %d rows after %d attempts; dropping (sample rows): %s", len(rows), RETRY_COUNT, rows[:5])
    return False

# ----------------------------
# Flush helper: produce to Kafka and insert to ClickHouse
# ----------------------------
def _flush_anomalies(producer, ch_client, anomalies_for_kafka, anomalies_for_ch):
    """
    Produce anomalies to Kafka and insert into ClickHouse.
    anomalies_for_kafka: list of dicts (with event_id)
    anomalies_for_ch: list of tuples (event_id, host, ts, cpu, reason)
    Returns True on success, False on failure (do not commit offsets if False).
    """
    if not anomalies_for_kafka:
        return True

    # 1) produce to Kafka
    try:
        for rec in anomalies_for_kafka:
            producer.send(ANOMALY_TOPIC, rec)
        producer.flush(timeout=10)
        logger.info("Produced %d anomaly messages to Kafka topic %s", len(anomalies_for_kafka), ANOMALY_TOPIC)
    except Exception as e:
        logger.exception("Failed to produce anomalies to Kafka: %s", e)
        return False

    # 2) insert into ClickHouse
    ok = insert_clickhouse_rows(ch_client, anomalies_for_ch)
    return ok

# ----------------------------
# Main loop
# ----------------------------
def main():
    logger.info("Starting telemetry -> anomalies -> ClickHouse pipeline (fixed: event_id + table ensure)")
    consumer = create_consumer()
    producer = create_producer()
    ch_client = create_clickhouse_client_and_ensure_table()

    processed_count = 0
    last_flush_ts = time.time()

    anomalies_for_ch = []    # list of tuples for ClickHouse (event_id, host, ts, cpu, reason)
    anomalies_for_kafka = [] # list of dicts for producing to anomaly topic

    try:
        while not shutdown_event.is_set():
            records = consumer.poll(timeout_ms=1000, max_records=BATCH_SIZE)
            if not records:
                # timeout - flush by time if needed
                now = time.time()
                if anomalies_for_ch and (now - last_flush_ts >= FLUSH_INTERVAL):
                    logger.info("Flush interval reached: attempting to flush %d anomaly rows", len(anomalies_for_ch))
                    success = _flush_anomalies(producer, ch_client, anomalies_for_kafka, anomalies_for_ch)
                    if success:
                        consumer.commit()
                        anomalies_for_ch.clear()
                        anomalies_for_kafka.clear()
                        last_flush_ts = time.time()
                continue

            # iterate retrieved records
            for tp, msgs in records.items():
                for msg in msgs:
                    if shutdown_event.is_set():
                        break
                    processed_count += 1
                    rec = msg.value

                    # defensive parsing of cpu and timestamp
                    try:
                        cpu = float(rec.get("cpu_percent", 0))
                    except Exception:
                        logger.exception("Malformed cpu_percent, skipping: %s", rec)
                        continue

                    if cpu >= CPU_THRESHOLD:
                        host = rec.get("host", "unknown")
                        try:
                            ts = int(rec.get("timestamp", int(time.time() * 1000)))
                        except Exception:
                            ts = int(time.time() * 1000)
                        reason = rec.get("reason", f"cpu>={int(CPU_THRESHOLD)}")

                        # generate unique event id so inserts are always unique
                        event_id = str(uuid.uuid4())

                        # prepare ClickHouse tuple: (event_id, host, ts, cpu_percent, reason)
                        anomalies_for_ch.append((event_id, host, ts, int(cpu), reason))

                        # prepare Kafka message (include event_id so downstreams can dedupe if needed)
                        anomalies_for_kafka.append({
                            "event_id": event_id,
                            "host": host,
                            "timestamp": ts,
                            "cpu_percent": int(cpu),
                            "reason": reason
                        })

            # decide if we should flush
            now = time.time()
            if anomalies_for_ch and (len(anomalies_for_ch) >= ANOMALY_BATCH_SIZE or (now - last_flush_ts) >= FLUSH_INTERVAL):
                logger.info("Flushing %d anomalies (-> Kafka + ClickHouse)", len(anomalies_for_ch))
                success = _flush_anomalies(producer, ch_client, anomalies_for_kafka, anomalies_for_ch)
                if success:
                    try:
                        consumer.commit()
                        logger.info("Committed consumer offsets after successful flush")
                    except Exception:
                        logger.exception("Failed to commit offsets after successful flush")
                    anomalies_for_ch.clear()
                    anomalies_for_kafka.clear()
                    last_flush_ts = time.time()
                else:
                    logger.warning("Flush failed; will retry next cycle without committing offsets")

            # if we processed many messages but no anomalies, commit periodically to advance offsets
            if not anomalies_for_ch and processed_count >= BATCH_SIZE:
                try:
                    consumer.commit()
                    logger.info("Committed consumer offsets after processing %d messages (no anomalies)", processed_count)
                except Exception:
                    logger.exception("Failed to commit offsets")
                processed_count = 0

    except Exception as e:
        logger.exception("Fatal pipeline error: %s", e)
    finally:
        # final flush on shutdown
        try:
            if anomalies_for_ch:
                logger.info("Shutdown: final flush of %d anomalies", len(anomalies_for_ch))
                success = _flush_anomalies(producer, ch_client, anomalies_for_kafka, anomalies_for_ch)
                if success:
                    try:
                        consumer.commit()
                    except Exception:
                        logger.exception("Failed to commit offsets after final flush")
        except Exception:
            logger.exception("Error during final flush/commit")

        try:
            producer.flush(timeout=10)
        except Exception:
            pass
        try:
            producer.close()
        except Exception:
            pass
        try:
            consumer.close()
        except Exception:
            pass
        try:
            ch_client.disconnect()
        except Exception:
            pass
        logger.info("Pipeline stopped.")

if __name__ == "__main__":
    main()
