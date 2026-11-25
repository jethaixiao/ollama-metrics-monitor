#!/usr/bin/env python3
"""白盒测试：直接 import proxy 模块，测内部函数逻辑。

用法: python3 tests/test_whitebox.py
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# import 前先固定测试环境变量（避免读到真实 config 之外的副作用也无妨，只读不写）
import importlib.util

spec = importlib.util.spec_from_file_location(
    "proxy", Path(__file__).resolve().parent.parent / "ollama-monitor-proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


print("== 1. _parse_library_page（用真实抓取的 ollama.com/library HTML）==")
sample = Path("/tmp/ollama_lib.html")
if sample.is_file():
    models = proxy._parse_library_page(sample.read_text(), limit=100)
    check("解析出 >10 个模型", len(models) > 10, f"实际 {len(models)}")
    names = [m["name"] for m in models]
    check("包含 gpt-oss", "gpt-oss" in names)
    check("包含 deepseek-r1", "deepseek-r1" in names)
    gpt = next((m for m in models if m["name"] == "gpt-oss"), None)
    check("gpt-oss 描述非空", bool(gpt and gpt["description"]))
    check("gpt-oss 有参数量标签(20b)", bool(gpt and any("20b" in s for s in gpt["sizes"])))
    check("gpt-oss 有能力标签(tools)", bool(gpt and "tools" in gpt["capabilities"]))
    check("gpt-oss pulls 非空", bool(gpt and gpt["pulls"]))
    check("limit=3 生效", len(proxy._parse_library_page(sample.read_text(), limit=3)) == 3)
    check("名称全部符合 [a-z0-9._-]",
          all(__import__("re").fullmatch(r"[a-z0-9][a-z0-9._-]*", m["name"]) for m in models))
else:
    print("  ⚠️ 跳过：/tmp/ollama_lib.html 不存在（先 curl 抓一次）")

print("== 1b. _parse_library_page（ollama.com/search?q=qwen 结果页，结构不同）==")
sample2 = Path("/tmp/ollama_search.html")
if sample2.is_file():
    models2 = proxy._parse_library_page(sample2.read_text(), limit=100)
    check("搜索页解析出 ≥10 个模型", len(models2) >= 10, f"实际 {len(models2)}")
    names2 = [m["name"] for m in models2]
    check("结果含 qwen3.8", "qwen3.8" in names2)
    # 解析层保留页面全部条目（含底部「相关推荐」）；关键词过滤由 API 层负责（黑盒覆盖）
    check("条目 ≥15（含相关推荐）", len(names2) >= 15)
    check("主流 qwen 系全部解析到",
          {"qwen3.8", "qwen3", "qwen2.5"} <= set(names2))
    q = next((m for m in models2 if m["name"] == "qwen3.8"), None)
    check("qwen3.8 描述非空", bool(q and q["description"]))
    check("qwen3.8 有能力标签(vision)", bool(q and "vision" in q["capabilities"]))
    check("qwen3.8 pulls 非空", bool(q and q["pulls"]))
    check("qwen3.8 updated 非空", bool(q and q["updated"]))
else:
    print("  ⚠️ 跳过：/tmp/ollama_search.html 不存在")

print("== 2. _evaluate_compat 边界值（Apple Silicon, 48GB）==")
specs = {"is_apple_silicon": True, "memory_total": 48 * 1024**3,
         "memory_available": 20 * 1024**3, "disk_free": 500 * 1024**3}
GB = 1024**3
r = proxy._evaluate_compat(30 * GB, specs)   # 30GB / 48GB ≈ 62.5% < 65%
check("30GB → ok", r["verdict"] == "ok", r["label"])
r = proxy._evaluate_compat(42 * GB, specs)   # 42/48 = 87.5% > 85%
check("42GB → no", r["verdict"] == "no", r["label"])
r = proxy._evaluate_compat(39 * GB, specs)   # 39/48 = 81% ∈ (65,85]
check("39GB → tight", r["verdict"] == "tight", r["label"])
r = proxy._evaluate_compat(10 * GB, {**specs, "disk_free": 5 * GB})
check("磁盘不足 → no_disk", r["verdict"] == "no_disk", r["label"])
r = proxy._evaluate_compat(8 * GB, {"is_apple_silicon": False, "memory_total": 16 * GB,
                                     "memory_available": 12 * GB, "disk_free": 100 * GB})
check("x86 + 12GB 可用 + 8GB 模型 → ok", r["verdict"] == "ok", r["label"])
r = proxy._evaluate_compat(8 * GB, {"is_apple_silicon": False, "memory_total": 8 * GB,
                                     "memory_available": 2 * GB, "disk_free": 100 * GB})
check("x86 内存超限 → no", r["verdict"] == "no", r["label"])
r = proxy._evaluate_compat(8 * GB, {"is_apple_silicon": False, "memory_total": None,
                                     "memory_available": None, "disk_free": None})
check("无内存信息 → unknown", r["verdict"] == "unknown", r["label"])

print("== 3. _registry_manifest_size（真实网络）==")
size = proxy._registry_manifest_size("qwen2.5", "0.5b")
check("qwen2.5:0.5b 大小在 0.2~2GB", bool(size and 0.2 * GB < size < 2 * GB), f"{size and size/GB:.2f} GB")
check("不存在模型返回 None", proxy._registry_manifest_size("no-such-model-xyz", "latest") is None)

print("== 4. system_specs 结构 ==")
s = proxy.system_specs()
check("有 cpu 字段", bool(s.get("cpu")))
check("有 memory_total", bool(s.get("memory_total")))
check("memory_total ≈ 物理内存（40~64GB 合理区间）",
      40 * GB < s["memory_total"] < 64 * GB, f"{s['memory_total']/GB:.1f}GB")
check("memory_available < memory_total", s["memory_available"] < s["memory_total"])
check("disk_free > 0", s["disk_free"] > 0)
check("ollama_models_size > 0", s["ollama_models_size"] > 0)
s2 = proxy.system_specs()
check("specs 缓存生效（两次引用一致）", s is s2)

print("== 5. _is_local_request / _is_same_origin ==")
def fake_req(headers=None, client="1.2.3.4"):
    return types.SimpleNamespace(headers=headers or {}, client=types.SimpleNamespace(host=client))
check("本机 127.0.0.1 → True", proxy._is_local_request(fake_req(client="127.0.0.1")))
check("带 X-Forwarded-For → False", not proxy._is_local_request(
    fake_req(headers={"x-forwarded-for": "1.2.3.4"}, client="127.0.0.1")))
check("外网 IP → False", not proxy._is_local_request(fake_req(client="203.0.113.9")))
ok_req = fake_req(headers={"origin": "https://x.ngrok-free.dev", "host": "x.ngrok-free.dev"})
check("Origin 与 Host 一致 → True", proxy._is_same_origin(ok_req))
bad_req = fake_req(headers={"origin": "https://evil.com", "host": "x.ngrok-free.dev"})
check("跨站 Origin → False", not proxy._is_same_origin(bad_req))
no_origin = fake_req(headers={})
check("无 Origin → True（curl/API 等非浏览器场景放行，浏览器跨站必带 Origin）",
      proxy._is_same_origin(no_origin))

print()
print(f"白盒结果: {len(PASS)} 通过, {len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
