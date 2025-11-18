# bgp_alerts_flink_udf.py
import json
from pyflink.table import EnvironmentSettings, TableEnvironment, DataTypes
from pyflink.table.udf import udf

# ---------- helper UDFs ----------
@udf(result_type=DataTypes.BIGINT())
def total_in_packets(interfaces):
    if interfaces is None:
        return 0
    total = 0
    try:
        for it in interfaces:
            # interface can be Row-like or dict-like depending on planner/format
            if isinstance(it, dict):
                val = it.get("in_packets") or it.get("inPackets") or 0
            else:
                # Row-like: attribute may be available
                val = getattr(it, "in_packets", None)
                if val is None:
                    try:
                        # fallback to index access
                        val = it[1]
                    except Exception:
                        val = 0
            try:
                total += int(val or 0)
            except Exception:
                pass
    except Exception:
        return 0
    return total

@udf(result_type=DataTypes.BOOLEAN())
def neighbor_down(bgp_neighbors):
    if bgp_neighbors is None:
        return False
    try:
        for nb in bgp_neighbors:
            if isinstance(nb, dict):
                state = nb.get("state") or nb.get("State") or ""
            else:
                state = getattr(nb, "state", None)
                if state is None:
                    try:
                        state = nb[1]
                    except Exception:
                        state = ""
            if str(state).strip().upper() != "ESTABLISHED":
                return True
    except Exception:
        return False
    return False

@udf(result_type=DataTypes.STRING())
def make_detail(ts, router, interfaces, bgp_neighbors):
    # build a compact JSON detail; default=str will convert timestamps etc.
    d = {
        "ts": ts,
        "router": router,
        "interfaces": interfaces if interfaces is not None else [],
        "bgp_neighbors": bgp_neighbors if bgp_neighbors is not None else []
    }
    try:
        return json.dumps(d, default=str)
    except Exception:
        # fallback to safe string if json fails
        return json.dumps({
            "ts": str(ts),
            "router": str(router)
        })

# ---------- main job ----------
def main():
    env_settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(env_settings)

    # register UDFs
    t_env.create_temporary_system_function("total_in_packets", total_in_packets)
    t_env.create_temporary_system_function("neighbor_down", neighbor_down)
    t_env.create_temporary_system_function("make_detail", make_detail)

    # Kafka source (ts is STRING to avoid implicit timestamp parse issues)
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
        'properties.group.id' = 'ch_bgp_consumer_flink',
        'scan.startup.mode' = 'earliest-offset',
        'format' = 'json',
        'json.fail-on-missing-field' = 'false',
        'json.ignore-parse-errors' = 'true'
    )
    """)

    # Print sink (TaskManager stdout)
    t_env.execute_sql("""
    CREATE TABLE alerts_print (
        alert_ts STRING,
        router STRING,
        reason STRING,
        detail STRING
    ) WITH ('connector' = 'print')
    """)

    # Kafka sink for alerts
    t_env.execute_sql("""
    CREATE TABLE alerts_kafka (
        alert_ts STRING,
        router STRING,
        reason STRING,
        detail STRING
    ) WITH (
        'connector' = 'kafka',
        'topic' = 'bgp-alerts',
        'properties.bootstrap.servers' = 'localhost:9092',
        'format' = 'json'
    )
    """)

    # Insert alerts into both sinks; use UDF make_detail to produce JSON detail string
    insert_sql = """
    INSERT INTO alerts_kafka
    SELECT
      COALESCE(ts, CAST(CURRENT_TIMESTAMP AS STRING)) AS alert_ts,
      router,
      CASE
        WHEN neighbor_down(bgp_neighbors) THEN 'neighbor_down'
        WHEN total_in_packets(interfaces) = 0 THEN 'zero_in_packets'
        ELSE 'other'
      END AS reason,
      make_detail(ts, router, interfaces, bgp_neighbors) AS detail
    FROM bgp_kafka
    WHERE neighbor_down(bgp_neighbors) OR total_in_packets(interfaces) = 0
    """
    t_env.execute_sql(insert_sql)

    t_env.execute_sql("""
    INSERT INTO alerts_print
    SELECT
      COALESCE(ts, CAST(CURRENT_TIMESTAMP AS STRING)) AS alert_ts,
      router,
      CASE
        WHEN neighbor_down(bgp_neighbors) THEN 'neighbor_down'
        WHEN total_in_packets(interfaces) = 0 THEN 'zero_in_packets'
        ELSE 'other'
      END AS reason,
      make_detail(ts, router, interfaces, bgp_neighbors) AS detail
    FROM bgp_kafka
    WHERE neighbor_down(bgp_neighbors) OR total_in_packets(interfaces) = 0
    """)

    print("Submitted PyFlink job: alerts -> print + kafka (bgp-alerts).")

if __name__ == "__main__":
    main()
