#!/usr/bin/env bash
set -euo pipefail

REMOTE="root@107.174.255.109"
SRC_OUT="/root/projects/Agent/gps/output"
SRC_IMG="/root/projects/Agent/gps/downloaded_images"
SRC_ART_GPS="/root/projects/Agent/gps/Automated_Articles"
SRC_ART_SRC="/root/projects/Agent/src/Automated_Articles"
DEST="$HOME/Documents/Agent_sync"
DAYS=1

mkdir -p "$DEST/output" "$DEST/downloaded_images" "$DEST/Automated_Articles/gps" "$DEST/Automated_Articles/src"

TMP_OUT="$(mktemp)"
TMP_IMG="$(mktemp)"
TMP_ART_GPS="$(mktemp)"
TMP_ART_SRC="$(mktemp)"
trap 'rm -f "$TMP_OUT" "$TMP_IMG" "$TMP_ART_GPS" "$TMP_ART_SRC"' EXIT

echo "==> Building file list for OUTPUT (last ${DAYS} day(s)) ..."
ssh "$REMOTE" "cd '$SRC_OUT' && find . -type f -mtime -$DAYS -print0" > "$TMP_OUT" || true

echo "==> OUTPUT files to sync ..."
rsync -avz --from0 --files-from="$TMP_OUT" \
  "$REMOTE:$SRC_OUT/" "$DEST/output/"

echo "==> Building file list for downloaded_images (last ${DAYS} day(s)) ..."
ssh "$REMOTE" "cd '$SRC_IMG' && find . -type f -mtime -$DAYS -print0" > "$TMP_IMG" || true

echo "==> IMAGES files to sync ..."
rsync -avz --from0 --files-from="$TMP_IMG" \
  "$REMOTE:$SRC_IMG/" "$DEST/downloaded_images/"

echo "==> Building file list for Automated_Articles (gps, last ${DAYS} day(s)) ..."
ssh "$REMOTE" "cd '$SRC_ART_GPS' && find . -type f -mtime -$DAYS -print0" > "$TMP_ART_GPS" || true

echo "==> GPS Automated_Articles files to sync ..."
rsync -avz --from0 --files-from="$TMP_ART_GPS" \
  "$REMOTE:$SRC_ART_GPS/" "$DEST/Automated_Articles/gps/"

echo "==> Building file list for Automated_Articles (src, last ${DAYS} day(s)) ..."
ssh "$REMOTE" "cd '$SRC_ART_SRC' && find . -type f -mtime -$DAYS -print0" > "$TMP_ART_SRC" || true

echo "==> SRC Automated_Articles files to sync ..."
rsync -avz --from0 --files-from="$TMP_ART_SRC" \
  "$REMOTE:$SRC_ART_SRC/" "$DEST/Automated_Articles/src/"

echo "Done."
