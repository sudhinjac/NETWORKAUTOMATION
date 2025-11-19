# flink_cpu_anomaly_random.py
import json
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream.connectors import FlinkKafkaConsumer, FlinkKafkaProducer
from pyflink.common.typeinfo import Types

KAFKA_BOOTSTRAP = "localhost:9092"
INPUT_TOPIC = "telemetry-cpu"
ANOMALY_TOPIC = "telemetry-cpu-anomalies"

def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)

    consumer = FlinkKafkaConsumer(
        topics=INPUT_TOPIC,
        deserialization_schema=SimpleStringSchema(),
        properties={
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "group.id": "flink-cpu-anomaly"
        }
    )

    ds = env.add_source(consumer)

    parsed = ds.map(lambda s: json.loads(s), output_type=Types.PICKLED_BYTE_ARRAY())

    anomalies = parsed.filter(lambda m: float(m["cpu_percent"]) > 95.0)

    anomalies.map(
        lambda a: f"⚠️  ANOMALY: CPU={a['cpu_percent']} Host={a['host']}",
        output_type=Types.STRING()
    ).print()

    producer = FlinkKafkaProducer(
        topic=ANOMALY_TOPIC,
        serialization_schema=SimpleStringSchema(),
        producer_config={"bootstrap.servers": KAFKA_BOOTSTRAP}
    )

    anomalies.map(lambda a: json.dumps(a), output_type=Types.STRING()) \
             .add_sink(producer)

    env.execute("CPU Random Anomaly Detector")

if __name__ == "__main__":
    main()
