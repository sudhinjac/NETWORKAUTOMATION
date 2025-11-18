# bgp_flink_file_sink_checkpointed.py
from pyflink.table import EnvironmentSettings, TableEnvironment

def main():
    # create streaming TableEnvironment
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # === enable checkpointing (important: filesystem sink commits on checkpoints) ===
    # checkpoint every 5 seconds
    t_env.get_config().get_configuration().set_string("execution.checkpointing.interval", "5s")
    # set checkpoint directory (use file:// for local)
    t_env.get_config().get_configuration().set_string("state.checkpoints.dir", "file:///tmp/flink_checkpoints")
    # optional: set checkpointing mode (AT_LEAST_ONCE or EXACTLY_ONCE)
    t_env.get_config().get_configuration().set_string("execution.checkpointing.mode", "EXACTLY_ONCE")

    # Kafka source table (keep timestamp as STRING to avoid parsing issues)
    t_env.execute_sql("""
    CREATE TABLE bgp_kafka (
        ts STRING,
        router STRING,
        interfaces ARRAY<ROW<name STRING, in_packets BIGINT>>,
        bgp_neighbors ARRAY<ROW<neighbor_ip STRING, state STRING>>
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'bgp-telemetry',
        'properties.bootstrap.servers' = 'localhost:9092',
        -- use a distinct group id so you can monitor consumer group
        'properties.group.id' = 'ch_bgp_consumer_flink',
        'scan.startup.mode' = 'earliest-offset',
        'format' = 'json',
        'json.fail-on-missing-field' = 'false',
        'json.ignore-parse-errors' = 'true'
    )
    """)

    # filesystem sink
    t_env.execute_sql("""
    CREATE TABLE file_sink (
        ts STRING,
        router STRING,
        interfaces ARRAY<ROW<name STRING, in_packets BIGINT>>,
        bgp_neighbors ARRAY<ROW<neighbor_ip STRING, state STRING>>
    ) WITH (
        'connector' = 'filesystem',
        'path' = 'file:///tmp/flink_bgp_out',
        'format' = 'json',
        -- use number-first durations (works with Flink parse)
        'sink.rolling-policy.rollover-interval' = '5 s',
        'sink.rolling-policy.check-interval' = '2 s'
    )
    """)

    # submit streaming insert (runs until cancelled)
    t_env.execute_sql("INSERT INTO file_sink SELECT ts, router, interfaces, bgp_neighbors FROM bgp_kafka")
    print("Submitted job: file_sink -> /tmp/flink_bgp_out (checkpointing ON every 5s).")

if __name__ == "__main__":
    main()
