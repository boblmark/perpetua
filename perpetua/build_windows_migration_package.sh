#!/bin/bash
# Perpetua Windows 迁移包构建脚本（新 VPS 为 Windows Server）
# 产物：~/workspace/your_files/perpetua-windows-migration-YYYYMMDD.tar.gz
# 内容：perpetua 源码递归全量（脱敏，排除清单与 build_vps_migration_package.sh 一致）
#       + windows_compat/ 适配层 + Windows 版迁移工具链 + MIGRATION_WINDOWS.md
# 绝不进包：OAuth token / MCP bearer / API key / 浏览器 profile-cookie / 实时 queue 快照
# 脱敏逻辑与 build_vps_migration_package.sh §2 保持一致（任一修改需同步另一处）
set -e
SRC=/home/hatch/data/perpetua
OUT=/home/hatch/workspace/your_files
DATE=$(date +%Y%m%d)
PKG="perpetua-windows-migration-$DATE.tar.gz"
MANIFEST="$OUT/.windows_migration_manifest.json"
STAGE=$(mktemp -d)
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

echo "[win-mig] 构建日期: $DATE"

# ===== 0. 漂移检测（复用 vps_migration_checksum.py 口径；manifest 独立）=====
CUR_SUM=$(python3 "$SRC/vps_migration_checksum.py")
OLD_SUM=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['sha256'])" 2>/dev/null || echo "none")
if [ "$FORCE" = 0 ] && [ "$CUR_SUM" = "$OLD_SUM" ]; then
  echo "[win-mig] 无漂移，跳过构建"
  rm -rf "$STAGE"
  exit 0
fi
echo "[win-mig] 检测到漂移（旧: ${OLD_SUM:0:8} 新: ${CUR_SUM:0:8}），开始构建"

ROOT="$STAGE/perpetua-windows-migration-$DATE"
mkdir -p "$ROOT/code" "$ROOT/tools" "$ROOT/windows_compat"

# ===== 1. 源码 staging（排除清单与 build_vps_migration_package.sh §1 严格一致）=====
rsync -a \
  --exclude='repo/' --exclude='.git/' \
  --exclude='videos/' --exclude='snapshots/' --exclude='logs/' \
  --exclude='hidden_logs/' --exclude='artifacts/' --exclude='db_backups/' \
  --exclude='deleted_backup/' --exclude='models/' --exclude='jobs/' \
  --exclude='tenants/' --exclude='billing/' --exclude='audit/' \
  --exclude='auth/' --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='distributor/cookies/' --exclude='distributor/vendor/cookies/' \
  --exclude='distributor/matrix_pending/' --exclude='distributor/pending_manual/' \
  --exclude='platform_browser_fallback/' \
  --exclude='ai_unhinged/ep1/' --exclude='ai_unhinged/pilots/' \
  --exclude='ep1_qc/qc_out_20261010/' --exclude='vps_console/img_cache/' \
  --exclude='deploy/perpetua-linux/' \
  --exclude='build/' --exclude='teaser_splice_check/' \
  --exclude='gemini_fallback_review/' --exclude='selftest/.thumbnails/' \
  --exclude='arena_agent/jury_prompts/' --exclude='arena_agent/jury_results/' \
  --exclude='radar/reports/' --exclude='takeover/current/' \
  --exclude='dynamic_constraints.json' --exclude='platform_health.json' \
  --exclude='publish_health_runlog.txt' \
  --exclude='*.log' --exclude='*.tmp' --exclude='*.bak*' --exclude='*~' \
  --exclude='*.mp4' --exclude='*.webm' --exclude='*.mov' --exclude='*.avi' \
  --exclude='.github_push_pending' \
  --exclude='queue.db' --exclude='ops_center.db' --exclude='commander_chat_token' \
  --exclude='vps_traffic.jsonl' --exclude='viralloop_oa_live_cache.json' \
  --exclude='video_quota.json' --exclude='formula_dedup_reject.log.json' \
  --exclude='*_queue.json' --exclude='*_ledger.json' --exclude='*_inbox.json' \
  --exclude='*_state.json' --exclude='*_runs.json' --exclude='*_heartbeat.json' \
  --exclude='review_budget_*.json' --exclude='collect_run_*.json' \
  --exclude='.tmp_*.json' --exclude='prompt_reviewed.json' \
  --exclude='awaiting_approval.json' --exclude='reject_window.json' \
  --exclude='formula_dedup_daily.json' --exclude='qc_orphan_alerted.json' \
  --exclude='private_queue.json' --exclude='anomaly_ledger.json' \
  --exclude='escalation_inbox.json' --exclude='command_queue.json' \
  --exclude='commander_chat_queue.json' --exclude='cron_ops_queue.json' \
  --exclude='executed_commands.json' --exclude='pipeline_runs.json' \
  --exclude='dead_state_alert_dedup.json' --exclude='matrix_history.json' \
  --exclude='platform_matrix.json' --exclude='evolution_reports/' \
  --exclude='deep_dive_*.md' \
  "$SRC/" "$ROOT/code/"
