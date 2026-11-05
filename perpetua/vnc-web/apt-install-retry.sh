#!/bin/bash
# Retry apt install for x11vnc+websockify until the system apt lock frees up.
# System os-intent reconcile apt runs come and go; do NOT kill them, just retry.
export http_proxy="http://198.19.0.1:3128" https_proxy="http://198.19.0.1:3128"
LOG="/home/hatch/data/perpetua/vnc-web/apt-retry.log"
for i in $(seq 1 240); do
  echo "[$(date '+%H:%M:%S')] attempt $i" >> "$LOG"
  if apt-get install -y x11vnc websockify >> "$LOG" 2>&1; then
    echo "[$(date '+%H:%M:%S')] apt install OK" >> "$LOG"
    break
  fi
  echo "[$(date '+%H:%M:%S')] apt locked/failed, wait 5s" >> "$LOG"
  sleep 5
done
command -v x11vnc >> "$LOG" 2>&1
command -v websockify >> "$LOG" 2>&1
echo "[$(date '+%H:%M:%S')] done" >> "$LOG"
