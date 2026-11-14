#!/bin/bash
# ============================================================
# Ollama Metrics Monitor - 一键安装
#
# 用法:
#   ./install.sh              # 安装并启动（开机自启）
#   ./install.sh --no-tunnel  # 不装公网隧道，仅本机/局域网
#   ./install.sh --no-venv    # 不使用虚拟环境，直接用系统 Python
#
# 安装内容:
#   1. 检查 Python / Homebrew / Ollama
#   2. 安装 Python 依赖
#   3. 生成 ~/Library/LaunchAgents/com.ollama.proxy.plist
#      ~/Library/LaunchAgents/com.ollama.ngrok.plist（开启隧道时）
#   4. 启动并自检
# ============================================================

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1

LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/ollama-monitor"
mkdir -p "$LOG_DIR" 2>/dev/null || true
# launchd 打开重定向文件时不受 Umask 影响，这里预创建并收紧权限
for f in proxy.log proxy.err.log ngrok.log ngrok.err.log; do
  touch "$LOG_DIR/$f" 2>/dev/null || true
  chmod 600 "$LOG_DIR/$f" 2>/dev/null || true
done

# plist 是 XML，路径里的 & < > 必须转义，否则 launchd 拒绝加载
xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
DIR_XML="$(xml_escape "$DIR")"
PROXY_LABEL="com.ollama.proxy"
NGROK_LABEL="com.ollama.ngrok"
PY="$(command -v python3 || true)"

ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
die()  { printf "  \033[31m✗\033[0m %s\n" "$1"; exit 1; }
hr()   { printf -- "------------------------------------------------------------\n"; }

echo
echo "Ollama Metrics Monitor — 安装程序"
hr

# ---------- 0. 配置 ----------
if [ ! -f config.env ]; then
  cp config.env.example config.env 2>/dev/null || die "缺少 config.env / config.env.example"
  warn "已从模板生成 config.env"
fi

# 首次安装自动生成访问口令
if ! grep -q '^ACCESS_CODE=.' config.env 2>/dev/null; then
  GEN_CODE="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
  if grep -q '^ACCESS_CODE=' config.env 2>/dev/null; then
    sed -i '' "s|^ACCESS_CODE=.*|ACCESS_CODE=$GEN_CODE|" config.env
  else
    printf '\nACCESS_CODE=%s\n' "$GEN_CODE" >> config.env
  fi
  ok "已生成访问口令：$GEN_CODE"
fi

set -a; . ./config.env; set +a
PROXY_PORT="${PROXY_PORT:-11437}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
TUNNEL_ENABLED="${TUNNEL_ENABLED:-true}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"

for a in "$@"; do
  [ "$a" = "--no-tunnel" ] && TUNNEL_ENABLED=false
done

# 占位符或空值都视为“未配置固定域名”，改走随机域名，避免别人照装失败
case "$NGROK_DOMAIN" in
  ""|your-name*|http*) NGROK_DOMAIN="" ;;
esac

echo "  代理端口   : $PROXY_PORT"
echo "  上游 Ollama: $OLLAMA_BASE_URL"
echo "  公网隧道   : $TUNNEL_ENABLED"
echo

# ---------- 1. 环境检查 ----------
printf "[1/6] 环境检查\n"
[ "$(uname)" = "Darwin" ] || die "仅支持 macOS（其他系统请手动用 python3 启动）"
[ -n "$PY" ] || die "未找到 python3，请先安装：brew install python"
ok "python3 → $PY"

if command -v ollama >/dev/null 2>&1; then
  ok "ollama 已安装"
else
  die "未安装 Ollama，请先安装：brew install ollama（或 https://ollama.com/download）"
fi
echo

# ---------- 2. Ollama 是否在跑 ----------
printf "[2/6] Ollama 服务\n"
if curl -s --max-time 3 "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; then
  ok "Ollama 正在运行"
else
  warn "Ollama 未运行，尝试启动…"
  (ollama serve >/tmp/ollama-serve.log 2>&1 &) ; sleep 6
  curl -s --max-time 3 "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1 \
    && ok "Ollama 已启动" \
    || die "Ollama 启动失败，请手动运行 ollama serve 后重试（日志 /tmp/ollama-serve.log）"
