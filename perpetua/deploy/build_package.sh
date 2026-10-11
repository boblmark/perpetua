#!/bin/bash
# Perpetua / ViralLoop 一键部署包构建脚本
# 在源机器上运行：bash build_package.sh
# 产物：perpetua-deploy-<date>.tar.gz

set -e
DATA_DIR="/home/hatch/data"
OUT_DIR="/home/hatch/data/perpetua/deploy"
STAGE="$OUT_DIR/stage"
DATE=$(date +%Y%m%d-%H%M)
PKG="perpetua-deploy-$DATE.tar.gz"

rm -rf "$STAGE"
mkdir -p "$STAGE/perpetua"

echo "[1/5] 复制核心代码..."
cp -r "$DATA_DIR/mcp_server"        "$STAGE/" 2>/dev/null || true
mkdir -p "$STAGE/perpetua-code"
# 复制 perpetua 但排除 deploy 目录本身（避免递归）
tar -cf - -C "$DATA_DIR/perpetua" --exclude='./deploy' . 2>/dev/null | tar -xf - -C "$STAGE/perpetua-code" || true
cp -r "$DATA_DIR/jev"               "$STAGE/" 2>/dev/null || true
cp -r "$DATA_DIR/youtube"           "$STAGE/" 2>/dev/null || true
cp -r "$DATA_DIR/ask_studio"        "$STAGE/" 2>/dev/null || true
cp -r "$DATA_DIR/collab"            "$STAGE/" 2>/dev/null || true

for f in trend_spike_detector.py pipeline_latency.py virality_score.py relay.py; do
  cp "$DATA_DIR/$f" "$STAGE/" 2>/dev/null || true
done

echo "[2/5] 清理敏感信息和缓存..."
# 删除 venv、__pycache__、日志、大体积媒体
find "$STAGE" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name "venv" -type d -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name "*.log" -delete 2>/dev/null || true
find "$STAGE" -name "*.mp4" -delete 2>/dev/null || true
find "$STAGE" -name ".token*" -delete 2>/dev/null || true
find "$STAGE" -name ".oauth.json" -delete 2>/dev/null || true
find "$STAGE" -name ".api_key" -delete 2>/dev/null || true
find "$STAGE" -name "*.bak-*" -delete 2>/dev/null || true

# tenants registry 脱敏：保留结构，清空 oauth 路径
if [ -f "$STAGE/perpetua-code/tenants/registry.json" ]; then
  python3 -c "
import json
p='$STAGE/perpetua-code/tenants/registry.json'
d=json.load(open(p))
for t in d.get('tenants',{}).values():
    t['oauth_file']=''; t['youtube_channel_id']=''
json.dump(d,open(p,'w'),indent=2,ensure_ascii=False)
" 2>/dev/null || true
fi

echo "[3/5] 写入安装脚本..."
cp "$OUT_DIR/install.sh" "$STAGE/install.sh"
cp "$OUT_DIR/requirements.txt" "$STAGE/requirements.txt"
cp "$OUT_DIR/README.md" "$STAGE/README.md"
cp -r "$OUT_DIR/systemd" "$STAGE/systemd"

echo "[4/5] 打包..."
cd "$OUT_DIR"
tar -czf "$PKG" -C stage .
rm -rf stage

echo "[5/5] 完成"
ls -lh "$OUT_DIR/$PKG"
echo ""
echo "把这个文件传到新机器，解压后运行 ./install.sh 即可"
