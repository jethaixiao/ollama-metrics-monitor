#!/bin/bash
# SwiftBar 插件：Ollama 模型状态菜单栏监控
# 数据源：本地 ollama-monitor-proxy (127.0.0.1:11437)
# 文件名中的 30s = 每 30 秒刷新一次菜单栏
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:$PATH"
PROXY="http://127.0.0.1:11437"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
export SCRIPT_PATH

# ---- 动作模式（SwiftBar 菜单项回调）----
case "$1" in
  unload)
    curl -s --max-time 30 -X POST "$PROXY/api/model-residency" \
      -H 'Content-Type: application/json' -H 'X-Model-Control: 1' \
      -d "{\"model\":\"$2\",\"enabled\":false}" >/dev/null
    osascript -e "display notification \"已卸载 $2\" with title \"Ollama\"" 2>/dev/null
    exit 0 ;;
  load)
    osascript -e "display notification \"正在加载 $2，大模型需等待数十秒…\" with title \"Ollama\"" 2>/dev/null &
    curl -s --max-time 180 -X POST "$PROXY/api/model-residency" \
      -H 'Content-Type: application/json' -H 'X-Model-Control: 1' \
      -d "{\"model\":\"$2\",\"enabled\":true}" >/dev/null
    osascript -e "display notification \"已加载 $2\" with title \"Ollama\"" 2>/dev/null
    exit 0 ;;
esac

# ---- 状态模式：拉取数据并输出菜单 ----
PS_JSON=$(curl -s --max-time 4 "$PROXY/api/ps")
TAGS_JSON=$(curl -s --max-time 4 "$PROXY/api/tags")
METRICS_JSON=$(curl -s --max-time 4 "$PROXY/metrics")

if [ -z "$PS_JSON" ]; then
  cat <<'EOF'
🔴 Ollama 离线
---
proxy :11437 无响应 | color=#e05252
打开看板 | href=http://127.0.0.1:11437/dashboard.html
EOF
  exit 0
fi

export PS_JSON TAGS_JSON METRICS_JSON
python3 <<'PYEOF'
import json, os

def gb(b):
    return f"{b/1073741824:.1f}GB" if b else ""

def fmt_num(n):
    n = n or 0
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.1f}K"
    return str(n)

def fmt_ms(ms):
    ms = ms or 0
    if ms >= 1000: return f"{ms/1000:.1f}s"
    return f"{ms:.0f}ms"

ps = json.loads(os.environ.get("PS_JSON") or "{}")
try: tags = json.loads(os.environ.get("TAGS_JSON") or "{}")
except Exception: tags = {}
try: mt = json.loads(os.environ.get("METRICS_JSON") or "{}")
except Exception: mt = {}

running = ps.get("models", [])
script = os.environ.get("SCRIPT_PATH", "")
total_vram = sum(m.get("size_vram") or m.get("size") or 0 for m in running)
running_names = {r["name"] for r in running}
avail = [(m["name"], m.get("size") or 0) for m in tags.get("models", [])
         if m["name"] not in running_names]

# 菜单栏标题
if len(running) == 1:
    print(f"🟢 {running[0]['name']} · {gb(total_vram)}")
elif running:
    print(f"🟢 {len(running)} 模型 · {gb(total_vram)}")
else:
    print("⚪ Ollama 空闲")

print("---")

# 运行中模型
if running:
    print("⚡ 已加载（点模型卸载）")
    for m in running:
        name = m["name"]
        mem = gb(m.get("size_vram") or m.get("size") or 0)
        suffix = f" · {m['expires']}" if m.get("expires") else ""
        print(f"--{name} · {mem}{suffix}")
        print(f"--卸载 {name} · {mem}{suffix} | bash=\"{script}\" param1=unload param2=\"{name}\" terminal=false refresh=true color=#e05252")
else:
    print("💤 无模型驻留内存（点模型名加载）")

# 可加载模型
if avail:
    print("📦 可加载（点模型名载入内存）")
    for name, size in avail[:12]:
        print(f"--加载 {name} · {gb(size)} | bash=\"{script}\" param1=load param2=\"{name}\" terminal=false refresh=true")
    if len(avail) > 12:
        print(f"--…共 {len(tags.get('models', []))} 个，全部请打开看板 | href=http://127.0.0.1:11437/dashboard.html")

print("---")

# 统计摘要
cum = mt.get("cumulative") or {}
pct = mt.get("latency_percentiles") or {}
print(f"📊 累计请求 {fmt_num(cum.get('total_requests'))} · tokens {fmt_num(cum.get('total_tokens'))}")
tpot = pct.get("tpot_p95")
print(f"⏱ P95 延迟 {fmt_ms(pct.get('p95'))} · 生成速度 P95 {fmt_ms(tpot)}/tok" if tpot else f"⏱ P95 延迟 {fmt_ms(pct.get('p95'))}")

print("---")
print("🖥 打开看板 | href=http://127.0.0.1:11437/dashboard.html")
print("🔄 刷新 | refresh=true")
PYEOF
