#!/usr/bin/env bash
set -euo pipefail

# Adjust these if your FLINK_HOME or tarball location differ
FLINK_HOME="${FLINK_HOME:-$HOME/flink-1.19.3}"
TARBALL="${TARBALL:-flink-1.19.3-bin-scala_2.12.tgz}"
TMPDIR="/tmp/flink_extract_$$"

echo "FLINK_HOME = $FLINK_HOME"
echo "TARBALL   = $TARBALL"

if [ ! -f "$TARBALL" ]; then
  echo "ERROR: tarball $TARBALL not found in current dir. Set TARBALL env var or run from the tarball directory."
  exit 1
fi
if [ ! -d "$FLINK_HOME" ]; then
  echo "ERROR: FLINK_HOME $FLINK_HOME not found. Export FLINK_HOME or adjust variable at top of script."
  exit 1
fi

# clean tmp
rm -rf "$TMPDIR"
mkdir -p "$TMPDIR"

echo "Extracting tarball (this may take a moment)..."
tar -xzf "$TARBALL" -C "$TMPDIR"

# find extracted root (handle either flink-1.19.3 or similar)
EXTRACTED_ROOT=$(find "$TMPDIR" -maxdepth 2 -type d -name "flink-1.19.3" -print -quit)
if [ -z "$EXTRACTED_ROOT" ]; then
  echo "Couldn't locate extracted flink directory under $TMPDIR"
  ls -l "$TMPDIR"
  exit 1
fi
SRC_LIB="$EXTRACTED_ROOT/lib"
echo "Found extracted lib at: $SRC_LIB"

# Identify relevant jars in extracted lib
echo "Searching for planner and kafka connector jars in extracted lib..."
PLANNER_BLINK=$(ls "$SRC_LIB" 2>/dev/null | egrep '^flink-table-planner-blink.*1.19.3.*\.jar$' || true)
PLANNER_LOADER=$(ls "$SRC_LIB" 2>/dev/null | egrep '^flink-table-planner-loader.*1.19.3.*\.jar$' || true)
CONNECTOR_KAFKA=$(ls "$SRC_LIB" 2>/dev/null | egrep '^flink-sql-connector-kafka(_2.12)?-1.19.3.*\.jar$' || true)

echo "Found (in extracted):"
echo "  PLANNER_BLINK: $PLANNER_BLINK"
echo "  PLANNER_LOADER: $PLANNER_LOADER"
echo "  CONNECTOR_KAFKA: $CONNECTOR_KAFKA"

# Prepare destination lib dir
DEST_LIB="$FLINK_HOME/lib"
mkdir -p "$DEST_LIB"

# Copy kafka connector if missing or different
if [ -n "$CONNECTOR_KAFKA" ]; then
  echo "Copying kafka connector jar..."
  cp -v "$SRC_LIB/$CONNECTOR_KAFKA" "$DEST_LIB/"
else
  echo "WARNING: kafka connector jar not found in tarball extracted lib. Skipping copy."
fi

# Planner handling: prefer blink planner. Ensure only one planner remains.
if [ -n "$PLANNER_BLINK" ]; then
  echo "Copying BLINK planner jar..."
  cp -v "$SRC_LIB/$PLANNER_BLINK" "$DEST_LIB/"
  # remove any planner-loader in dest (to avoid multiple planners)
  echo "Removing any planner-loader jars from $DEST_LIB (if present)..."
  rm -vf "$DEST_LIB"/flink-table-planner-loader*.jar || true
elif [ -n "$PLANNER_LOADER" ]; then
  echo "BLINK planner not found. Copying planner-loader jar..."
  cp -v "$SRC_LIB/$PLANNER_LOADER" "$DEST_LIB/"
  # remove blink variant in dest if present (shouldn't happen)
  rm -vf "$DEST_LIB"/flink-table-planner-blink*.jar || true
else
  echo "WARNING: No planner jars found in the extracted lib. You may need to download matching planner jar manually."
fi

echo "Listing relevant jars now in $DEST_LIB:"
ls -1 "$DEST_LIB" | egrep 'table-planner|planner-loader|connector-kafka|flink-sql-connector-kafka' || true

# Restart flink (stop then start)
echo "Stopping Flink cluster..."
"$FLINK_HOME/bin/stop-cluster.sh" || true
sleep 2
echo "Starting Flink cluster..."
"$FLINK_HOME/bin/start-cluster.sh"

echo "Waiting 3s for services to settle..."
sleep 3

echo "Flink web UI check (first 3 lines):"
curl -sS http://localhost:8081 | sed -n '1,3p' || echo "curl failed (web UI might be unreachable)"

echo "Done. If you still get connector errors, check the jobmanager logs:"
echo "  tail -n 200 $FLINK_HOME/log/*jobmanager*.log"

# cleanup extracted files
rm -rf "$TMPDIR"
echo "Temporary files removed: $TMPDIR"
