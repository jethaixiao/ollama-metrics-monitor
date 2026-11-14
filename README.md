# Ollama Metrics Monitor

> 给本地 Ollama 装一块仪表盘和一本账本。
> 谁调了哪个模型、花了多少 token、慢在哪一步、GPU 当时忙不忙 —— 一眼看清，数据可导出，能开机自启，能分享给朋友看。

架构见 [第 2 节](#2-架构)。

---

## 1. 它解决什么问题

本地跑 Ollama 的人通常会遇到四个盲区：

| 盲区 | 后果 | 本产品怎么解 |
|---|---|---|
| 不知道调了多少 | 想申请算力/预算，拿不出数据 | 累计请求数、token 数、费用估算、可导出 CSV |
| 不知道慢在哪 | 只看到"这次很慢"，说不清是加载慢、首字慢还是生成慢 | 把耗时拆成加载 / 排队 / 输入处理 / 生成 / 其他五段 |
| 不知道谁在占资源 | 多个客户端混用，说不清是哪个模型的锅 | 按模型分组统计，请求级明细带客户端 IP |
| 不知道 GPU 忙不忙 | 只看得到显存占用，看不出负载高低 | GPU 利用率滚动基线（μ±2σ）+ EMA 平滑 |

设计上遵循一条原则：**数字优先，装饰让位**。整个页面只有一种强调色（铜橙），只用在"需要注意的地方"。

界面分两个页签：**监控**（叙事条 → KPI → 趋势 → 模型排名 → 请求明细 → 耗时拆解 → 资源）和**接入指引**（地址、Token、模型名、各语言示例）。

---

## 2. 架构

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ DSH          │   │ WorkBuddy    │   │ 你的脚本/程序 │
│ WorkBuddy    │   │ 其他客户端    │   │ curl / SDK   │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └──────────────────┼──────────────────┘
                          │  OpenAI 兼容 /v1  或  Ollama 原生 /api
                 ┌────────▼─────────┐
                 │  Metrics Proxy   │  :11437
                 │                  │
                 │  · 转发请求       │
                 │  · 解析 token/耗时 │
                 │  · 写 SQLite      │
                 │  · 提供看板页面    │
                 └────────┬─────────┘
                          │
                 ┌────────▼─────────┐
                 │  Ollama          │  :11434
                 │  (推理引擎)       │
                 └──────────────────┘

      ngrok（可选）把 :11437 暴露成固定公网域名，仅供查看
```

**关键点：Proxy 是旁路，不改变 Ollama 本身。** 停掉 Proxy，Ollama 照常工作；只是这段时间的调用不会被记账。

---

## 3. 三分钟上手

### 前置条件

- macOS
- [Ollama](https://ollama.com/download) 已安装并至少拉过一个模型
  ```bash
  ollama pull qwen2.5:7b
  ```
- Homebrew（装 ngrok 用，可选）

### 安装

```bash
git clone https://github.com/jethaixiao/ollama-metrics-monitor.git
cd ollama-metrics-monitor
./install.sh
```

脚本会依次做六件事：查环境 → 确认 Ollama 在跑 → 装 Python 依赖 → 查端口 → 生成开机自启 → 启动并自检。

装完会打印：

```
本机看板   : http://localhost:11437/dashboard.html
OpenAI 接口: http://localhost:11437/v1
公网看板   : https://your-name.ngrok-free.app/dashboard.html
```

打开看板，只要有人调用过模型，数据就开始跳。

### 只在本机用（不要公网）

```bash
./install.sh --no-tunnel
```

---

## 4. 配置

所有配置集中在 `config.env`，改完执行 `./start-monitor.sh restart`。

| 键 | 默认 | 说明 |
|---|---|---|
| `PROXY_PORT` | `11437` | 代理监听端口。客户端都填这个端口 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | 上游 Ollama 地址 |
| `DB_PATH` | 留空 | 留空则用本目录 `ollama_metrics.db`；想换盘就填绝对路径 |
| `LOG_LEVEL` | `INFO` | `DEBUG` 能看到更细的转发日志 |
| `ACCESS_CODE` | 安装时随机生成 | 访问口令：页面登录用、API 用 `Authorization: Bearer <口令>`。留空则关闭鉴权 |
| `BIND_HOST` | `127.0.0.1` | 监听地址。改 `0.0.0.0` 才允许局域网直接访问（局域网同样无鉴权） |
| `MAX_BODY_BYTES` | `8388608` | 单请求体上限（8MB），超出返回 413 |
| `TUNNEL_ENABLED` | `true` | 是否启用公网隧道 |
| `NGROK_DOMAIN` | 留空 | ngrok 免费账号可申请 1 个固定域名，形如 `your-name.ngrok-free.app`；留空则每次启动用随机域名 |

> **端口为什么不是 11434？** 因为 11434 被 Ollama 占着。Ollama 只认这一个端口，改起来麻烦，所以让 Proxy 换个端口，让客户端改连 Proxy —— 改客户端比改服务端省事。

---

## 5. 界面怎么读

页面从上到下是一条阅读动线：**先看结论，再看趋势，最后查个案。**

### ① 叙事条（最顶部一行）

自动生成的一句话结论，三种状态：

| 颜色 | 含义 | 判读 |
|---|---|---|
| 绿 | 系统正常 | 无异常波动，不用管 |
| 黄 | 流量突增 / 延迟偏高 | 有窗口请求数超过均值 2 倍，或 P95 > 5s |
| 红 | GPU 异常 | 某时刻 GPU 利用率 Z 分数 > 2 且绝对值 > 10% |

故意忽略"低负载异常"（Z < -2）。模型空转时利用率掉到 0.5% 是好事，不是告警。

### ② KPI 四格条

总请求数 · 总 Tokens · 估算费用 · P95/P99 延迟。

这四项是"给老板/给自己看进度"的，不适合用来下判断，判断看下面的图。

### ③ 请求趋势（近 2 小时，5 分钟粒度）

- **黑色柱子**：每 5 分钟的请求数
- **橙色折线**：GPU 利用率 EMA（指数移动平均，α=0.3）
- **红点**：被判定为异常峰值的窗口

为什么是 2 小时 / 5 分钟：小时级会抹平突发，秒级看不出形状。5 分钟是"能看出峰值形状"和"不至于全是噪点"的折中。

为什么用 EMA 而不是原始值：原始 GPU 曲线抖得看不清趋势，EMA 保留走势、滤掉毛刺。

### ④ 模型排名

横向条形，左到右依次是：模型名 · 请求量条 · 请求次数 · 平均响应时间。

一眼看出"哪个模型在被用、用得贵不贵"。

### ⑤ 最近请求（按异常分数排序）

**不按时间倒序，按异常分数倒序。** 有问题的请求永远置顶。

异常分数算法：

| 条件 | 加分 |
|---|---|
| 每 token 耗时 > P95 | +2 |
| 每 token 耗时 > P99 | +3 |
| 其他开销占比 > 40%（且 > 1 秒） | +2 |
| 首字延迟 > 2 秒 | +1 |
| 当时 GPU 利用率 > 80% | +1 |
| 失败 | +5 |

> 为什么不用绝对响应时间打分：同样 15 秒，输出 30 个 token 是真慢，输出 600 个 token 只是生成得多。
> 绝对耗时会随输出长度线性放大，用它打分必然误伤长输出。

分数 ≥ 3 的行会淡橙底色。`unknown` + 300 秒 + 0 token 的超时噪声会被自动折叠，只在标题旁提示"已隐藏 N 条"。

### ⑥ GPU 资源监控

四条线：

- **原始值**（细线）：真实采样，看毛刺
- **EMA 平滑**（橙线）：看趋势
- **μ+2σ / μ-2σ**（黄虚线）：正常波动区间

横轴是采样时间（HH:MM，每 5 秒一点，窗口 30 分钟）。卡片右上角实时显示「当前 / 基线 / Z 分数 / 已采集时长」，鼠标悬停可看精确到秒的采样时刻。

**判读法：落在虚线带内 = 正常；连续跑出上界 = 资源真的紧；一直在下界附近 = 模型空转，不用加卡。**

### ⑦ 单次请求详情

点表格任意一行弹出：

- **耗时分解条形图**：TTFT / Token 生成 / 其他开销，三段占比
- **上下文对比**：这次 vs 近期平均，"慢 4.8 倍 ⚠️" 这种话自动生成
- **当时 GPU 快照**：该请求发生时刻的利用率与显存

这是回答"这次为什么慢"的地方。

---

## 6. 指标字典

给要看数字的人。每个指标都写清楚"怎么算"和"什么算好"。

| 指标 | 计算方式 | 参考区间 | 说明 |
|---|---|---|---|
| **TTFT**（首字延迟） | `load_duration + prompt_eval_duration` | < 500ms 好；> 2s 偏慢 | 用户感知"卡不卡"的第一指标；冷启动含模型加载 |
| **TPOT**（每 token 耗时） | `eval_duration / eval_count` | 依赖模型与硬件 | 比平均吞吐更能反映生成速度 |
| **Tokens/s** | `eval_count / (eval_duration / 1e9)` | 7B 常见 30–60；14B 常见 15–35 | 吞吐 |
| **P50 / P95 / P99** | 对已记录响应时间求分位 | P99 与 P50 差距越大越不稳 | **P95/P99 才是申请算力的依据**，平均值会骗人 |
| **GPU 利用率** | macOS 取 llama-server/ollama 进程 CPU% 之和；Linux 取 `nvidia-smi` | < 30% 有余量；持续 > 80% 需扩容 | 判断"是不是跑满了" |
| **VRAM 占用** | macOS 取各进程 RSS 之和 | 接近物理上限要警惕 | 决定能不能再加载一个模型 |
| **Z 分数** | `(当前值 - 滚动均值) / 滚动标准差` | \|Z\| > 2 视为异常 | 脱离分布的绝对值没有意义 |
| **EMA** | `α·当前 + (1-α)·上次`，α=0.3 | — | 平滑曲线，滤掉毛刺 |
| **估算费用** | 按 `MODEL_PRICING` 每 1K token 单价累加 | — | 只是参考价，可在 `ollama-monitor-proxy.py` 里改 |

> **为什么不提供"GPU 温度 / 功耗"？** macOS 上拿不到可靠数据。Linux + NVIDIA 才有。所以跨平台默认只给能拿准的指标，不编造。

---

## 7. 接入客户端

统一规则：**把原来的 `http://localhost:11434` 换成 `http://127.0.0.1:11437`。** 只需要改这一处。

流式（`stream: true`）已支持：代理会把 Ollama 的 NDJSON 转成标准 OpenAI SSE（`data: {...}` + `data: [DONE]`），并补齐 `finish_reason` 与 `usage`，所以对客户端来说和直连官方 API 没有区别。

### 7.1 DSH（DeepSeek Harness）

编辑 `~/.dsh/profiles/desktop/cordis.patch.yml`，找到 `ollama` 这个 provider：

```yaml
      ollama:
        displayName: 本地 Ollama
        api: openai-completions
        baseURL: http://127.0.0.1:11437/v1      # ← 关键：指向代理
        headers:
          Authorization: Bearer ollama
        compat:
          supportsStore: false
          supportsDeveloperRole: false
          supportsReasoningEffort: false
          supportsStrictMode: false
        models:
          - id: qwen2.5:7b                      # ← 必须与 ollama list 完全一致
            name: Qwen2.5 7B (本地)
            contextWindow: 32768
            maxTokens: 8192
            input: [text]
            reasoningEfforts: false
          - id: qwen3:14b
            name: Qwen3 14B (本地)
            contextWindow: 40960
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}
          - id: qwen3:14b-abliterated
            name: Qwen3 14B Abliterated (本地)
            contextWindow: 40960
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}
          - id: deepseek-r1:14b
            name: DeepSeek R1 14B (本地)
            contextWindow: 131072
            maxTokens: 16384
            input: [text]
            reasoningEfforts: {off: null, high: high}
```

本地模型窗口小，还要补 `compaction-basic` 的余量，否则切换模型会报 `MODEL_SWITCH_COMPACTION_FAILED`：

```yaml
- id: compaction-basic
  name: "@deepseek-ai/dsh-compaction-basic"
  config:
    modelPolicies:
      - {provider: ollama, model: "qwen2.5:7b",            headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "qwen3:14b",             headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "qwen3:14b-abliterated", headroomTokens: 4096, maxTokens: 4096}
      - {provider: ollama, model: "deepseek-r1:14b",       headroomTokens: 4096, maxTokens: 4096}
```

改完**重启 DSH**。之后在输入框右下角的模型选择器里就能看到这四个，选哪个都会被记账。

### 7.2 Python

```python
import requests

r = requests.post(
    "http://127.0.0.1:11437/v1/chat/completions",
    headers={"Content-Type": "application/json"},
    json={
        "model": "qwen3:14b-abliterated",
        "messages": [{"role": "user", "content": "你好"}],
        "temperature": 0.7,
        "max_tokens": 512,
    },
    timeout=600,
)
print(r.json()["choices"][0]["message"]["content"])
print(r.json()["usage"])          # prompt/completion/total tokens
```

### 7.3 JavaScript

```javascript
const r = await fetch("http://127.0.0.1:11437/v1/chat/completions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "qwen2.5:7b",
    messages: [{ role: "user", content: "你好" }],
  }),
});
console.log(await r.json());
```

### 7.4 cURL

```bash
curl -X POST http://127.0.0.1:11437/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"你好"}]}'
```

### 7.5 其它客户端（WorkBuddy / Cherry Studio / Open WebUI 等）

在"模型服务 / OpenAI 兼容"里填：

- **Base URL**：`http://127.0.0.1:11437/v1`
- **API Key**：随便填（如 `ollama`），本地不校验
- **模型名**：`ollama list` 里看到的名字，四个任选

### 7.6 查看模型列表

```bash
curl -s http://127.0.0.1:11437/v1/models | python3 -m json.tool
```

---

## 8. 数据管理

### 导出

看板右上角 **导出** 按钮，或直接访问：

```bash
# 逐条明细，Excel/Numbers 可直接打开（带 BOM，中文不乱码）
curl -OJ http://127.0.0.1:11437/export?format=csv   # -J 才会用服务端的文件名

# 完整快照（累计 + 分模型 + 趋势 + GPU 时序 + 明细）
curl -OJ http://127.0.0.1:11437/export?format=json
```

CSV 列：`id, timestamp, model, endpoint, prompt_tokens, completion_tokens, total_tokens, response_time_ms, ttft_ms, time_per_token_ms, tokens_per_second, success, error_message, client_ip`

### 清零（开始新一轮统计）

看板右上角 **清除** 按钮 → 确认。会清空请求记录、趋势、GPU 采样，累计值归零。

**这是不可恢复删除。** 要留档请先导出。

应用场景：做了一轮"四模型并发"实验，想单独测下一轮，就先导出再清除，两轮数据互不污染。

### 直接查库

```bash
sqlite3 ollama_metrics.db "SELECT model, COUNT(*), SUM(total_tokens) FROM request_logs GROUP BY model;"
```

---

## 9. 公网分享

### ngrok（默认，适合临时分享）

1. 注册 [ngrok](https://dashboard.ngrok.com)，拿到 authtoken
   ```bash
   ngrok config add-authtoken <你的 token>
   ```
2. 在 Dashboard 的 Domains 页面申请一个免费固定域名，填进 `config.env` 的 `NGROK_DOMAIN`
3. `./install.sh`

分享地址：`https://<你的域名>/dashboard.html`

首次用浏览器打开可能弹 ngrok 提示页，点 **Visit Site** 即可。用代码调用公网 API 时加 header `ngrok-skip-browser-warning: true`。

### 局域网（最快，同 WiFi）

```bash
ipconfig getifaddr en0          # 会输出你的局域网 IP
```

朋友访问 `http://<你的局域网IP>:11437/dashboard.html`。零配置、零延迟、不经过任何第三方。

### Cloudflare Tunnel（长期稳定，备选）

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:11437
```

会打印一个 `https://xxx.trycloudflare.com` 地址。**注意：快速隧道每次重启换 URL**；想固定 URL 需要自有域名接入 Cloudflare。

### 安全提示

默认启用访问口令（`ACCESS_CODE`）：

- **看板**：未登录访问会被重定向到登录页，输入口令后得到一个有效 30 天的 cookie。
- **API**：请求头带 `Authorization: Bearer <口令>` 才能调用；否则返回 401。
- **本机直连**（127.0.0.1，不经隧道）免口令，方便 DSH / 本地脚本。
- 口令就写在看板「接入指引」页里，登录后可一键复制，不用另外分发。

> 口令是共享的、无用户体系：知道口令的人都能进、都能调。要撤销就改 `config.env` 里的 `ACCESS_CODE` 再重启，所有人需重新输入。

如果不想要这层保护，把 `ACCESS_CODE` 留空即可恢复开放访问（不建议公网使用）。

- 给 ngrok 加 OAuth / IP 白名单（付费功能）
- 或只用局域网分享
- 或定期换域名

已经内置的两道边界：

- **导出与清除仅限本机**。公网打开时这两个按钮不显示；直接调 `/export`、`/reset` 会返回 403。
- **不挂载项目目录**。早期版本用 StaticFiles 挂载整个目录，`/static/ollama_metrics.db` 能被公网直接下载，现已移除，只单独提供 `/dashboard.html`。

---

## 10. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 看板右上角显示 `HTTP 404` | Proxy 没起来，或隧道指向了错的端口 | `./start-monitor.sh restart`；确认 `curl localhost:11437/health` 有输出 |
| 看板有页面但数字不涨 | 客户端还在连 11434，绕过了代理 | 检查客户端 Base URL 是否为 `127.0.0.1:11437` |
| DSH 报 `Connection error` | 代理挂了 / 端口写错 | `./start-monitor.sh` 看三行状态是否全绿 |
| DSH 报 `400 Value looks like object, but can't find closing '}'` | 旧版本代理读请求体被截断（已修） | 升级到本版本，或确认 proxy 已重启 |
| 请求全是 `unknown` | 上游报错且代理拿不到模型名（旧版本） | 本版本会用请求体里的 model 回填，升级即可 |
| 一堆 600 秒的超时记录 | 多模型并发排队超过 10 分钟 | 已自动折叠；想真正解决就减少并发或加显存 |
| GPU 图是一条直线 | macOS 没拿到 nvidia-smi，用进程 CPU% 近似 | 属正常，见"指标字典"说明 |
| 切模型时 DSH 报 `MODEL_SWITCH_COMPACTION_FAILED` | 本地窗口小，压缩余量算成负数 | 补 `compaction-basic` 的 modelPolicies（见 7.1） |
| ngrok 域名打不开 | 免费隧道掉线 / 域名被回收 | `./start-monitor.sh restart`；或到 ngrok Dashboard 看 Tunnels |

日志位置（权限 600，仅当前用户可读）：

```bash
~/Library/Logs/ollama-monitor/proxy.log        # 转发与错误
~/Library/Logs/ollama-monitor/proxy.err.log    # Python 异常栈
~/Library/Logs/ollama-monitor/ngrok.log        # 隧道
./start-monitor.sh logs                        # 跟踪
```

---

## 11. 卸载

```bash
./uninstall.sh            # 停服务、移除开机自启，保留数据库
./uninstall.sh --purge    # 连数据库和日志一起删
```

Ollama 本身不受影响。

---

## 12. 文件清单

| 文件 | 作用 |
|---|---|
| `install.sh` | 一键安装：查环境、装依赖、生成开机自启、自检 |
| `uninstall.sh` | 卸载 |
| `start-monitor.sh` | 日常运维：`status` / `restart` / `logs` |
| `ollama-monitor-proxy.py` | 核心：转发 + 记账 + Dashboard 服务 + OpenAI 兼容层 + 导出 |
| `dashboard.html` | 看板页面（无构建） |
| `chart.umd.min.js` | Chart.js 本地副本，由代理 `/chart.js` 提供，不依赖 CDN |
| `config.env` | 你的配置（安装时从 `config.env.example` 生成） |
| `config.env.example` | 配置模板 |
| `ollama_metrics.db` | SQLite 数据（自动创建） |

技术栈：Python 3 + FastAPI + SQLite + Chart.js（本地副本）。**没有 Node 构建，没有 Docker，没有外部数据库，不依赖 CDN。**

---

## 13. 已知限制

1. **macOS 拿不到真实 GPU 硬件指标**（利用率/温度/功耗）。当前用 llama-server 进程 CPU% + RSS 近似。Linux + NVIDIA 会走 `nvidia-smi` 拿准确值。
2. **流式请求的耗时统计是"整段完成时间"**，不是逐 token 时间线。TTFT 可从 `prompt_eval_duration` 精确算出，但首 token 到末 token 的实时曲线没有。
3. **并发超过 GPU 承载时会排队**，表现为单请求耗时暴涨、部分请求超时。这是 Ollama 本身行为，Proxy 只如实记录（并把纯超时噪声折叠掉）。
4. **费用是估算**，单价写在 `MODEL_PRICING` 里，不是真实账单。
5. **公网只读**，没有鉴权。分享范围请自行控制。

---

## 14. 一分钟验收清单

装完想确认"真的能用了"，跑这四条：

```bash
# 1. 三个组件都在
./start-monitor.sh

# 2. 代理健康
curl -s http://localhost:11437/health

# 3. 四个模型都认得
curl -s http://localhost:11437/v1/models | python3 -c "import sys,json;print([m['id'] for m in json.load(sys.stdin)['data']])"

# 4. 发一次请求，然后看是否入账
curl -s -X POST http://localhost:11437/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"hi"}],"max_tokens":8}' >/dev/null
curl -s http://localhost:11437/metrics | python3 -c "import sys,json;d=json.load(sys.stdin);print('入账请求数:',d['cumulative']['total_requests'])"
```

四条都通过，就可以正常用了。
