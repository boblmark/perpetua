#!/bin/bash
# Cron 调度定义导出脚本（供新机器重建用）
# 用法：bash /home/hatch/data/perpetua/export_crons.sh
# 产出：/home/hatch/workspace/goals/full-perpetua-system-migration-to-new-vps/files/cron_export_YYYYMMDD/
#       + 同名 .tar.gz（install-package-sync 的构建脚本会自动把它打进 full 安装包）
set -e
DATE=$(date +%Y%m%d)
FILES_DIR=/home/hatch/workspace/goals/full-perpetua-system-migration-to-new-vps/files
EXPORT="$FILES_DIR/cron_export_$DATE"
NOW_CST=$(TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M CST')

rm -rf "$EXPORT"
mkdir -p "$EXPORT/cron.d" "$EXPORT/goals"

# 通用 cron
cp -r /home/hatch/workspace/cron.d/. "$EXPORT/cron.d/"

# 目标归属 cron（按 goal 分组）
for g in /home/hatch/workspace/goals/*/; do
  slug=$(basename "$g")
  if [ -d "$g/crons" ] && [ -n "$(find "$g/crons" -name '*.md' -print -quit)" ]; then
    mkdir -p "$EXPORT/goals/$slug"
    cp -r "$g/crons" "$EXPORT/goals/$slug/crons"
  fi
done

# 生成 manifest（程序化解析 frontmatter，不手拼）
python3 - "$EXPORT" "$NOW_CST" <<'EOF'
import os, re, sys
export_dir, now_cst = sys.argv[1], sys.argv[2]

def parse_fm(path):
    fm = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        if not lines or lines[0].strip() != '---':
            return fm
        for ln in lines[1:]:
            if ln.strip() == '---':
                break
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', ln)
            if m:
                fm[m.group(1)] = m.group(2).strip()
    except Exception:
        pass
    return fm

rows = []
for root, _dirs, files in os.walk(export_dir):
    for fn in sorted(files):
        if not fn.endswith('.md'):
            continue
        p = os.path.join(root, fn)
        fm = parse_fm(p)
        sched = fn.rsplit('__', 1)[-1][:-3] if '__' in fn else '?'
        cid = fm.get('id', fn[:-3])
        # _archive/_invalid 下的文件不是在途调度，按目录名如实标注
        if '/_archive/' in p:
            state = 'ARCHIVED'
        elif '/_invalid/' in p:
            state = 'INVALID'
        else:
            state = 'ON' if fm.get('enabled', 'true').lower() == 'true' else 'OFF'
        title = fm.get('title', '') or ''
        if title in ('null', 'None', ''):
            title = cid
        owner = fm.get('owner', '') or ''
        if owner in ('null', 'None', ''):
            owner = '(无)'
        rows.append((cid, state, sched, title, owner))

rows.sort(key=lambda r: r[0].lower())
off = sum(1 for r in rows if r[1] == 'OFF')
archived = sum(1 for r in rows if r[1] in ('ARCHIVED', 'INVALID'))
live = [r for r in rows if r[1] in ('ON', 'OFF')]
with open(os.path.join(export_dir, 'manifest.txt'), 'w', encoding='utf-8') as f:
    f.write(f"# Muse 平台 Cron 完整清单（{now_cst} 导出）\n")
    f.write("# 格式：ID | 状态 | 调度 | 标题 | 归属\n")
    f.write(f"# 共 {len(rows)} 个文件：在途 {len(live)}（启用 {len(live)-off} / 禁用 {off}，迁移时保持禁用）"
            f"；归档/失效 {archived}（迁移时跳过）\n\n")
    for r in rows:
        f.write(" | ".join(r) + "\n")

cron_d_n = sum(1 for _r, _d, fs in os.walk(os.path.join(export_dir, 'cron.d'))
               for _f in fs if _f.endswith('.md'))
goal_n = sum(1 for _r, _d, fs in os.walk(os.path.join(export_dir, 'goals'))
             for _f in fs if _f.endswith('.md'))
with open(os.path.join(export_dir, 'README.md'), 'w', encoding='utf-8') as f:
    f.write(f"# Cron 调度导出包（{now_cst}）\n\n")
    f.write("> 从 Muse 平台侧导出的全部调度任务定义，用于新机器重建\n\n")
    f.write("## 内容\n\n")
    f.write(f"- `cron.d/` — {cron_d_n} 个通用 cron 定义\n")
    f.write(f"- `goals/` — {goal_n} 个目标归属 cron 定义（按 goal 分组）\n")
    f.write(f"- `manifest.txt` — 平台侧 {len(rows)} 个任务的完整清单（含 ID/调度/标题/归属/启用状态）\n\n")
    f.write("## 说明\n\n")
    f.write("1. 磁盘上的 `.md` 文件是平台侧定义的只读副本，与平台侧实时同步\n")
    f.write("2. 系统级 cron（feed-pulse-*、deterministic-doctor、profile-image）由运行时管理，新机器自动就有，不用重建\n")
    f.write("3. manifest 里标记 OFF 的任务迁移时保持禁用\n")
    f.write("4. 新机器重建时：用每个 `.md` 文件的 frontmatter（schedule/owner）+ body，逐个 `cron.add` 即可\n")
    f.write("   （状态列为 ARCHIVED/INVALID 的是归档/失效定义，迁移时跳过；OFF 的迁移后保持禁用）\n\n")
    f.write("## 禁用任务列表（迁移时保持禁用）\n\n")
    for r in rows:
        if r[1] == 'OFF':
            f.write(f"- {r[0]}\n")
print(f"[export] {len(rows)} 个 cron 定义已导出（cron.d={cron_d_n}, goals={goal_n}, 禁用={off}）")
EOF

cd "$FILES_DIR" && tar -czf "cron_export_$DATE.tar.gz" "cron_export_$DATE"
echo "[export] 打包完成：$FILES_DIR/cron_export_$DATE.tar.gz ($(du -h "$FILES_DIR/cron_export_$DATE.tar.gz" | cut -f1))"
