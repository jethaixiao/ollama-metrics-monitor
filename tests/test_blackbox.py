#!/usr/bin/env python3
"""黑盒冒烟测试：对运行中的 proxy 做端到端请求验证。

用法: python3 tests/test_blackbox.py  [base_url]   # 默认 http://127.0.0.1:11437
注意：加载/卸载真实模型属有副作用操作，用 qwen2.5:7b（小）且测完恢复原状。
"""
import json
import os
import sys
import urllib.request
import urllib.error

# 本地服务直连：禁用 shell 环境里的 HTTP 代理，避免代理不稳造成误报
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(k, None)
os.environ["no_proxy"] = "*"

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11437"
PASS, FAIL = [], []


def req(path, method="GET", body=None, headers=None, timeout=60):
    r = urllib.request.Request(BASE + path, method=method,
                               headers=headers or {},
                               data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


print("== 1. 基础端点 ==")
st, raw = req("/health")
check("/health 200", st == 200, str(st))
st, raw = req("/dashboard.html")
check("/dashboard.html 200", st == 200)
html = raw.decode()
check("注入 __AGENT_PORT__", "__AGENT_PORT__" not in html)
check("注入 __PUBLIC_HOST__（ngrok 域名已填）", "__PUBLIC_HOST__" not in html)
check("页面含 hostSwitch 容器", 'id="hostSwitch"' in html)
check("页面含 renderHostSwitch", "renderHostSwitch" in html)
check("页面含「切换本地」文案", "切换本地" in html)
check("页面含「切换公网」文案", "切换公网" in html)
check("无残留 __LOCAL_BASE__ 占位符", "__LOCAL_BASE__" not in html)

print("== 2. 监控指标 ==")
st, raw = req("/metrics")
d = jload(raw)
check("/metrics 200 + 有 by_model", st == 200 and "by_model" in d)
check("available_models ≥1", len(d.get("available_models", [])) >= 1)
check("running_models 是列表", isinstance(d.get("running_models"), list))

print("== 3. Ollama 代理 ==")
st, raw = req("/api/tags")
check("/api/tags 有模型", st == 200 and len(jload(raw).get("models", [])) >= 1)
st, raw = req("/api/ps")
check("/api/ps 200", st == 200)

print("== 4. 模型管理端点 ==")
st, raw = req("/api/system/specs")
d = jload(raw)
check("/api/system/specs 200 + cpu", st == 200 and bool(d.get("cpu")))

st, raw = req("/api/models/search?limit=5")
d = jload(raw)
check("/api/models/search 200", st == 200)
check("搜索返回 5 个模型", len(d.get("models", [])) == 5)

st, raw = req("/api/models/search?q=qwen")
d = jload(raw)
check("关键词搜索 qwen 有结果", st == 200 and len(d.get("models", [])) >= 1)

print("== 4b. Hugging Face 源 ==")
st, raw = req("/api/models/search?source=hf&limit=5")
d = jload(raw)
check("HF 热门 200", st == 200, str(st))
hf_models = d.get("models", [])
check("HF 返回 5 个模型", len(hf_models) == 5)
check("HF 名字带 hf.co/ 前缀", all(m["name"].startswith("hf.co/") for m in hf_models))
check("HF 有 downloads 数据", all(m.get("pulls") for m in hf_models))

st, raw = req("/api/models/search?source=hf&q=qwen&limit=5")
d = jload(raw)
check("HF 关键词搜索 qwen 有结果", st == 200 and len(d.get("models", [])) >= 1)

st, raw = req("/api/models/compat?name=hf.co/unsloth/Qwen3-0.6B-GGUF")
d = jload(raw)
check("HF compat 200", st == 200, raw[:200].decode(errors="replace"))
check("HF compat 默认量化（Q4_K_M 优先）", d.get("model", "").count(":") == 1, d.get("model", ""))
check("HF compat 返回 quants 列表", isinstance(d.get("quants"), list) and len(d["quants"]) >= 2)
check("HF compat size_gb 合理(0.2~2)", 0.2 < d.get("size_gb", 0) < 2, str(d.get("size_gb")))
check("HF compat verdict 有效", d.get("verdict") in ("ok", "tight", "no", "no_disk", "unknown"))

st, raw = req("/api/models/compat?name=hf.co/no-such-repo-xyz-abc/GGUF")
check("HF compat 不存在仓库 → 404", st == 404, str(st))

st, raw = req("/api/models/compat?name=qwen2.5:0.5b")
d = jload(raw)
check("/api/models/compat 200", st == 200)
check("compat 有 verdict", d.get("verdict") in ("ok", "tight", "no", "no_disk", "unknown"))
check("compat size_gb > 0", d.get("size_gb", 0) > 0)

st, raw = req("/api/models/compat?name=no-such-model-xyz:latest")
check("compat 不存在模型 → 404", st == 404, str(st))

# 参数校验分支
st, _ = req("/api/models/pull", method="POST", body={})
check("pull 缺 name → 400", st == 400, str(st))
st, _ = req("/api/models/remove", method="POST", body={})
check("remove 缺 name → 400", st == 400, str(st))
st, _ = req("/api/models/pull", method="POST", body={"name": "x"},
            headers={"Content-Type": "application/json", "X-Model-Control": "1"})
# 本机直连允许；Ollama 对不存在模型报错是流式的（200 + error 行）或 404
check("pull 不存在模型不被 403 拒（鉴权通过）", st in (200, 404), str(st))

print("== 5. 模型驻留（加载 → 验证 → 卸载 → 恢复，真实副作用）==")
tags = jload(req("/api/tags")[1]).get("models", [])
target = next((m["model"] for m in tags if m["model"].startswith("qwen2.5:7b")), None)
if not target:
    target = next((m["model"] for m in tags if "0.5b" in m["model"] or "7b" in m["model"]), None)
if target:
    st, raw = req("/api/model-residency", method="POST",
                  body={"model": target, "enabled": True},
                  headers={"Content-Type": "application/json", "X-Model-Control": "1"})
    check(f"加载 {target} → 200", st == 200, raw[:120].decode(errors="replace"))
    ps = jload(req("/api/ps")[1]).get("models", [])
    check("加载后出现在 /api/ps", any(m["model"] == target for m in ps))
    st, raw = req("/api/model-residency", method="POST",
                  body={"model": target, "enabled": False},
                  headers={"Content-Type": "application/json", "X-Model-Control": "1"})
    check(f"卸载 {target} → 200", st == 200)
    ps = jload(req("/api/ps")[1]).get("models", [])
    check("卸载后不在 /api/ps", not any(m["model"] == target for m in ps))
else:
    print("  ⚠️ 跳过驻留测试：无可用小模型")

print("== 6. 安全边界（伪造公网请求无法做到，此处验证本机白名单逻辑由白盒覆盖）==")
st, raw = req("/api/model-residency", method="POST", body={"model": "x", "enabled": False},
              headers={"Content-Type": "application/json"})
check("缺 X-Model-Control 头 → 403", st == 403, str(st))

print()
print(f"黑盒结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
