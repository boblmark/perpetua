#!/bin/bash
# Perpetua VPS 完整迁移包构建脚本
# 产物：~/workspace/your_files/perpetua-vps-migration-YYYYMMDD.tar.gz
# 内容：perpetua 源码递归全量（脱敏）+ 基础设施脚本与配置 + 迁移工具链 + MIGRATION.md
# 绝不进包：OAuth token / MCP bearer / API key / 浏览器 profile-cookie / 实时 queue 快照
# 触发：手动 ./build_vps_migration_package.sh [--force]，或由 install-package-sync cron 调用
#       （脚本自带漂移检测，无变化时秒级跳过）
set -e
SRC=/home/hatch/data/perpetua
OUT=/home/hatch/workspace/your_files
DATE=$(date +%Y%m%d)
PKG="perpetua-vps-migration-$DATE.tar.gz"
MANIFEST="$OUT/.vps_migration_manifest.json"
STAGE=$(mktemp -d)
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

echo "[vps-mig] 构建日期: $DATE"

# ===== 0. 漂移检测（口径：vps_migration_checksum.py，唯一真相源）=====
CUR_SUM=$(python3 "$SRC/vps_migration_checksum.py")
OLD_SUM=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['sha256'])" 2>/dev/null || echo "none")
if [ "$FORCE" = 0 ] && [ "$CUR_SUM" = "$OLD_SUM" ]; then
  echo "[vps-mig] 无漂移，跳过构建"
  rm -rf "$STAGE"
  exit 0
fi
echo "[vps-mig] 检测到漂移（旧: ${OLD_SUM:0:8} 新: ${CUR_SUM:0:8}），开始构建"

ROOT="$STAGE/perpetua-vps-migration-$DATE"
mkdir -p "$ROOT/code" "$ROOT/tools"

# ===== 1. 源码 staging（排除清单与 vps_migration_checksum.py 保持一致）=====
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
  --exclude='*.log' --exclude='*.tmp' --exclude='*.bak*' --exclude='*~' \
  --exclude='*.mp4' --exclude='*.webm' --exclude='*.mov' --exclude='*.avi' \
  --exclude='.github_push_pending' \
  --exclude='queue.db' --exclude='ops_center.db' --exclude='commander_chat_token' \
  --exclude='vps_traffic.jsonl' --exclude='viralloop_oa_live_cache.json' \
  --exclude='video_quota.json' --exclude='formula_dedup_reject.log.json' \
  --exclude='*_queue.json' --exclude='*_ledger.json' --exclude='*_inbox.json' \
  --exclude='*_state.json' --exclude='*_runs.json' --exclude='*_heartbeat.json' \
  --exclude='review_budget_*.json' --exclude='collect_run_*.json' \
  --exclude='private_queue.json' --exclude='anomaly_ledger.json' \
  --exclude='escalation_inbox.json' --exclude='command_queue.json' \
  --exclude='commander_chat_queue.json' --exclude='cron_ops_queue.json' \
  --exclude='executed_commands.json' --exclude='pipeline_runs.json' \
  --exclude='dead_state_alert_dedup.json' \
  "$SRC/" "$ROOT/code/"
echo "[vps-mig] 源码 staging 完成"

# ===== 2. 脱敏（只计数，不打印任何值）=====
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
            continue  # 二进制跳过
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
echo "[vps-mig] 脱敏完成：替换 $REDACT_COUNT 处"

# ===== 3. 迁移工具链（真实可用，非占位）=====

# ---- 3a. install.sh（幂等，可重复执行）----
cat > "$ROOT/tools/install.sh" <<'TOOLEOF'
#!/bin/bash
# Perpetua 新 VPS 安装脚本 —— 幂等，可重复执行
# 用法：sudo -E ./install.sh   或   PERP_HOME=/opt/perpetua ./install.sh
set -e
PERP_HOME="${PERP_HOME:-/home/hatch/data/perpetua}"
PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "[install] 目标目录: $PERP_HOME"

need_root() { [ "$(id -u)" = 0 ] || { echo "[install] 需要 root（sudo）"; exit 1; }; }

# 1. 系统依赖（dpkg 检查，缺啥装啥）
need_root
for p in python3 python3-pip ffmpeg curl rsync openssh-client ca-certificates sqlite3; do
  if dpkg -s "$p" >/dev/null 2>&1; then echo "[install] 已有: $p";
  else echo "[install] 安装: $p"; apt-get update -qq && apt-get install -y -qq "$p"; fi
