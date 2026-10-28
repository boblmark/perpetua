#!/bin/bash
# QQ 盒成片清理（空间政策 2026-10-28）：视频上传 YouTube 并核验成功后，
# 凭盒内文件名删除盒内原片。调用前必须已核验 YouTube 侧 video_id 有效；
# 本脚本只删名，不核验上传状态——核验是调用方的责任。
# 用法：
#   qqbox_video_cleanup.sh <box-basename> [event_bus_id]
#   传 event_bus_id 时，删完会清掉条目的 box_filename 字段（本地库操作）。
# 安全：只接受 basename，拒绝空值/斜杠/通配符；删前打印盒内文件大小。
set -u
F=$(basename "${1:-}")
case "$F" in
  "" | *"/"* | *"*"* | *"?"*) echo "refuse: bad filename" >&2; exit 1 ;;
esac
VPS_SCRIPT=$(mktemp /tmp/qqbox_cleanup_XXXXXX.sh)
cat > "$VPS_SCRIPT" <<EOF
#!/bin/bash
TOKEN=\$(cat /root/.instabox_boxqq01_token)
ssh -p 2222 -o BatchMode=yes -o ConnectTimeout=15 \\
  -o StrictHostKeyChecking=accept-new \\
  -o UserKnownHostsFile=/root/.ssh/known_hosts_instabox \\
  "\${TOKEN}@ssh.instabox.sh" \\
  'f="/data/home/muse/generated-videos/$F"; ls -l "\$f" && rm -f "\$f" && echo DELETED || echo NOT_FOUND'
EOF
scp -q -o BatchMode=yes -o ConnectTimeout=20 -o ProxyCommand='nc -X connect -x 198.19.0.1:3128 %h %p' -i /home/hatch/.ssh/id_ed25519 "$VPS_SCRIPT" root@192.166.82.123:/tmp/qqbox_cleanup_run.sh
/home/hatch/workspace/mcp-b-ssh.sh "bash /tmp/qqbox_cleanup_run.sh"
RC=$?
rm -f "$VPS_SCRIPT"
if [ $RC -eq 0 ] && [ -n "${2:-}" ]; then
  python3 -c "
import json, sqlite3, sys
db = sqlite3.connect('/home/hatch/data/ops_center.db')
row = db.execute('SELECT payload FROM event_bus WHERE id=?', (int(sys.argv[1]),)).fetchone()
if row:
    p = json.loads(row[0])
    p.pop('box_filename', None)
    p.pop('box_path', None)
    db.execute('UPDATE event_bus SET payload=? WHERE id=?', (json.dumps(p, ensure_ascii=False), int(sys.argv[1])))
    db.commit()
    print('cleared box fields for item', sys.argv[1])
" "$2"
fi
exit $RC
