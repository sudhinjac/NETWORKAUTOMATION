# 1) make sure FLINK_HOME is set correctly (adjust if needed)
export FLINK_HOME="$HOME/flink-1.19.3"
echo "FLINK_HOME=$FLINK_HOME"

# 2) find the tarball (assumes it's flink-1.19.3-bin-*.tgz somewhere)
TARBALL=$(ls -1 .. | egrep 'flink-1.19.3-bin.*tgz' || true)
if [ -z "$TARBALL" ]; then
  TARBALL=$(ls -1 | egrep 'flink-1.19.3-bin.*tgz' || true)
fi
if [ -z "$TARBALL" ]; then
  echo "Tarball not found in current or parent dir. Place flink-1.19.3-bin-*.tgz here or adjust TARBALL."
  exit 1
fi
# normalize full path
if [ ! -f "$TARBALL" ]; then
  # if TARBALL is relative name in parent dir
  if [ -f "../$TARBALL" ]; then
    TARBALL="$(pwd)/../$TARBALL"
  else
    TARBALL="$(pwd)/$TARBALL"
  fi
fi
echo "Using tarball: $TARBALL"

# 3) quick list of potentially required jars inside the tarball (planner, kafka, pekko/akka)
echo "Listing matching jar names inside tarball:"
tar -tzf "$TARBALL" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka|pekko|akka|slf4j|logging' || true

# 4) extract lib/ from tarball into a temp dir
TMP_DIR=/tmp/flink_extract_$RANDOM
rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
tar -xzf "$TARBALL" -C "$TMP_DIR" "flink-1.19.3/lib" || { echo "Extraction failed"; exit 1; }
EX_LIB="$TMP_DIR/flink-1.19.3/lib"
echo "Extracted lib to: $EX_LIB"
ls -1 "$EX_LIB" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka|pekko|akka|slf4j|log4j' || true

# 5) copy the needed jars from extracted lib to FLINK_HOME/lib
mkdir -p "$FLINK_HOME/lib"
cp -v "$EX_LIB"/flink-table-planner-blink*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/flink-table-planner-loader*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/flink-sql-connector-kafka*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
# Copy pekko/akka and related jars if present (planner runtime deps)
cp -v "$EX_LIB"/*pekko*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/*akka*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
# copy any logging/slf4j jars that tarball contains (avoid duplicates if present)
cp -v "$EX_LIB"/log4j* "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/*slf4j* "$FLINK_HOME/lib/" 2>/dev/null || true

# 6) prefer blink planner — remove planner-loader if both present to avoid 'multiple factories' ambiguity
if ls "$FLINK_HOME/lib"/flink-table-planner-blink*1.19.3*.jar >/dev/null 2>&1; then
  echo "Blink planner present; removing planner-loader jars to avoid duplicate factories."
  rm -vf "$FLINK_HOME/lib"/flink-table-planner-loader* 2>/dev/null || true
fi

# 7) show final relevant jars in FLINK lib
echo
echo "=== Final list of planner/kafka/pekko jars in $FLINK_HOME/lib ==="
ls -1 "$FLINK_HOME/lib" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka|pekko|akka|slf4j|log4j' || true
echo "==============================================================="

# 8) ensure the flink CLI exists and is executable
if [ -x "$FLINK_HOME/bin/flink" ]; then
  echo "Flink CLI ready at $FLINK_HOME/bin/flink"
else
  echo "Flink CLI not found or not executable at $FLINK_HOME/bin/flink — check FLINK_HOME. Current dir listing:"
  ls -l "$FLINK_HOME/bin" || true
fi

# 9) restart flink cleanly (stop -> start)
"$FLINK_HOME/bin/stop-cluster.sh" || true
sleep 1
"$FLINK_HOME/bin/start-cluster.sh"

# 10) show last 120 lines of Flink logs to inspect any runtime errors
sleep 2
echo "Tail last 120 lines of logs:"
tail -n 120 "$FLINK_HOME/log/"*standalonesession*.log || true