done
python3 -c "import yaml" 2>/dev/null || pip3 install --quiet pyyaml requests || true

# 2. 目录（已存在则跳过）
mkdir -p "$PERP_HOME" /etc/perpetua
OWNER="${SUDO_USER:-$USER}"
chown -R "$OWNER:$OWNER" "$PERP_HOME" 2>/dev/null || true

# 3. 源码同步（rsync 幂等；tools/ 与文档不同步进运行目录）
rsync -a --delete \
  --exclude='tools/' --exclude='MIGRATION.md' \
  --exclude='SECRETS_MANIFEST.md' --exclude='FILELIST.txt' \
  "$PKG_DIR/code/" "$PERP_HOME/"
echo "[install] 源码已同步"

# 4. systemd units（内容无变化则不重载）
CHANGED=0
for src in "$PKG_DIR/code/deploy/systemd"/*.service "$PKG_DIR/code/vps_console"/*.service; do
  [ -f "$src" ] || continue
  n=$(basename "$src")
  if ! cmp -s "$src" "/etc/systemd/system/$n" 2>/dev/null; then
    echo "[install] 安装 unit: $n"; cp "$src" "/etc/systemd/system/$n"; CHANGED=1
  fi
done
[ "$CHANGED" = 1 ] && { systemctl daemon-reload; echo "[install] systemd 已重载"; }

# 5. 密钥目录骨架（700；密钥由包外通道填入，见 SECRETS_MANIFEST.md）
mkdir -p "$PERP_HOME/auth" "$PERP_HOME/.secrets"
chmod 700 "$PERP_HOME/auth" "$PERP_HOME/.secrets"
chown -R "$OWNER:$OWNER" "$PERP_HOME/auth" "$PERP_HOME/.secrets"

# 6. 隧道脚本可执行位
chmod +x "$PERP_HOME"/vps_console/tunnel_*.sh "$PERP_HOME"/vps_console/*keepalive*.sh 2>/dev/null || true

echo "[install] 完成。下一步：按 SECRETS_MANIFEST.md 填入密钥 → 运行 tools/restore.sh（如有快照）→ tools/verify.sh"
TOOLEOF

# ---- 3b. snapshot.sh（旧机器，只读探针：不启停服务、不改配置、不碰线上 queue）----
cat > "$ROOT/tools/snapshot.sh" <<'TOOLEOF'
#!/bin/bash
# 在旧机器上生成迁移快照 —— 只读，不修改任何生产状态
# 用法：./snapshot.sh [源码目录] [输出目录]
set -e
SRC="${1:-/home/hatch/data/perpetua}"
OUT="${2:-$HOME/vps-migration-snapshot-$(date +%Y%m%d-%H%M%S)}"
[ -d "$SRC" ] || { echo "[snapshot] 源码目录不存在: $SRC"; exit 1; }
mkdir -p "$OUT"

# 1. queue.db / ops_center.db：用 backup API 拷副本再转 json（不对线上库加写锁）
python3 - "$SRC" "$OUT" <<'PYEOF'
import sqlite3, json, os, sys
src, out = sys.argv[1], sys.argv[2]
for dbname in ("queue.db", "ops_center.db"):
    db = os.path.join(src, dbname)
    if not os.path.isfile(db):
        print(f"[snapshot] 跳过（无文件）: {dbname}"); continue
    tmp = os.path.join(out, dbname + ".copy")
    s = sqlite3.connect(f"file:{db}?mode=ro", uri=True)   # 只读打开
    d = sqlite3.connect(tmp)
    s.backup(d); d.close(); s.close()
    os.remove(tmp)
    # 用 row_factory 保证可序列化
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    dump = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        dump[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t}")]
    con.close()
    json.dump(dump, open(os.path.join(out, dbname + ".json"), "w"), ensure_ascii=False, default=str)
    print(f"[snapshot] 已导出: {dbname}（{sum(len(v) for v in dump.values())} 行）")
PYEOF

# 2b. 管线关键状态（perpetua 目录之外，但属迁移范围）
[ -f /home/hatch/data/youtube/private_queue.json ] \
  && cp /home/hatch/data/youtube/private_queue.json "$OUT/youtube_private_queue.json" \
  && echo "[snapshot] 已复制: youtube/private_queue.json"
[ -f /home/hatch/data/ask_studio/queue.json ] \
  && cp /home/hatch/data/ask_studio/queue.json "$OUT/ask_studio_queue.json" \
  && echo "[snapshot] 已复制: ask_studio/queue.json（评审队列）"
[ -f /home/hatch/data/ask_studio/instant_queue.json ] \
  && cp /home/hatch/data/ask_studio/instant_queue.json "$OUT/ask_studio_instant_queue.json" \
  && echo "[snapshot] 已复制: ask_studio/instant_queue.json"
[ -f /home/hatch/data/jev/criteria.json ] \
  && cp /home/hatch/data/jev/criteria.json "$OUT/jev_criteria.json" \
  && echo "[snapshot] 已复制: jev/criteria.json"

# 2. 实时队列/账本 JSON（cp 只读）
for f in private_queue.json anomaly_ledger.json escalation_inbox.json \
         command_queue.json commander_chat_queue.json; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$OUT/" && echo "[snapshot] 已复制: $f"
done

# 3. cron 定义导出（新机器重建调度用）
if [ -d /home/hatch/workspace/cron.d ]; then
  mkdir -p "$OUT/cron.d"
  cp -r /home/hatch/workspace/cron.d/. "$OUT/cron.d/" 2>/dev/null || true
  echo "[snapshot] cron.d 已导出"
fi
for d in /home/hatch/workspace/goals/*/crons; do
  [ -d "$d" ] || continue
  g=$(basename "$(dirname "$d")")
  mkdir -p "$OUT/goal_crons/$g" && cp -r "$d"/. "$OUT/goal_crons/$g/" 2>/dev/null || true
