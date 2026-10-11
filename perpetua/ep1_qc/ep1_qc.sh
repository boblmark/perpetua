#!/usr/bin/env bash
# EP1 QC 机检脚本（对应 ep1-QC-checklist.md 的第二、三部分）
#
# 用法：
#   ./ep1_qc.sh /path/to/ep1_final.mp4 [输出目录]
#
# 可选环境变量：
#   FFMPEG=/path/to/ffmpeg     指定 ffmpeg（默认优先使用 imageio-ffmpeg 自带的二进制）
#   USER_START=120             用户报告问题的起始秒（默认 120 = 2:00）
#   USER_END=883               用户报告问题的结束秒（默认 883 = 14:43）
#   BLACK_MAX_YMAX=20          单帧亮度最大值低于该值视为“纯黑”（限幅制下黑场约 16）
#
# 说明：机检只能发现“黑屏、静音、解码错误、冻结”等客观现象，
#       “音画是否对应”“版权与政策”仍需人工复核，脚本会在报告中列出待办。

set -u

IN="${1:?用法: $0 <视频文件> [输出目录]}"
OUT="${2:-./qc_out}"
USER_START="${USER_START:-120}"
USER_END="${USER_END:-883}"
BLACK_MAX_YMAX="${BLACK_MAX_YMAX:-20}"

if [ -z "${FFMPEG:-}" ]; then
  FFMPEG="$(python3 -c 'import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || echo ffmpeg)"
fi
if ! "$FFMPEG" -version >/dev/null 2>&1; then
  echo "找不到 ffmpeg，请设置 FFMPEG=... 或 pip install imageio-ffmpeg" >&2
  exit 1
fi

mkdir -p "$OUT/frames"
LOG="$OUT/machine_checks.log"
BLACK="$OUT/black_frames.txt"
SILENCE="$OUT/silence.txt"
DECODE="$OUT/decode_errors.txt"
FREEZE="$OUT/freeze.txt"
CHECK="$OUT/checkpoints.tsv"
REPORT="$OUT/report.md"

: > "$LOG"
log() { echo "$@" | tee -a "$LOG"; }

log "== 0. 基本信息 =="
INFO="$("$FFMPEG" -hide_banner -i "$IN" 2>&1)"
echo "$INFO" | grep -E "Duration|Stream #0" | tee -a "$LOG"
DUR_RAW="$(echo "$INFO" | sed -n 's/.*Duration: \([0-9:.]*\).*/\1/p' | head -1)"
DUR="$(echo "$DUR_RAW" | awk -F: '{ if (NF==3) print int($1*3600+$2*60+$3); else print 0 }')"
log "时长（秒）: $DUR"

log ""
log "== 1. 黑帧检测 (blackdetect d=2, pix_th=0.10) =="
"$FFMPEG" -hide_banner -i "$IN" -vf blackdetect=d=2:pix_th=0.10 -an -f null - 2>&1 \
  | grep -E "black_start" > "$BLACK" || true
if [ -s "$BLACK" ]; then cat "$BLACK" | tee -a "$LOG"; else log "未检出黑帧段"; fi

log ""
log "== 2. 静音检测 (silencedetect noise=-40dB d=3，音频流) =="
"$FFMPEG" -hide_banner -i "$IN" -af silencedetect=noise=-40dB:d=3 -vn -f null - 2>&1 \
  | grep -E "silence_(start|end)" > "$SILENCE" || true
if [ -s "$SILENCE" ]; then cat "$SILENCE" | tee -a "$LOG"; else log "未检出静音段（>=3s）"; fi

log ""
log "== 3. 解码错误 / 时间戳异常 (-v error) =="
"$FFMPEG" -v error -hide_banner -i "$IN" -f null - > "$DECODE" 2>&1 || true
if [ -s "$DECODE" ]; then
  log "检出 $(wc -l < "$DECODE") 行错误输出，前 20 行："
  head -20 "$DECODE" | tee -a "$LOG"
else
  log "无解码错误输出"
fi

log ""
log "== 4. 冻结帧检测 (freezedetect n=-60dB d=2) =="
"$FFMPEG" -hide_banner -i "$IN" -vf freezedetect=n=-60dB:d=2 -an -f null - 2>&1 \
  | grep -E "freeze_(start|end|duration)" > "$FREEZE" || true
if [ -s "$FREEZE" ]; then cat "$FREEZE" | tee -a "$LOG"; else log "未检出冻结帧段"; fi

log ""
log "== 5. 抽查点位（每点 10 秒，逐秒取亮度；并截图） =="
# 点位：0:00、5:00、10:00、15:00、结尾 19:30；以及用户报告区间内每 60 秒一个点
POINTS="0 300 600 900"
END_PT=$(( DUR > 40 ? DUR - 30 : 0 ))
[ "$END_PT" -gt 0 ] && POINTS="$POINTS $END_PT"
t=$USER_START
while [ "$t" -le "$USER_END" ] && [ "$t" -lt "$DUR" ]; do
  POINTS="$POINTS $t"
  t=$(( t + 60 ))
done
POINTS="$(echo $POINTS | tr ' ' '\n' | sort -n | uniq | tr '\n' ' ')"

