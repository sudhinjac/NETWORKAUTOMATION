# bgp_flink_no_unnest.py
from pyflink.table import EnvironmentSettings, TableEnvironment

def main():
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # Kafka source DDL: map timestamp -> ts
    t_env.execute_sql("""
    CREATE TABLE bgp_kafka (
        ts TIMESTAMP(3),
        router STRING,
        interfaces ARRAY<ROW<name STRING, in_packets BIGINT>>,
        bgp_neighbors ARRAY<ROW<neighbor_ip STRING, state STRING>>,
        WATERMARK FOR ts AS ts - INTERVAL '5' SECOND
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'bgp-telemetry',
        'properties.bootstrap.servers' = 'localhost:9092',
        'properties.group.id' = 'flink-bgp-consumer',
        'scan.startup.mode' = 'earliest-offset',
        'format' = 'json',
        'json.fail-on-missing-field' = 'false',
        'json.ignore-parse-errors' = 'true',
        'json.timestamp-format.standard' = 'ISO-8601'
    )
    """)

    # Print raw events
    t_env.execute_sql("""
    CREATE TABLE print_raw (
        ts TIMESTAMP(3),
        router STRING,
        interfaces ARRAY<ROW<name STRING, in_packets BIGINT>>,
        bgp_neighbors ARRAY<ROW<neighbor_ip STRING, state STRING>>
    ) WITH ('connector' = 'print')
    """)

    t_env.execute_sql("INSERT INTO print_raw SELECT ts, router, interfaces, bgp_neighbors FROM bgp_kafka")

    # Simple per-router 1-minute tumbling aggregation (counts)
    t_env.execute_sql("""
    CREATE TABLE router_counts_print (
        win_end TIMESTAMP(3),
        router STRING,
        cnt BIGINT
    ) WITH ('connector' = 'print')
    """)

    t_env.execute_sql("""
    INSERT INTO router_counts_print
    SELECT
      TUMBLE_END(ts, INTERVAL '1' MINUTE) AS win_end,
      router,
      COUNT(*) AS cnt
    FROM bgp_kafka
    GROUP BY TUMBLE(ts, INTERVAL '1' MINUTE), router
    """)

    print("Submitted minimal PyFlink job: raw prints + per-router 1-min counts.")
    # job runs in cluster until cancelled

if __name__ == "__main__":
    main()
