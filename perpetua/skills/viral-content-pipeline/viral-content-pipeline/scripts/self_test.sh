#!/usr/bin/env bash
# 端到端自检：用 example_data 完整跑一遍「分析 → 出表 → 文档」链路
# 用途：验证本技能包在当前环境可用；也作为迁移到新任务时的参照
#
# 用法：bash scripts/self_test.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SKILL="$(dirname "$HERE")"
WORK="${1:-/tmp/pipeline_selftest}"

say(){ printf '\n\033[1;34m▸ %s\033[0m\n' "$*"; }
pass(){ printf '  \033[32m✅ %s\033[0m\n' "$*"; }
fail(){ printf '  \033[31m❌ %s\033[0m\n' "$*"; }

rm -rf "$WORK" && mkdir -p "$WORK/data" "$WORK/out"
cp "$SKILL"/example_data/*.json "$WORK/data/" 2>/dev/null
[ -f "$WORK/data/bili_rows.json" ] || { fail "example_data 缺失"; exit 1; }
pass "示例数据已就位（$(ls "$WORK/data" | wc -l) 个文件）"

export PIPELINE_DATA="$WORK/data"
export PIPELINE_OUT="$WORK/out"
RUN="bash $SKILL/scripts/run_with_libs.sh python3"

say "1/4 分析层 → analysis.json"
$RUN "$SKILL/scripts/analyze/step8_analysis.py" >/dev/null 2>&1 \
  && [ -f "$WORK/data/analysis.json" ] && pass "analysis.json 已生成" || fail "分析层失败"

say "2/4 出表层 → xlsx"
if $RUN "$SKILL/scripts/build/step7_build_final.py" >/dev/null 2>&1; then
  XLSX="$WORK/out/competitor_viral_20261014.xlsx"
  [ -f "$XLSX" ] && pass "xlsx 已生成" || fail "xlsx 未生成"
  python3 - "$XLSX" <<'PY'
import sys
from openpyxl import load_workbook
wb = load_workbook(sys.argv[1])
plats = [s for s in ["bilibili","tiktok","douyin","kuaishou","x"] if s in wb.sheetnames]
rows = sum(wb[s].max_row-1 for s in plats)
blank = sum(1 for s in plats for r in wb[s].iter_rows(min_row=2, values_only=True) for x in r if x in (None,""))
print(f"  ✅ 数据行 {rows} | 空单元格 {blank} | sheets {len(wb.sheetnames)}")
assert blank == 0, "存在空单元格（违反铁律）"
assert "analysis_benchmark" in wb.sheetnames, "缺少分析 sheet"
PY
else
  fail "出表层失败"
fi

say "3/4 文档层 → 样片库 / 方法论 / 一页纸"
$RUN "$SKILL/scripts/docs/step9a_sample_lib.py" >/dev/null 2>&1 \
  && pass "样片库 xlsx" || fail "样片库失败"
$RUN "$SKILL/scripts/docs/step9b_methodology.py" >/dev/null 2>&1 \
  && pass "方法论 docx + pdf" || fail "方法论失败"
$RUN "$SKILL/scripts/docs/step9c_onepager.py" >/dev/null 2>&1 \
  && pass "一页纸 pdf + png" || fail "一页纸失败"

say "4/4 产物清单"
ls -la "$WORK/out/" 2>/dev/null | tail -n +2 | awk '{printf "  %-46s %8.1f KB\n", $9, $5/1024}'
echo
echo "工作目录：$WORK"
echo "（封面墙需真实封面图 covers*/ 目录，示例数据未含，故跳过）"
