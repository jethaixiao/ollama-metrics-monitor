#!/bin/bash
# ============================================================
# Ollama Metrics Monitor - 卸载
#
#   ./uninstall.sh            只停止服务、移除开机自启
#   ./uninstall.sh --purge    同时删除数据库与日志
# ============================================================

set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

echo "停止并移除开机自启…"
launchctl unload "$LAUNCH_DIR/com.ollama.proxy.plist" 2>/dev/null
launchctl unload "$LAUNCH_DIR/com.ollama.ngrok.plist" 2>/dev/null
rm -f "$LAUNCH_DIR/com.ollama.proxy.plist" "$LAUNCH_DIR/com.ollama.ngrok.plist"

pkill -f "ollama-monitor-proxy.py" 2>/dev/null
pkill -f "ngrok http" 2>/dev/null
echo "  ✓ 服务已停止"

# 读取用户配置，尊重自定义 DB_PATH
DB_FILE="$DIR/ollama_metrics.db"
if [ -f "$DIR/config.env" ]; then
  set -a; . "$DIR/config.env"; set +a
  [ -n "${DB_PATH:-}" ] && DB_FILE="$DB_PATH"
fi

if [ "$PURGE" = true ]; then
  rm -f "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"
  rm -f /tmp/ollama-proxy.log /tmp/ollama-proxy.err.log /tmp/ollama-ngrok.log /tmp/ollama-ngrok.err.log
  echo "  ✓ 数据库与日志已删除"
else
  echo "  · 数据库保留在 $DB_FILE（如需删除：./uninstall.sh --purge）"
fi

echo "卸载完成。Ollama 本身未受影响。"
