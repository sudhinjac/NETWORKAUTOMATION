from pyflink.table import EnvironmentSettings, TableEnvironment

# Minimal robust PyFlink job for reading JSON from Kafka and printing + 1-min counts.
# Saves you from repeated errors: use this file with
#   $FLINK_HOME/bin/flink run -py /path/to/bgp_flink_no_unnest.py

def main():
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # Kafka source DDL
    # - Ensure your Kafka messages have an ISO-8601 timestamp string in field `ts` or `timestamp`.
    # - Flink's JSON format will convert the timestamp string to TIMESTAMP(3) when json.timestamp-format.standard is set.
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
        'properties.group.id' = 'ch_bgp_consumer_local_001',
        'scan.startup.mode' = 'earliest-offset',
        'format' = 'json',
        'json.fail-on-missing-field' = 'false',
        'json.ignore-parse-errors' = 'true',
        'json.timestamp-format.standard' = 'ISO-8601'
    )
    """)

    # Print sink: printed rows will appear in the TaskExecutor logs (stdout) of the running Flink TaskManager(s).
    t_env.execute_sql("""
    CREATE TABLE print_raw (
        ts TIMESTAMP(3),
        router STRING,
        interfaces ARRAY<ROW<name STRING, in_packets BIGINT>>,
        bgp_neighbors ARRAY<ROW<neighbor_ip STRING, state STRING>>
    ) WITH ('connector' = 'print')
    """)

    # Submit streaming inserts (these will run until job cancelled)
    t_env.execute_sql("INSERT INTO print_raw SELECT ts, router, interfaces, bgp_neighbors FROM bgp_kafka")

    # 1-minute tumbling aggregation example: counts per router
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

    print("Submitted PyFlink job: print_raw + router_counts_print")


if __name__ == '__main__':
    main()