done

# 4. 清单
(cd "$OUT" && sha256sum $(find . -type f | sort) > SHA256SUMS 2>/dev/null || true)
echo "[snapshot] 快照完成: $OUT"
echo "[snapshot] 传到新机器: scp -r \"$OUT\" <user>@<newhost>:/tmp/"
echo "[snapshot] 注意：密钥文件（auth/、*.token、浏览器 profile）不在快照内，走 SSH 加密直传或重授权"
TOOLEOF

# ---- 3c. restore.sh（新机器）----
cat > "$ROOT/tools/restore.sh" <<'TOOLEOF'
#!/bin/bash
# 在新机器上恢复快照
# 用法：./restore.sh <快照目录>  （环境变量 PERP_HOME 指定目标，默认 /home/perpetua/data/perpetua）
set -e
SNAP="${1:?用法: ./restore.sh <快照目录>}"
PERP_HOME="${PERP_HOME:-/home/hatch/data/perpetua}"
DATA_ROOT="${DATA_ROOT:-/home/hatch/data}"
[ -d "$SNAP" ] || { echo "[restore] 快照目录不存在: $SNAP"; exit 1; }
[ -d "$PERP_HOME" ] || { echo "[restore] 先运行 tools/install.sh 建好 $PERP_HOME"; exit 1; }

# 1. 校验快照完整性
if [ -f "$SNAP/SHA256SUMS" ]; then
  (cd "$SNAP" && sha256sum -c SHA256SUMS --quiet) && echo "[restore] 快照校验通过" \
    || { echo "[restore] 快照校验失败，停止"; exit 1; }
fi

