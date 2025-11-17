# Set these if different
export FLINK_HOME=~/flink-1.19.3
TARBALL=~/flink-1.19.3-bin-scala_2.12.tgz

# stop flink
$FLINK_HOME/bin/stop-cluster.sh || true

# prepare temp dir
TMP=/tmp/flink_extract_$RANDOM
rm -rf "$TMP" && mkdir -p "$TMP"

# list and extract candidate jars from the tarball
echo "Listing potential jars in tarball..."
tar -tzf "$TARBALL" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka' || true

# extract the whole lib folder from tarball into tmp (fast)
tar -xzf "$TARBALL" -C "$TMP" "flink-1.19.3/lib"

# find actual filenames in the extracted lib
EX_LIB="$TMP/flink-1.19.3/lib"
echo "Found these planner/connector jars in the tarball's lib:"
ls -1 "$EX_LIB" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka' || true

# copy the blink planner (preferred) and kafka connector into FLINK lib
# (these lines will copy whichever matching jars are present)
cp -v "$EX_LIB"/flink-table-planner-blink*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/flink-table-planner-loader*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true
cp -v "$EX_LIB"/flink-sql-connector-kafka*1.19.3*.jar "$FLINK_HOME/lib/" 2>/dev/null || true

# Make sure only ONE planner variant remains in lib: prefer blink.
# Remove loader variant if blink exists; otherwise keep loader.
if ls "$FLINK_HOME/lib"/flink-table-planner-blink*1.19.3*.jar >/dev/null 2>&1; then
  echo "Blink planner present — removing any planner-loader jar to avoid duplicates."
  rm -vf "$FLINK_HOME/lib"/flink-table-planner-loader*.jar || true
else
  echo "Blink planner not found — ensure planner-loader is present (we copied if available)."
fi

# show final state
echo "Resulting jars in $FLINK_HOME/lib (planner + kafka connector):"
ls -1 "$FLINK_HOME/lib" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka' || true

# restart Flink
$FLINK_HOME/bin/start-cluster.sh

# short wait then tail client/jobmanager logs for any errors
sleep 2
echo "Tail last 120 lines of the client/standalone logs:"
tail -n 120 "$FLINK_HOME/log/"*standalonesession*.log || true