printf "point_sec\tsample_sec\tYAVG\tYMAX\tverdict\n" > "$CHECK"
for p in $POINTS; do
  [ "$p" -ge "$DUR" ] && continue
  STATS="$("$FFMPEG" -hide_banner -ss "$p" -i "$IN" -t 10 -an \
      -vf "fps=1,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-,metadata=print:key=lavfi.signalstats.YMAX:file=-" \
      -f null - 2>/dev/null)"
  # 逐帧输出 YAVG / YMAX，按顺序配对
  YAVG_LIST="$(echo "$STATS" | sed -n 's/.*YAVG=\([0-9.]*\).*/\1/p')"
  YMAX_LIST="$(echo "$STATS" | sed -n 's/.*YMAX=\([0-9.]*\).*/\1/p')"
  i=0
  paste <(echo "$YAVG_LIST") <(echo "$YMAX_LIST") | while IFS=$'\t' read -r yavg ymax; do
    [ -z "${yavg:-}" ] && continue
    i=$((i+1))
    verdict="ok"
    ymax_i=${ymax%.*}
    if [ "${ymax_i:-255}" -le "$BLACK_MAX_YMAX" ]; then verdict="疑似纯黑"; fi
    printf "%s\t%s\t%s\t%s\t%s\n" "$p" "$((p+i-1))" "$yavg" "$ymax" "$verdict" >> "$CHECK"
  done
  # 每个点位截一张图（点位后 5 秒）
  "$FFMPEG" -hide_banner -loglevel error -y -ss "$((p+5))" -i "$IN" -frames:v 1 \
      "$OUT/frames/at_$(printf %05d "$p").png" 2>/dev/null || true
done
TOTAL=$(($(wc -l < "$CHECK") - 1))
BLACK_PTS=$(awk -F'\t' 'NR>1 && $5=="疑似纯黑"' "$CHECK" | wc -l)
log "共采样 $TOTAL 帧，疑似纯黑 $BLACK_PTS 帧（明细见 $CHECK，截图见 $OUT/frames/）"

log ""
log "== 6. 用户报告区间 ${USER_START}s–${USER_END}s 的汇总 =="
UB="$(sed -n 's/.*black_start:\([0-9.]*\).*/\1/p' "$BLACK" | awk -v s="$USER_START" -v e="$USER_END" '$1+0>=s && $1+0<=e{c++} END{print c+0}')"
UBS="$(awk -v s="$USER_START" -v e="$USER_END" -F'\t' 'NR>1 && $2>=s && $2<=e && $5=="疑似纯黑"' "$CHECK" | wc -l)"
USIL="$(awk -v s="$USER_START" -v e="$USER_END" '/silence_start/{ for(i=1;i<=NF;i++) if($i ~ /silence_start/) {v=$(i+1); if (v+0>=s && v+0<=e) c++} } END{print c+0}' "$SILENCE")"
UFRZ="$(awk -v s="$USER_START" -v e="$USER_END" '/freeze_start/{ for(i=1;i<=NF;i++) if($i ~ /freeze_start/) {v=$(i+1); if (v+0>=s && v+0<=e) c++} } END{print c+0}' "$FREEZE")"
log "区间内黑屏段起点数（全片 blackdetect）: $UB"
log "区间内抽样点纯黑帧数: $UBS"
log "区间内静音段起点数: $USIL"
log "区间内冻结段起点数: $UFRZ"

# ---------- 生成报告 ----------
{
  echo "# EP1 机检报告"
  echo
  echo "- 文件：\`$IN\`"
  echo "- 生成时间：$(date '+%Y-%m-%d %H:%M:%S')"
  echo "- 时长：${DUR} 秒"
  echo
  echo "## 一、用户报告问题（${USER_START}s–${USER_END}s）"
  echo
  if [ "$UB" -gt 0 ] || [ "$UBS" -gt 0 ] || [ "$USIL" -gt 0 ]; then
    echo "**结论：机检证实存在异常**（黑屏段 $UB 处，抽样纯黑帧 $UBS 帧，静音段 $USIL 处，冻结段 $UFRZ 处）。请看下方明细与截图。"
  else
    echo "**结论：机检未发现该区间的黑屏/静音/冻结**。注意：仅覆盖抽样点位，卡顿的主观感受仍需人工在播放器中复看。"
  fi
  echo
  echo "## 二、黑帧段（blackdetect）"
  echo '```'; [ -s "$BLACK" ] && cat "$BLACK" || echo "无"; echo '```'
  echo
  echo "## 三、静音段（silencedetect, ≥3s）"
  echo '```'; [ -s "$SILENCE" ] && cat "$SILENCE" || echo "无"; echo '```'
  echo
  echo "## 四、解码错误"
  echo '```'; [ -s "$DECODE" ] && head -50 "$DECODE" || echo "无"; echo '```'
  echo
  echo "## 五、冻结帧段（freezedetect）"
  echo '```'; [ -s "$FREEZE" ] && cat "$FREEZE" || echo "无"; echo '```'
  echo
  echo "## 六、抽查点位（逐秒亮度）"
  echo
  echo "疑似纯黑帧明细："
  echo
  echo '```'; awk -F'\t' 'NR==1 || $5=="疑似纯黑"' "$CHECK"; echo '```'
  echo
  echo "## 七、需人工复核（机检无法判断）"
  echo
  echo "- [ ] 0:00 开头钩子、5:00、10:00、15:00、结尾 19:30 的画面与声音是否正常"
  echo "- [ ] 每个“深色解说卡 ↔ 全彩 AI 片段”切换处（各 2 处）是否出现黑闪或音断"
  echo "- [ ] 旁白与画面大致对应（抽查 5 处，误差 ≤ 0.5 秒）"
  echo "- [ ] 无未成年人画面、血腥暴力、性暗示"
  echo "- [ ] 30 个 AI fail 片段来源无版权问题，并符合 YouTube 合成内容披露要求"
  echo "- [ ] 标题与画面不存在误导性的标题党内容"
} > "$REPORT"

log ""
log "报告已生成：$REPORT"