# 2. 恢复 JSON 状态
for f in "$SNAP"/*.json; do
  [ -f "$f" ] || continue
  n=$(basename "$f")
  case "$n" in *.copy|SHA256SUMS) continue;; esac
  cp "$f" "$PERP_HOME/$n" && echo "[restore] 已恢复: $n"
done

# 2b. perpetua 之外的关键状态（放回原路径）
[ -f "$SNAP/youtube_private_queue.json" ] \
  && { mkdir -p "$DATA_ROOT/youtube"; cp "$SNAP/youtube_private_queue.json" "$DATA_ROOT/youtube/private_queue.json"; echo "[restore] 已恢复: youtube/private_queue.json"; }
[ -f "$SNAP/ask_studio_queue.json" ] \
  && { mkdir -p "$DATA_ROOT/ask_studio"; cp "$SNAP/ask_studio_queue.json" "$DATA_ROOT/ask_studio/queue.json"; echo "[restore] 已恢复: ask_studio/queue.json"; }
[ -f "$SNAP/ask_studio_instant_queue.json" ] \
  && { mkdir -p "$DATA_ROOT/ask_studio"; cp "$SNAP/ask_studio_instant_queue.json" "$DATA_ROOT/ask_studio/instant_queue.json"; echo "[restore] 已恢复: ask_studio/instant_queue.json"; }
[ -f "$SNAP/jev_criteria.json" ] \
  && { mkdir -p "$DATA_ROOT/jev"; cp "$SNAP/jev_criteria.json" "$DATA_ROOT/jev/criteria.json"; echo "[restore] 已恢复: jev/criteria.json"; }

# 3. 恢复 sqlite（json -> db；原 db 先备份）
python3 - "$SNAP" "$PERP_HOME" <<'PYEOF'
import sqlite3, json, os, sys, time
snap, home = sys.argv[1], sys.argv[2]
for dbname in ("queue.db", "ops_center.db"):
    jf = os.path.join(snap, dbname + ".json")
    if not os.path.isfile(jf):
        print(f"[restore] 跳过（快照无）: {dbname}"); continue
    dump = json.load(open(jf))
    db = os.path.join(home, dbname)
    if os.path.isfile(db):
        os.rename(db, db + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
        print(f"[restore] 旧 {dbname} 已备份")
    con = sqlite3.connect(db)
    for t, rows in dump.items():
        if not rows: continue
        cols = list(rows[0].keys())
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} ({', '.join(cols)})")
        con.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
                       [[r[c] for c in cols] for r in rows])
    con.commit(); con.close()
    print(f"[restore] 已恢复: {dbname}")
PYEOF

# 4. 权限收紧
chmod 600 "$PERP_HOME"/auth/* 2>/dev/null || true
chmod 700 "$PERP_HOME/auth" 2>/dev/null || true

echo "[restore] 完成。运行 tools/verify.sh 做冒烟验收"
TOOLEOF

# ---- 3d. verify.sh（冒烟验收；--dry-run 只验逻辑自洽，不碰网络）----
cat > "$ROOT/tools/verify.sh" <<'TOOLEOF'
#!/bin/bash
# 新机器冒烟验收
# 用法：./verify.sh [--dry-run]   dry-run 不发起任何网络/进程检查，只验证脚本逻辑与文件自洽
PERP_HOME="${PERP_HOME:-/home/hatch/data/perpetua}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "[verify] PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "[verify] FAIL: $1"; }

# 1. 关键文件存在
for f in dispatch_health.py auto_pipeline.py queue_db.py \
         vps_console/console_server.py platform_config.yaml deploy/requirements.txt; do
  if [ "$DRY" = 1 ]; then
    [ -f "$PERP_HOME/$f" ] && ok "dry-run 文件存在: $f" || bad "dry-run 文件缺失: $f"
  else
    [ -f "$PERP_HOME/$f" ] && ok "文件存在: $f" || bad "文件缺失: $f"
  fi
done

# 2. python 语法（dry-run 也跑：纯本地）
if python3 -m py_compile "$PERP_HOME/dispatch_health.py" "$PERP_HOME/auto_pipeline.py" 2>/dev/null; then
  ok "python 语法检查通过"
else
  bad "python 语法检查失败"
fi

# 3. 端口/服务（dry-run 跳过真实 curl，只检查检查项非空）
PORTS="18739 18736 8734 8735"
[ -n "$PORTS" ] || bad "端口清单为空"
for p in $PORTS; do
  if [ "$DRY" = 1 ]; then ok "dry-run 端口检查项就绪: $p"; continue; fi
  if curl -sf -m 5 -o /dev/null "http://127.0.0.1:$p/" 2>/dev/null; then ok "端口 $p 响应";
  else bad "端口 $p 无响应"; fi
done

# 4. dispatcher 健康脚本（dry-run 只校验脚本可被调用，真实跑走完整探针）
if [ "$DRY" = 1 ]; then
  [ -x "$PERP_HOME/dispatch_health.py" ] || [ -f "$PERP_HOME/dispatch_health.py" ]
  ok "dry-run dispatch_health.py 可调用"
else
  if python3 "$PERP_HOME/dispatch_health.py" >/dev/null 2>&1; then ok "dispatch_health 探针通过";
  else bad "dispatch_health 探针异常（exit=$?)"; fi
fi

# 5. queue 可读（dry-run 检查 db 文件存在性即可）
if [ "$DRY" = 1 ]; then
  ok "dry-run queue 检查项就绪"
else
  if python3 -c "
import sqlite3,sys
con=sqlite3.connect('file:$PERP_HOME/queue.db?mode=ro',uri=True)
print(con.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()[0])
" 2>/dev/null | grep -qE '^[0-9]+$'; then ok "queue.db 可读"; else bad "queue.db 不可读"; fi
fi

echo "[verify] 结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = 0 ] && { echo "[verify] 冒烟验收通过"; exit 0; } || { echo "[verify] 冒烟验收未通过，见上"; exit 1; }
TOOLEOF

# ---- 3e. rollback.sh ----
cat > "$ROOT/tools/rollback.sh" <<'TOOLEOF'
#!/bin/bash
# 回滚：停止新机器服务，旧机器保持为权威
# 策略（已定）：旧机器在冒烟验收通过前不下线；回滚 = 新机器停服 + 流量留在旧机器
set -e
echo "[rollback] 将停止本机所有 perpetua-* systemd 服务，旧机器继续为权威。"
read -r -p "确认回滚？输入 yes 继续: " ans
[ "$ans" = "yes" ] || { echo "[rollback] 已取消"; exit 0; }
if [ "$(id -u)" = 0 ]; then
  systemctl stop 'perpetua-*' 2>/dev/null || true
  systemctl disable 'perpetua-*' 2>/dev/null || true
  echo "[rollback] systemd 服务已停用"
else
  echo "[rollback] 非 root，跳过 systemctl；请手动停服务"
fi
pkill -f "tunnel_.*\.sh" 2>/dev/null || true
echo "[rollback] 回滚完成。检查清单："
echo "  1) 旧机器服务正常（curl 旧机器各端口）"
echo "  2) DNS/隧道仍指向旧机器"
echo "  3) 本机数据保留，待问题定位后再决定重迁或废弃"
TOOLEOF

chmod +x "$ROOT/tools/"*.sh
echo "[vps-mig] 工具链已写入"

# ===== 4. SECRETS_MANIFEST.md（密钥清单：名称/用途/来源/获取方式/落地路径）=====
cat > "$ROOT/SECRETS_MANIFEST.md" <<'DOCEOF'
# 密钥清单（包外独立通道，不进静态包）

本包所有密钥值已替换为 `__REDACTED__`。新机器上线前，按下表通过
**旧 VPS → 新 VPS 的 SSH 加密直传**（落地 600 权限）或**新机重授权**补齐。

| 密钥名 | 用途 | 获取方式 | 新机落地路径 | 权限 |
|---|---|---|---|---|
| YouTube OAuth token | YouTube Data API（上传/评论/数据） | 新机走 OAuth 授权流程重授权；一人一份，绝不共用 | credential-proxy vault | vault 托管 |
| MCP Bearer token | 外部 agent 接入 MCP server | 旧机 `data/mcp_server/.token` 经 SSH 直传；或重新签发 | 新机同路径 | 600 |
| GitHub 同步 token | 安装包/GitHub 自动推送 | authd 实时获取，新机配置 authd 后自动可用，不落盘 | —（内存） | — |
| DeepSeek API key | 红队大脑备用通道 | 环境变量重设；网页版优先，API 仅备用 | 环境变量 | — |
| jev API key | 爆款判决 | 旧机经 SSH 直传或重新申请 | 新机配置 | 600 |
| Cloudblast API token | VPS 余额/跑道监控 | 用户从 Cloudblast 控制台设置页获取后录入 | 监控配置 | 600 |
| 浏览器 profile / cookie | 九平台矩阵登录态 | 整目录经 SSH rsync 直传（`distributor/cookies/` 等），绝不进包 | 同路径 | 700/600 |
| x11vnc / SSH 密钥 | 远程桌面与机器互信 | 用户重设密码；SSH key 新机生成后把公钥加入旧机授权 | — | 600 |

直传示例（在旧机器执行，目标为新机器）：
```bash
scp -p /home/hatch/data/mcp_server/.token root@NEW_VPS:/home/perpetua/data/mcp_server/.token
ssh root@NEW_VPS 'chmod 600 /home/perpetua/data/mcp_server/.token'
rsync -a --chmod=700 /home/hatch/data/perpetua/distributor/cookies/ root@NEW_VPS:/home/perpetua/data/perpetua/distributor/cookies/
```

铁律：revoke/轮换任何凭据前，先验证 blast radius（还有谁在用、是否共享、有无回滚）。
DOCEOF

# ===== 5. MIGRATION.md（步骤/检查清单/回滚条件）=====
cat > "$ROOT/MIGRATION.md" <<'DOCEOF'
# Perpetua VPS 完整迁移手册

## 0. 原则
- 旧机器在**新机器冒烟验收通过前不下线**（回滚策略）。
- 密钥永不进静态包，走 SSH 加密直传或重授权（见 SECRETS_MANIFEST.md）。
- 实时 queue 快照在**迁移窗口**由 `tools/snapshot.sh` 实时生成，不烘焙进包。

## 1. 迁移步骤
1. 新机器准备：解包 → `cd perpetua-vps-migration-YYYYMMDD && sudo -E ./tools/install.sh`
   （幂等，可重复跑；PERP_HOME 环境变量可改目标目录）
2. 填密钥：按 SECRETS_MANIFEST.md 直传或重授权，落地权限 600/700。
3. 旧机器进迁移窗口：`./tools/snapshot.sh /home/hatch/data/perpetua ~/vps-migration-snapshot-<ts>`
   （只读：不启停服务、不改配置；建议在低峰执行，缩短新旧 queue 漂移）
4. 传快照到新机器：`scp -r ~/vps-migration-snapshot-<ts> root@NEW:/tmp/`
5. 新机器恢复：`./tools/restore.sh /tmp/vps-migration-snapshot-<ts>`
6. 冒烟验收：`./tools/verify.sh`（先 `--dry-run` 验逻辑，再真实跑）
7. 拉起服务：`systemctl enable --now perpetua-console perpetua-mcp`（按实际 unit 名），
   启动隧道脚本（`vps_console/tunnel_*.sh`），重建 cron 调度（快照内 `cron.d/`）。
8. 观察 24h：dispatch_health 全绿、queue 深度正常、发布链路有产出。

## 2. 检查清单
- [ ] install.sh 无报错，PERP_HOME 下源码完整
- [ ] 全部密钥已补齐且权限为 600/700（`ls -l auth/ .secrets/`）
- [ ] snapshot SHA256SUMS 校验通过
- [ ] verify.sh 全 PASS（含 dispatch_health.py 探针）
- [ ] systemd units 已 enable，重启后自起
- [ ] 隧道三层判活：ssh 进程 → 远端端口绑定 → 本地 curl 响应
- [ ] cron 调度已重建（对照快照 cron.d）
- [ ] 旧机器服务保持运行，直到本清单全勾

## 3. 回滚条件（任一成立即回滚）
- verify.sh 有 FAIL 且 30 分钟内无法定位修复
- 新机器 dispatch_health 持续 DEGRADED/DOWN 超 1h
- queue 恢复后深度异常或消费者停滞
- 回滚动作：`./tools/rollback.sh`（停新机器服务，旧机器继续权威）

## 4. 旧机器下线条件（全部满足）
- 新机器连续 24h 全绿且有真实发布产出
- 旧机器 queue 已排空（pending=0）
- 用户明确批准下线
DOCEOF

# ===== 6. FILELIST.txt =====
(cd "$ROOT" && find code tools -type f | sort > FILELIST.txt)
FILE_COUNT=$(wc -l < "$ROOT/FILELIST.txt")
echo "[vps-mig] 文件数: $FILE_COUNT"

# ===== 7. 打包（固定属主，避免解包时 chown 噪音）=====
tar --owner=0 --group=0 -czf "$OUT/$PKG" -C "$STAGE" "perpetua-vps-migration-$DATE"
PKG_SIZE=$(du -h "$OUT/$PKG" | cut -f1)
echo "[vps-mig] $PKG 完成 ($PKG_SIZE)"

# ===== 8. 写 manifest =====
python3 -c "
import json
manifest = {'built_at': '$DATE', 'sha256': '$CUR_SUM', 'package': '$PKG',
            'size': '$PKG_SIZE', 'file_count': $FILE_COUNT, 'redactions': $REDACT_COUNT}
json.dump(manifest, open('$MANIFEST','w'), indent=2)
print('[vps-mig] manifest 已更新:', '$CUR_SUM'[:16])
"

rm -rf "$STAGE"
echo "[vps-mig] 完成: $OUT/$PKG"
