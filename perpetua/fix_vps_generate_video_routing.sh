#!/bin/bash
# Fix: MCP-B cron consumer must SKIP generate_video jobs (not mark as failed)
# 
# Problem: /opt/mcp-b/data/mcp_jobs/queue_config.json lacks 'generate_video' in job_types.
# The 5-min cron consumer marks unknown job types as FAILED, killing real muse-main tasks.
# 
# Solution: Add 'generate_video' to job_types with action='skip' (let the dedicated
# muse-main handler process them, not the generic cron consumer).
#
# Run on VPS as: sudo bash fix_vps_generate_video_routing.sh

CONFIG="/opt/mcp-b/data/mcp_jobs/queue_config.json"
BACKUP="${CONFIG}.bak-$(date +%Y%m%d-%H%M%S)"

if [ ! -f "$CONFIG" ]; then
    echo "ERROR: $CONFIG not found"
    exit 1
fi

# Backup
cp "$CONFIG" "$BACKUP"
echo "Backed up to $BACKUP"

# Add generate_video to job_types with skip action
python3 << 'PYEOF'
import json

CONFIG = "/opt/mcp-b/data/mcp_jobs/queue_config.json"

with open(CONFIG) as f:
    data = json.load(f)

if "job_types" not in data:
    data["job_types"] = {}

# Add generate_video with skip action
# The dedicated muse-main backend handles these; cron consumer must not touch them
data["job_types"]["generate_video"] = {
    "action": "skip",
    "reason": "Handled by dedicated muse-main backend, not generic cron consumer. See fix_vps_generate_video_routing.sh (2026-10-15).",
    "skip_silently": True
}

with open(CONFIG, "w") as f:
    json.dump(data, f, indent=2)

print("Added generate_video to job_types with action=skip")
print("Current job_types:", list(data["job_types"].keys()))
PYEOF

echo ""
echo "Fix applied. Verify with:"
echo "  cat $CONFIG | python3 -c 'import json,sys; print(list(json.load(sys.stdin)[\"job_types\"].keys()))'"