echo "[win-mig] 源码 staging 完成"

# ===== 2. 脱敏（与 build_vps_migration_package.sh §2 同逻辑；只计数，不打印值）=====
REDACT_COUNT=$(python3 - "$ROOT/code" <<'PYEOF'
import os, re, sys
stage = sys.argv[1]
secret_key_re = re.compile(
    r'(?i)\b(api[_-]?key|secret|password|passwd|bearer|private[_-]?key|'
    r'client[_-]?secret|auth[_-]?token|access[_-]?token|refresh[_-]?token)\b')
token_res = [
    re.compile(r'hsurr:[A-Za-z0-9._\-]+'),
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'ghp_[A-Za-z0-9]{20,}'),
    re.compile(r'AIza[A-Za-z0-9_\-]{20,}'),
    re.compile(r'xox[bap]-[A-Za-z0-9\-]{10,}'),
]
kv_re = re.compile(r'^(\s*(?:"|\')?[\w.\-]+(?:"|\')?\s*[:=]\s*)(.+?)(\s*(?:\#.*)?)$')
tokenish_re = re.compile(r'^[A-Za-z0-9_\-+/=]{20,}$')
count = 0
for root, dirs, files in os.walk(stage):
    for fn in files:
        p = os.path.join(root, fn)
        try:
            with open(p, 'rb') as f:
                data = f.read()
        except OSError:
            continue
        if b'\x00' in data[:8192]:
            continue
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            continue
        for r in token_res:
            text, n = r.subn('__REDACTED__', text)
            count += n
        out = []
        for line in text.split('\n'):
            m = kv_re.match(line)
            if m:
                key_part, val, tail = m.group(1), m.group(2).strip(), m.group(3)
                v = val.strip('"\'')
                if (secret_key_re.search(key_part) and v
                        and not v.startswith(('$', '{', '<', '(', '__REDACTED__'))
                        and v.lower() not in ('', 'null', 'none', 'true', 'false')):
                    quoted = val[:1] in '"\''
                    if (quoted and len(v) >= 8) or (not quoted and tokenish_re.match(v)):
                        q = val[:1] if quoted else ''
                        line = m.group(1) + q + '__REDACTED__' + q + tail
                        count += 1
            out.append(line)
        text = '\n'.join(out)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text)
print(count)
PYEOF
)
echo "[win-mig] 脱敏完成：替换 $REDACT_COUNT 处"

# ===== 3. windows_compat 适配层（顶层突出，code/ 内亦有副本）=====
rsync -a --exclude='__pycache__/' --exclude='tasks_xml/' \
  "$SRC/windows_compat/" "$ROOT/windows_compat/"
# 生成 Task Scheduler XML（在构建机上跑 --scan；Windows 路径占位符，目标机按 PERPETUA_HOME 解析）
python3 "$ROOT/windows_compat/sched_win.py" --scan \
  --out "$ROOT/windows_compat/tasks_xml" >/dev/null 2>&1 || \
  echo "[win-mig] 警告：sched_win.py --scan 未成功，tasks_xml 为空"
