#!/bin/bash
# Ollama Metrics Monitor - 运维脚本
#
# 架构（三个组件，各自由 launchd 常驻监管）：
#   Ollama            :11434   真正的推理后端
#   Metrics Proxy     :11437   拦截 + 记账 + Dashboard + OpenAI 兼容层
#   ngrok             :4040    把 11437 暴露到固定公网域名
#
# launchd 服务：
#   com.ollama.proxy   直接前台运行 proxy，崩溃自动拉起
#   com.ollama.ngrok   直接前台运行 ngrok，崩溃自动拉起
#   Ollama 自身由 Ollama.app 托管
#
# 用法：
#   ./start-monitor.sh          查看状态
#   ./start-monitor.sh restart  重启 proxy + ngrok
#   ./start-monitor.sh logs     跟踪日志

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_LABEL="com.ollama.proxy"
NGROK_LABEL="com.ollama.ngrok"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

# 读用户配置
if [ -f "$SCRIPT_DIR/config.env" ]; then
  set -a; . "$SCRIPT_DIR/config.env"; set +a
fi
PROXY_PORT="${PROXY_PORT:-11437}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
PUBLIC_HOST="${NGROK_DOMAIN:-}"
TUNNEL_ENABLED="${TUNNEL_ENABLED:-true}"

ACTION="${1:-status}"

case "$ACTION" in
  restart)
    echo "🔄 重启 proxy + ngrok ..."
    launchctl kickstart -k "gui/$(id -u)/$PROXY_LABEL" 2>/dev/null \
      || { launchctl unload "$LAUNCH_DIR/$PROXY_LABEL.plist" 2>/dev/null; launchctl load "$LAUNCH_DIR/$PROXY_LABEL.plist"; }
    if [ "$TUNNEL_ENABLED" = "true" ] && [ -f "$LAUNCH_DIR/$NGROK_LABEL.plist" ]; then
      launchctl kickstart -k "gui/$(id -u)/$NGROK_LABEL" 2>/dev/null \
        || { launchctl unload "$LAUNCH_DIR/$NGROK_LABEL.plist" 2>/dev/null; launchctl load "$LAUNCH_DIR/$NGROK_LABEL.plist"; }
    else
      launchctl unload "$LAUNCH_DIR/$NGROK_LABEL.plist" 2>/dev/null || true
      pkill -f "ngrok http .*$PROXY_PORT" 2>/dev/null || true
    fi
    sleep 6
    ;;
  logs)
    echo "📜 Proxy 日志（Ctrl+C 退出）"
    tail -f /tmp/ollama-proxy.log /tmp/ollama-proxy.err.log
    exit 0
    ;;
  status) ;;
  *)
    echo "用法: $0 [status|restart|logs]"
    exit 1
    ;;
esac

echo "========================================="
echo "  Ollama Metrics Monitor 状态"
echo "========================================="

printf "%-14s" "Ollama"
if curl -s --max-time 3 "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1; then
  n=$(curl -s --max-time 3 "$OLLAMA_BASE_URL/api/tags" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null)
  echo "✅ 运行中 ($OLLAMA_BASE_URL)  模型 $n 个"
else
  echo "❌ 未运行 (请启动 Ollama)"
fi

printf "%-14s" "Proxy"
if curl -s --max-time 3 http://localhost:$PROXY_PORT/health >/dev/null 2>&1; then
  echo "✅ 运行中 (:$PROXY_PORT)"
else
  echo "❌ 未运行 — 执行: $0 restart"
fi

printf "%-14s" "ngrok"
if [ "$TUNNEL_ENABLED" != "true" ]; then
  echo "— 已禁用（TUNNEL_ENABLED=false）"
elif curl -s --max-time 3 http://localhost:4040/api/tunnels 2>/dev/null | grep -q '"public_url": *"http'; then
  URL=$(curl -s --max-time 3 http://localhost:4040/api/tunnels | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['tunnels'][0]['public_url'] if d.get('tunnels') else '')" 2>/dev/null)
  echo "✅ 隧道在线 ${URL}"
else
  echo "⚠️  隧道未就绪 — 执行: $0 restart（端口/域名改动需重跑 ./install.sh）"
fi

echo
echo "📊 本地 Dashboard : http://localhost:$PROXY_PORT/dashboard.html"
[ -n "$PUBLIC_HOST" ] && echo "🌐 公网 Dashboard : https://$PUBLIC_HOST/dashboard.html"
echo "🔌 OpenAI 兼容接口: http://127.0.0.1:$PROXY_PORT/v1"
echo
echo "▶ 开机自启已由 launchd 接管（无需本脚本）"
echo "▶ 清除统计数据：Dashboard 顶部「清除」按钮"