fi
MODELS=$(curl -s "${OLLAMA_BASE_URL}/api/tags" | "$PY" -c "import sys,json;print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo 0)
echo "      已下载模型: $MODELS 个"
[ "$MODELS" -eq 0 ] && warn "还没有模型，先执行: ollama pull qwen2.5:7b"
echo

# ---------- 3. Python 依赖 ----------
printf "[3/6] Python 依赖\n"
VENV_DIR="$DIR/.venv"
USE_VENV=true
for a in "$@"; do [ "$a" = "--no-venv" ] && USE_VENV=false; done

if [ -d "$VENV_DIR" ] && "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, requests" >/dev/null 2>&1; then
  PY="$VENV_DIR/bin/python"
  ok "使用已有虚拟环境 .venv"
elif [ "$USE_VENV" = true ]; then
  echo "      创建虚拟环境 .venv（不污染系统 Python）…"
  if "$PY" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    PY="$VENV_DIR/bin/python"
    "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    if ! "$PY" -m pip install --quiet fastapi uvicorn requests 2>"$DIR/.pip-error.log"; then
      warn "虚拟环境安装失败，回退系统 Python"
      tail -5 "$DIR/.pip-error.log" 2>/dev/null | sed 's/^/        /'
      PY="$(command -v python3)"; USE_VENV=false
    else
      ok "依赖已装入 .venv"
    fi
  else
    warn "无法创建虚拟环境，使用当前 Python"
    PY="$(command -v python3)"; USE_VENV=false
  fi
elif "$PY" -c "import fastapi, uvicorn, requests" >/dev/null 2>&1; then
  ok "按 --no-venv 使用系统 Python"
else
  echo "      创建虚拟环境并安装依赖（不动系统 Python）…"
  if "$PY" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    PY="$VENV_DIR/bin/python"
    "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    if ! "$PY" -m pip install --quiet fastapi uvicorn requests 2>"$DIR/.pip-error.log"; then
      warn "虚拟环境安装失败，错误摘录："
      tail -5 "$DIR/.pip-error.log" | sed 's/^/        /'
      die "依赖安装失败"
    fi
    ok "依赖已装入 .venv"
  else
    warn "无法创建虚拟环境，改用当前 Python（可能污染全局环境）"
    "$PY" -m pip install --quiet --break-system-packages fastapi uvicorn requests 2>"$DIR/.pip-error.log" \
      || "$PY" -m pip install --quiet fastapi uvicorn requests 2>"$DIR/.pip-error.log" \
      || { tail -5 "$DIR/.pip-error.log" | sed 's/^/        /'; die "依赖安装失败"; }
  fi
fi
"$PY" -c "import fastapi, uvicorn, requests" >/dev/null 2>&1 || die "依赖仍不可用"
echo

# ---------- 4. 端口占用检查 ----------
printf "[4/6] 端口检查\n"
BUSY=$(lsof -nP -iTCP:"$PROXY_PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $2}')
if [ -n "${BUSY:-}" ]; then
  if ps -p "$BUSY" -o command= 2>/dev/null | grep -q "ollama-monitor-proxy.py"; then
    ok "端口 $PROXY_PORT 被本程序旧进程占用，将重启"
  else
    die "端口 $PROXY_PORT 被其他程序占用（PID ${BUSY}）。改 config.env 里的 PROXY_PORT 后重试"
  fi
else
  ok "端口 $PROXY_PORT 空闲"
fi
echo

# ---------- 5. 生成 LaunchAgent ----------
printf "[5/6] 开机自启配置\n"
mkdir -p "$LAUNCH_DIR"
PY_XML="$(xml_escape "$PY")"   # venv 可能已改写 PY，这里再取一次
launchctl unload "$LAUNCH_DIR/$PROXY_LABEL.plist" 2>/dev/null
launchctl unload "$LAUNCH_DIR/$NGROK_LABEL.plist" 2>/dev/null
pkill -f "ollama-monitor-proxy.py" 2>/dev/null
pkill -f "ngrok http .*$PROXY_PORT" 2>/dev/null
sleep 1

cat > "$LAUNCH_DIR/$PROXY_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PROXY_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY_XML</string>
    <string>$DIR_XML/ollama-monitor-proxy.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR_XML</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/proxy.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/proxy.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
</dict>
</plist>
PLIST
if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$LAUNCH_DIR/$PROXY_LABEL.plist" >/dev/null 2>&1; then
    die "生成的 plist 不合法：$LAUNCH_DIR/$PROXY_LABEL.plist"
  fi
  ok "已生成 ${PROXY_LABEL}"

if [ "$TUNNEL_ENABLED" = "true" ]; then
  if ! command -v ngrok >/dev/null 2>&1; then
    warn "未安装 ngrok，跳过公网隧道（可 brew install ngrok 后重跑本脚本）"
  elif [ -z "$NGROK_DOMAIN" ]; then
    warn "config.env 里 NGROK_DOMAIN 为空，改用随机临时域名"
    NGROK_ARGS="http $PROXY_PORT --log=stdout --log-level=info"
    cat > "$LAUNCH_DIR/$NGROK_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$NGROK_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v ngrok)</string>
    <string>http</string><string>$PROXY_PORT</string>
    <string>--log=stdout</string><string>--log-level=info</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/ngrok.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/ngrok.err.log</string>
</dict>
</plist>
PLIST
    ok "已生成 ${NGROK_LABEL}（随机域名模式）"
  else
    cat > "$LAUNCH_DIR/$NGROK_LABEL.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$NGROK_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v ngrok)</string>
    <string>http</string><string>$PROXY_PORT</string>
    <string>--url=$NGROK_DOMAIN</string>
    <string>--log=stdout</string><string>--log-level=info</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/ngrok.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/ngrok.err.log</string>
</dict>
</plist>
PLIST
    ok "已生成 ${NGROK_LABEL}（固定域名 ${NGROK_DOMAIN}）"
  fi
else
  # 关键：只跳过生成还不够，旧 plist 会在下次 load 时把隧道重新拉起来
  rm -f "$LAUNCH_DIR/$NGROK_LABEL.plist"
  launchctl unload "$LAUNCH_DIR/$NGROK_LABEL.plist" 2>/dev/null || true
  warn "已按 --no-tunnel 跳过公网隧道，并移除旧的 ngrok 自启配置"
fi
echo

# ---------- 6. 启动并自检 ----------
printf "[6/6] 启动并自检\n"
launchctl load "$LAUNCH_DIR/$PROXY_LABEL.plist" 2>/dev/null
if [ "$TUNNEL_ENABLED" = "true" ] && [ -f "$LAUNCH_DIR/$NGROK_LABEL.plist" ]; then launchctl load "$LAUNCH_DIR/$NGROK_LABEL.plist" 2>/dev/null; fi

for i in $(seq 1 15); do
  curl -s --max-time 2 "http://localhost:$PROXY_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

if curl -s --max-time 3 "http://localhost:$PROXY_PORT/health" >/dev/null 2>&1; then
  ok "代理已就绪 http://localhost:$PROXY_PORT"
else
  die "代理启动失败，查看: tail -30 ~/Library/Logs/ollama-monitor/proxy.err.log"
fi

if [ -f "$LAUNCH_DIR/$NGROK_LABEL.plist" ]; then
  echo "      等待 ngrok 建立隧道（最长 40 秒）…"
  for i in $(seq 1 40); do
    curl -s --max-time 2 http://localhost:4040/api/tunnels 2>/dev/null | grep -q '"public_url": *"http' && break
    sleep 1
  done
  PUB=$("$PY" - <<'PYEOF' 2>/dev/null
import json,urllib.request
try:
    d=json.load(urllib.request.urlopen("http://localhost:4040/api/tunnels",timeout=3))
    print(d["tunnels"][0]["public_url"] if d.get("tunnels") else "")
except Exception:
    print("")
PYEOF
)
  [ -n "$PUB" ] && ok "公网隧道 $PUB" || warn "隧道尚未就绪，稍后看 ~/Library/Logs/ollama-monitor/ngrok.err.log"
fi

echo
hr
echo "  安装完成"
hr
echo
echo "  本机看板   : http://localhost:$PROXY_PORT/dashboard.html"
echo "  OpenAI 接口: http://localhost:$PROXY_PORT/v1"
[ -n "${PUB:-}" ] && echo "  公网看板   : $PUB/dashboard.html"
echo
echo "  下一步：把客户端（DSH / WorkBuddy / 代码）的 API 地址"
echo "  从 ${OLLAMA_BASE_URL} 改成 http://127.0.0.1:$PROXY_PORT/v1"
echo
echo "  常用命令："
echo "    ./start-monitor.sh          查看状态"
echo "    ./start-monitor.sh restart  重启服务"
echo "    ./start-monitor.sh logs     看日志"
echo "    ./uninstall.sh              卸载"
echo