echo "[win-mig] 适配层已就位"

# ===== 4. Windows 版迁移工具链 =====
cp "$SRC/windows_compat/tools_win/"*.py "$ROOT/tools/"
cp "$SRC/windows_compat/install_windows.bat" "$ROOT/tools/"
cp "$SRC/windows_compat/MIGRATION_WINDOWS.md" "$ROOT/"
cp "$SRC/windows_compat/README_WINDOWS.md" "$ROOT/"
cp "$SRC/WINDOWS_PORT_INVENTORY.md" "$ROOT/"
echo "[win-mig] 工具链已写入"

# ===== 5. SECRETS_MANIFEST.md（Windows 路径版）=====
cat > "$ROOT/SECRETS_MANIFEST.md" <<'DOCEOF'
# 密钥清单（包外独立通道，不进静态包）

本包所有密钥值已替换为 `__REDACTED__`。新 Windows 机器上线前，按下表通过
**旧机器 → 新机器的 SSH/scp 加密直传**（落地后仅管理员可读）或**新机重授权**补齐。

| 密钥名 | 用途 | 获取方式 | 新机落地路径 | 权限 |
|---|---|---|---|---|
| YouTube OAuth token | YouTube Data API | 新机浏览器走授权流程重授权；一人一份，绝不共用 | credential-proxy vault（命名管道服务端） | 管理员+DACL |
| MCP Bearer token | 外部 agent 接入 MCP server | 旧机经 SSH 直传 | `%PROGRAMDATA%\Perpetua\data\mcp_server\.token` | 管理员可读 |
| GitHub 同步 token | 安装包/GitHub 自动推送 | authd 实时获取，新机配置 authd 后自动可用，不落盘 | —（内存） | — |
| DeepSeek API key | 红队大脑备用通道 | 环境变量重设；网页版优先 | 环境变量 | — |
| jev API key | 爆款判决 | 旧机经 SSH 直传或重新申请 | 新机配置 | 管理员可读 |
| Cloudblast API token | VPS 余额/跑道监控 | 用户从 Cloudblast 控制台设置页获取后录入 | 监控配置 | 管理员可读 |
| 浏览器 profile / cookie | 九平台矩阵登录态 | 整目录经 SSH rsync/scp 直传，绝不进包 | 同相对路径 | 管理员可读 |
| SSH 密钥 | 机器互信（隧道） | 新机生成后把公钥加入可信列表；或旧机私钥加密直传 | `%USERPROFILE%\.ssh\` | 管理员可读 |

直传示例（在旧机器执行，目标为新 Windows 机器，OpenSSH scp）：
```powershell
scp C:\old\mcp_server\.token Administrator@NEW_WIN:C:\ProgramData\Perpetua\data\mcp_server\.token
```

铁律：revoke/轮换任何凭据前，先验证 blast radius（还有谁在用、是否共享、有无回滚）。
DOCEOF

# ===== 6. FILELIST.txt =====
(cd "$ROOT" && find code tools windows_compat -type f | sort > FILELIST.txt)
FILE_COUNT=$(wc -l < "$ROOT/FILELIST.txt")
echo "[win-mig] 文件数: $FILE_COUNT"

# ===== 7. 打包 =====
tar --owner=0 --group=0 -czf "$OUT/$PKG" -C "$STAGE" "perpetua-windows-migration-$DATE"
PKG_SIZE=$(du -h "$OUT/$PKG" | cut -f1)
echo "[win-mig] $PKG 完成 ($PKG_SIZE)"

# ===== 8. 写 manifest =====
python3 -c "
import json
manifest = {'built_at': '$DATE', 'sha256': '$CUR_SUM', 'package': '$PKG',
            'size': '$PKG_SIZE', 'file_count': $FILE_COUNT, 'redactions': $REDACT_COUNT,
            'target': 'windows'}
json.dump(manifest, open('$MANIFEST','w'), indent=2)
print('[win-mig] manifest 已更新:', '$CUR_SUM'[:16])
"

rm -rf "$STAGE"
echo "[win-mig] 完成: $OUT/$PKG"
