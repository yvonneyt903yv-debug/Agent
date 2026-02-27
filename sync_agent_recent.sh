#!/usr/bin/env bash
set -euo pipefail

REMOTE="root@107.174.255.109"
SRC_OUT="/root/projects/Agent/gps/output"
SRC_IMG="/root/projects/Agent/gps/downloaded_images"
SRC_ART_GPS="/root/projects/Agent/gps/Automated_Articles"
DEST="$HOME/Documents/Agent_sync"
DAYS=1

mkdir -p "$DEST/output" "$DEST/downloaded_images" "$DEST/Automated_Articles/gps"

TMP_OUT="$(mktemp)"
TMP_IMG="$(mktemp)"
TMP_ART_GPS="$(mktemp)"
SSH_SOCKET="$(mktemp -u /tmp/sync_agent_ssh_XXXXXX.sock)"
trap 'rm -f "$TMP_OUT" "$TMP_IMG" "$TMP_ART_GPS"; ssh -S "$SSH_SOCKET" -O exit "$REMOTE" >/dev/null 2>&1 || true' EXIT

SSH_OPTS=(
  -o ControlMaster=auto
  -o ControlPath="$SSH_SOCKET"
  -o ControlPersist=5m
)

remote_find_recent() {
  local src="$1"
  local out="$2"
  if ssh "${SSH_OPTS[@]}" "$REMOTE" "test -d '$src'"; then
    ssh "${SSH_OPTS[@]}" "$REMOTE" "cd '$src' && find . -type f -mtime -$DAYS -print0" > "$out"
    return 0
  fi
  : > "$out"
  return 1
}

sync_from_list() {
  local list_file="$1"
  local src="$2"
  local dest="$3"
  local label="$4"

  if [[ ! -s "$list_file" ]]; then
    echo "==> ${label}: no files in last ${DAYS} day(s), skip."
    return 0
  fi

  rsync -avz -e "ssh ${SSH_OPTS[*]}" --from0 --files-from="$list_file" \
    "$REMOTE:$src/" "$dest/"
}

echo "==> Building file list for OUTPUT (last ${DAYS} day(s)) ..."
if ! remote_find_recent "$SRC_OUT" "$TMP_OUT"; then
  echo "==> OUTPUT source missing on remote, skip: $SRC_OUT"
fi

echo "==> OUTPUT files to sync ..."
sync_from_list "$TMP_OUT" "$SRC_OUT" "$DEST/output/" "OUTPUT"

echo "==> Building file list for downloaded_images (last ${DAYS} day(s)) ..."
if ! remote_find_recent "$SRC_IMG" "$TMP_IMG"; then
  echo "==> IMAGES source missing on remote, skip: $SRC_IMG"
fi

echo "==> IMAGES files to sync ..."
sync_from_list "$TMP_IMG" "$SRC_IMG" "$DEST/downloaded_images/" "IMAGES"

echo "==> Building file list for Automated_Articles (gps, last ${DAYS} day(s)) ..."
if ! remote_find_recent "$SRC_ART_GPS" "$TMP_ART_GPS"; then
  echo "==> GPS Automated_Articles source missing on remote, skip: $SRC_ART_GPS"
fi

echo "==> GPS Automated_Articles files to sync ..."
sync_from_list "$TMP_ART_GPS" "$SRC_ART_GPS" "$DEST/Automated_Articles/gps/" "GPS Automated_Articles"

echo "Done."
