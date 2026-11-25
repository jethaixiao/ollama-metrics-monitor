#!/usr/bin/env python3
"""
Ollama Metrics Proxy - 拦截 Ollama API 调用并记录指标到 SQLite
功能：
1. 代理所有 Ollama API 请求
2. 自动解析响应中的 Token 统计信息
3. 记录每次调用的详细指标到 SQLite
4. 提供 /metrics 端点供 Dashboard 查询
5. 支持 ngrok 公网分享
"""

import json
import time
import sqlite3
import asyncio
import logging
import threading
import subprocess
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
import os
import sys
import hmac
import hashlib

# ==================== 配置 ====================
# 全部可通过环境变量覆盖；install.sh 生成的 config.env 会被 launchd 注入。
_HERE = Path(__file__).resolve().parent


def _load_env_file(path: Path) -> None:
    """读取 config.env。

    与 install.sh / start-monitor.sh 的 shell 解析保持一致：
    支持 export 前缀、行尾注释、成对引号、CRLF。
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.replace("\r", "").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        # 去掉行尾注释（引号内的 # 保留）
        if v and v[0] in "\"'":
            q = v[0]
            end = v.find(q, 1)
            v = v[1:end] if end > 0 else v[1:]
        else:
            v = v.split(" #")[0].split("\t#")[0].strip()
        if k:
            os.environ.setdefault(k, v)


_load_env_file(_HERE / "config.env")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "11437"))
DB_PATH = os.environ.get("DB_PATH") or str(_HERE / "ollama_metrics.db")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# 默认只监听本机：ngrok 从 127.0.0.1 转发即可，无需暴露到局域网
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(8 * 1024 * 1024)))  # 8MB
# 访问口令：留空 = 不启用鉴权（保持旧的开放行为）
ACCESS_CODE = os.environ.get("ACCESS_CODE", "").strip()

# 模型定价参考（每 1K tokens，人民币）
MODEL_PRICING = {
    "qwen3": {"prompt": 0.002, "completion": 0.006},
    "qwen2.5": {"prompt": 0.002, "completion": 0.006},
    "llama3": {"prompt": 0.003, "completion": 0.009},
    "llama2": {"prompt": 0.002, "completion": 0.006},
    "mistral": {"prompt": 0.002, "completion": 0.006},
    "gemma": {"prompt": 0.001, "completion": 0.003},
    "default": {"prompt": 0.002, "completion": 0.006},
}

# ==================== 日志配置 ====================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ==================== 数据库管理 ====================
class MetricsDB:
    """SQLite 数据库管理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()
    
    def _get_conn(self):
        # timeout: 并发写时等待而不是立刻抛 "database is locked"
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        # WAL 让读不阻塞写（GPU 采集线程与请求线程同时在写）
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        return conn
    
    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 键值元信息（记录当前指标口径等）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)
        """)

        # 请求日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                response_time_ms REAL NOT NULL,
                ttft_ms REAL DEFAULT 0,
                time_per_token_ms REAL DEFAULT 0,
                tokens_per_second REAL DEFAULT 0,
                success BOOLEAN NOT NULL DEFAULT 1,
                error_message TEXT,
                client_ip TEXT,
                created_at TEXT NOT NULL,
                load_ms REAL DEFAULT 0,
                prompt_eval_ms REAL DEFAULT 0,
                eval_ms REAL DEFAULT 0,
                total_ms REAL DEFAULT 0
            )
        """)

        # 老库补列（幂等）
        for col in ("load_ms", "prompt_eval_ms", "eval_ms", "total_ms"):
            try:
                cursor.execute(f"ALTER TABLE request_logs ADD COLUMN {col} REAL DEFAULT 0")
            except Exception:
                pass
        
        # GPU 资源监控表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gpu_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                gpu_utilization_pct REAL DEFAULT 0,
                vram_used_bytes INTEGER DEFAULT 0,
                vram_total_bytes INTEGER DEFAULT 0,
                temperature_celsius INTEGER DEFAULT 0,
                power_draw_watts REAL DEFAULT 0,
                rolling_mean REAL DEFAULT 0,
                rolling_stddev REAL DEFAULT 0,
                z_score REAL DEFAULT 0,
                ema_utilization REAL DEFAULT 0
            )
        """)
        
        # 累积统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cumulative_stats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_requests INTEGER NOT NULL DEFAULT 0,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                total_response_time_ms REAL NOT NULL DEFAULT 0,
                total_errors INTEGER NOT NULL DEFAULT 0,
                first_request_at TEXT,
                last_request_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        
        # 初始化累积统计行
        cursor.execute("""
            INSERT OR IGNORE INTO cumulative_stats (id, updated_at)
            VALUES (1, ?)
        """, (datetime.now(timezone.utc).isoformat(),))
        
        # 5分钟级聚合表（用于微观趋势图）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS five_min_stats (
                window_start TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL DEFAULT 0,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                avg_response_time_ms REAL NOT NULL DEFAULT 0,
                avg_tokens_per_second REAL NOT NULL DEFAULT 0,
                max_response_time_ms REAL NOT NULL DEFAULT 0,
                p95_response_time_ms REAL NOT NULL DEFAULT 0
            )
        """)
        
        # 小时级聚合表（保留用于宏观统计）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hourly_stats (
                hour TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL DEFAULT 0,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                avg_response_time_ms REAL NOT NULL DEFAULT 0,
                avg_tokens_per_second REAL NOT NULL DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()

        # 数据库含客户端 IP 与请求内容，只允许当前用户读写
        try:
            os.chmod(self.db_path, 0o600)
        except Exception:
            pass
        logger.info(f"数据库初始化完成: {self.db_path}")
    
    def log_request(self, record: dict):
        """记录单次请求。任何 DB 异常都不应影响已经完成的响应。"""
        conn = self._get_conn()
        try:
            self._log_request_inner(conn, record)
        except Exception as e:
            logger.warning("写统计失败（不影响响应）: %s", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _log_request_inner(self, conn, record: dict):
        cursor = conn.cursor()
        
        now = datetime.now(timezone.utc).isoformat()
        
        # 插入请求日志
        cursor.execute("""
            INSERT INTO request_logs 
            (timestamp, model, endpoint, prompt_tokens, completion_tokens,
             total_tokens, response_time_ms, ttft_ms, time_per_token_ms, tokens_per_second,
             success, error_message, client_ip, created_at,
             load_ms, prompt_eval_ms, eval_ms, total_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get("timestamp", now),
            record["model"],
            record.get("endpoint", "/api/chat"),
            record.get("prompt_tokens", 0),
            record.get("completion_tokens", 0),
            record.get("total_tokens", 0),
            record["response_time_ms"],
            record.get("ttft_ms", 0),
            record.get("time_per_token_ms", 0),
            record.get("tokens_per_second", 0),
            record.get("success", True),
            record.get("error_message"),
            record.get("client_ip", "127.0.0.1"),
            now,
            record.get("load_ms", 0),
            record.get("prompt_eval_ms", 0),
            record.get("eval_ms", 0),
            record.get("total_ms", 0),
        ))
        
        # 更新累积统计
        if record.get("success", True):
            cursor.execute("""
                UPDATE cumulative_stats SET
                    total_requests = total_requests + 1,
                    total_prompt_tokens = total_prompt_tokens + ?,
                    total_completion_tokens = total_completion_tokens + ?,
                    total_tokens = total_tokens + ?,
                    total_response_time_ms = total_response_time_ms + ?,
                    last_request_at = ?,
                    updated_at = ?
                WHERE id = 1
            """, (
                record.get("prompt_tokens", 0),
                record.get("completion_tokens", 0),
                record.get("total_tokens", 0),
                record["response_time_ms"],
                now,
                now,
            ))
            
            # 更新 first_request_at（仅首次）
            cursor.execute("""
                UPDATE cumulative_stats SET
                    first_request_at = COALESCE(first_request_at, ?)
                WHERE id = 1 AND first_request_at IS NULL
            """, (now,))
        else:
            cursor.execute("""
                UPDATE cumulative_stats SET
                    total_requests = total_requests + 1,
                    total_errors = total_errors + 1,
                    last_request_at = ?,
                    updated_at = ?
                WHERE id = 1
            """, (now, now))
        
        # 更新小时级聚合
        hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:00")
        cursor.execute("""
            INSERT INTO hourly_stats (hour, request_count, total_prompt_tokens, 
                                      total_completion_tokens, avg_response_time_ms,
                                      avg_tokens_per_second)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(hour) DO UPDATE SET
                request_count = request_count + 1,
                total_prompt_tokens = total_prompt_tokens + ?,
                total_completion_tokens = total_completion_tokens + ?,
                avg_response_time_ms = (avg_response_time_ms * request_count + ?) / (request_count + 1),
                avg_tokens_per_second = (avg_tokens_per_second * request_count + ?) / (request_count + 1)
        """, (
            hour_key,
            record.get("prompt_tokens", 0),
            record.get("completion_tokens", 0),
            record["response_time_ms"],
            record.get("tokens_per_second", 0),
            record.get("prompt_tokens", 0),
            record.get("completion_tokens", 0),
            record["response_time_ms"],
            record.get("tokens_per_second", 0),
        ))
        
        # 更新 5 分钟级聚合（实时更新当前窗口，不等窗口结束）
        now_dt = datetime.now(timezone.utc)
        five_min_key = now_dt.strftime("%Y-%m-%d %H:") + f"{(now_dt.minute // 5) * 5:02d}"
        
        cursor.execute("SELECT request_count, max_response_time_ms, p95_response_time_ms FROM five_min_stats WHERE window_start = ?", (five_min_key,))
        existing = cursor.fetchone()
        
        if existing:
            old_count = existing[0]
            old_max = existing[1] or 0
            old_p95 = existing[2] or 0
            new_max = max(old_max, record["response_time_ms"])
            # 该窗口目前没有保留样本，只能用最大值代表上界；
            # 前端应把它当作"窗口峰值"而不是统计意义上的 P95。
            new_p95 = new_max
            
            cursor.execute("""
                UPDATE five_min_stats SET
                    request_count = request_count + 1,
                    total_prompt_tokens = total_prompt_tokens + ?,
                    total_completion_tokens = total_completion_tokens + ?,
                    avg_response_time_ms = (avg_response_time_ms * ? + ?) / ?,
                    avg_tokens_per_second = (avg_tokens_per_second * ? + ?) / ?,
                    max_response_time_ms = ?,
                    p95_response_time_ms = ?
                WHERE window_start = ?
            """, (
                record.get("prompt_tokens", 0),
                record.get("completion_tokens", 0),
                old_count, record["response_time_ms"], old_count + 1,
                old_count, record.get("tokens_per_second", 0), old_count + 1,
                new_max, new_p95, five_min_key,
            ))
        else:
            cursor.execute("""
                INSERT INTO five_min_stats (window_start, request_count, total_prompt_tokens,
                                            total_completion_tokens, avg_response_time_ms,
                                            avg_tokens_per_second, max_response_time_ms,
                                            p95_response_time_ms)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?)
            """, (
                five_min_key,
                record.get("prompt_tokens", 0),
                record.get("completion_tokens", 0),
                record["response_time_ms"],
                record.get("tokens_per_second", 0),
                record["response_time_ms"],
                record["response_time_ms"],
            ))
        
        # 清理超过 24 小时的 5 分钟级数据
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        cursor.execute("DELETE FROM five_min_stats WHERE window_start < ?", (cutoff,))

        conn.commit()
        # 连接由外层 log_request 的 finally 关闭

    def get_cumulative_stats(self) -> dict:
        """获取累积统计"""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM cumulative_stats WHERE id = 1").fetchone()
        conn.close()
        
        if not row:
            return {}
        
        stats = dict(row)
        
        # 计算平均值
        if stats["total_requests"] > 0:
            stats["avg_response_time_ms"] = round(
                stats["total_response_time_ms"] / stats["total_requests"], 2
            )
            stats["avg_tokens_per_request"] = round(
                stats["total_tokens"] / stats["total_requests"], 2
            )
        else:
            stats["avg_response_time_ms"] = 0
            stats["avg_tokens_per_request"] = 0
        
        # 计算费用估算
        stats["estimated_cost_cny"] = self._calculate_cost(stats)
        
        return stats
    
    def _calculate_cost(self, stats: dict) -> float:
        """估算费用（简化版，使用默认价格）"""
        pricing = MODEL_PRICING["default"]
        prompt_cost = (stats.get("total_prompt_tokens", 0) / 1000) * pricing["prompt"]
        completion_cost = (stats.get("total_completion_tokens", 0) / 1000) * pricing["completion"]
        return round(prompt_cost + completion_cost, 4)
    
    def get_recent_requests(self, limit: int = 50) -> list:
        """获取最近的请求记录"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM request_logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_hourly_stats(self, hours: int = 24) -> list:
        """获取最近 N 小时的小时级统计"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM hourly_stats ORDER BY hour DESC LIMIT ?", (hours,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]  # 正序返回

    def get_five_min_stats(self, minutes: int = 120) -> list:
        """获取最近 N 分钟的 5 分钟级统计（默认 120 分钟 = 2 小时）"""
        conn = self._get_conn()
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        rows = conn.execute(
            "SELECT * FROM five_min_stats WHERE window_start >= ? ORDER BY window_start",
            (cutoff,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    
    def get_model_stats(self) -> list:
        """按模型分组的统计"""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT 
                model,
                COUNT(*) as request_count,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens,
                AVG(response_time_ms) as avg_response_time_ms,
                AVG(tokens_per_second) as avg_tokens_per_second
            FROM request_logs
            WHERE success = 1
              AND model IS NOT NULL AND model <> '' AND model <> 'unknown'
            GROUP BY model
            ORDER BY request_count DESC
        """).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def check_gpu_source(self, source: str) -> bool:
        """口径（ioreg 真实计数器 / cpu 近似）变化时清空历史，返回是否清理过"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT v FROM meta WHERE k='gpu_source'").fetchone()
            prev = row["v"] if row else None
            if prev != source:
                if prev is not None:
                    conn.execute("DELETE FROM gpu_stats")
                    logger.warning("GPU 指标口径由 %s 切换为 %s，已清空旧基线", prev, source)
                conn.execute("INSERT INTO meta(k,v) VALUES('gpu_source',?) "
                             "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (source,))
                conn.commit()
                return prev is not None
            return False
        finally:
            conn.close()

    def save_gpu_stat(self, stat: dict):
        """保存 GPU 资源快照，并维护滚动统计窗口"""
        conn = self._get_conn()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        
        # 获取最近 24 个窗口（2小时）用于计算滚动基线
        cutoff = (now - timedelta(hours=2)).isoformat()
        # 用最近 30 分钟（360 个 5 秒采样）作为统计基线，与看板文案一致
        recent = conn.execute(
            "SELECT gpu_utilization_pct FROM gpu_stats WHERE timestamp >= ? ORDER BY id DESC LIMIT 360",
            (cutoff,)
        ).fetchall()
        
        values = [r["gpu_utilization_pct"] for r in recent]
        n = len(values)
        
        # 计算滚动基线
        if n >= 5:
            mean_val = sum(values) / n
            variance = sum((x - mean_val) ** 2 for x in values) / n
            stddev_val = variance ** 0.5
            z_score = (stat["gpu_utilization_pct"] - mean_val) / stddev_val if stddev_val > 0 else 0
        else:
            mean_val = stat["gpu_utilization_pct"]
            stddev_val = 0
            z_score = 0
        
        # 计算 EMA (α=0.3)
        ema_prev = conn.execute(
            "SELECT ema_utilization FROM gpu_stats ORDER BY id DESC LIMIT 1"
        ).fetchone()
        alpha = 0.3
        if ema_prev and ema_prev["ema_utilization"] is not None:
            ema_new = alpha * stat["gpu_utilization_pct"] + (1 - alpha) * ema_prev["ema_utilization"]
        else:
            ema_new = stat["gpu_utilization_pct"]
        
        conn.execute("""
            INSERT INTO gpu_stats (timestamp, gpu_utilization_pct, vram_used_bytes, 
                                   vram_total_bytes, temperature_celsius, power_draw_watts,
                                   rolling_mean, rolling_stddev, z_score, ema_utilization)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_iso,
            stat.get("gpu_utilization_pct", 0),
            stat.get("vram_used_bytes", 0),
            stat.get("vram_total_bytes", 0),
            stat.get("temperature_celsius", 0),
            stat.get("power_draw_watts", 0),
            round(mean_val, 2),
            round(stddev_val, 2),
            round(z_score, 2),
            round(ema_new, 2),
        ))
        
        # 清理超过 24 小时的数据
        cutoff_24h = (now - timedelta(hours=24)).isoformat()
        conn.execute("DELETE FROM gpu_stats WHERE timestamp < ?", (cutoff_24h,))
        conn.commit()
        conn.close()

    def get_recent_gpu_stats(self, limit: int = 288) -> list:
        """获取最近 N 个 GPU 快照（默认 24 小时，每 5 秒一次 = 17280，取最近 288 即 24 分钟用于图表）"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM gpu_stats ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]

    def get_latency_percentiles(self) -> dict:
        """响应时间与每 token 耗时（TPOT）的 P50 / P95 / P99。

        绝对响应时间受输出长度影响，不能直接用来判断"是否变慢"；
        TPOT 与输出长度无关，才是性能口径。
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT response_time_ms, time_per_token_ms FROM request_logs
            WHERE success = 1 AND response_time_ms > 0
            ORDER BY response_time_ms
        """).fetchall()
        conn.close()

        if not rows:
            return {"p50": 0, "p95": 0, "p99": 0, "count": 0,
                    "tpot_p50": 0, "tpot_p95": 0, "tpot_p99": 0}

        values = [r["response_time_ms"] for r in rows]
        tpot = sorted(r["time_per_token_ms"] for r in rows if (r["time_per_token_ms"] or 0) > 0)

        def percentile(data, p):
            if not data:
                return 0
            k = (len(data) - 1) * (p / 100.0)
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            d = k - f
            return data[f] + d * (data[c] - data[f])

        return {
            "p50": round(percentile(values, 50), 2),
            "p95": round(percentile(values, 95), 2),
            "p99": round(percentile(values, 99), 2),
            "tpot_p50": round(percentile(tpot, 50), 2),
            "tpot_p95": round(percentile(tpot, 95), 2),
            "tpot_p99": round(percentile(tpot, 99), 2),
            "count": len(values),
        }

    def reset_all_data(self):
        """清除所有监控数据"""
        conn = self._get_conn()
        conn.execute("DELETE FROM request_logs")
        conn.execute("DELETE FROM hourly_stats")
        conn.execute("DELETE FROM five_min_stats")
        conn.execute("DELETE FROM gpu_stats")
        # 重置累积统计
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE cumulative_stats SET
                total_requests = 0,
                total_prompt_tokens = 0,
                total_completion_tokens = 0,
                total_tokens = 0,
                total_response_time_ms = 0,
                total_errors = 0,
                first_request_at = NULL,
                last_request_at = NULL,
                updated_at = ?
            WHERE id = 1
        """, (now,))
        conn.commit()
        conn.close()
        logger.info("🗑️ 所有监控数据已清除")


# ==================== FastAPI 应用 ====================
db = MetricsDB(DB_PATH)

# 获取脚本所在目录（用于提供静态文件）
SCRIPT_DIR = Path(__file__).parent.resolve()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 Ollama Metrics Proxy 启动中...")
    logger.info(f"   后端 Ollama: {OLLAMA_BASE_URL}")
    logger.info(f"   代理端口: {PROXY_PORT}")
    logger.info(f"   数据库: {DB_PATH}")
    logger.info(f"   Dashboard: {SCRIPT_DIR}/dashboard.html")
    
    # 日志含请求路径，兜底收紧权限（launchd 重定向文件不受 Umask 影响）
    for name in ("proxy.log", "proxy.err.log"):
        f = Path.home() / "Library/Logs/ollama-monitor" / name
        try:
            if f.exists():
                os.chmod(f, 0o600)
        except Exception:
            pass

    # 口径切换检测：先探测一次，确定到底是硬件计数器还是 CPU 近似
    try:
        _collect_gpu_stats()          # 触发探测，设置 _GPU_SOURCE
        db.check_gpu_source(_GPU_SOURCE)
    except Exception as e:
        logger.warning("口径检查失败: %s", e)

    # 启动 GPU 监控后台线程
    stop_event = threading.Event()
    gpu_thread = threading.Thread(target=_gpu_monitor_loop, args=(stop_event,), daemon=True)
    gpu_thread.start()
    logger.info("   📊 GPU 监控线程已启动 (每 5 秒采集)")
    
    yield
    
    stop_event.set()
    gpu_thread.join(timeout=2)
    logger.info("👋 Ollama Metrics Proxy 已停止")


def _gpu_monitor_loop(stop_event: threading.Event):
    """后台线程：每 5 秒采集 GPU 资源数据"""
    while not stop_event.is_set():
        try:
            stat = _collect_gpu_stats()
            if stat:
                db.save_gpu_stat(stat)
        except Exception as e:
            logger.warning("GPU 监控采集失败: %s", e)
        stop_event.wait(5)


_VRAM_CACHE = {"total": 0, "at": 0.0}
_GPU_SOURCE = "cpu"      # ioreg = 真实 GPU 计数器；cpu = 进程 CPU 近似
_MEM_TOTAL_CACHE = {"bytes": 0}


def _macos_total_memory() -> int:
    """物理内存总量（统一内存架构下即 GPU 可用上限）"""
    if _MEM_TOTAL_CACHE["bytes"]:
        return _MEM_TOTAL_CACHE["bytes"]
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout
        _MEM_TOTAL_CACHE["bytes"] = int(out.strip())
    except Exception:
        _MEM_TOTAL_CACHE["bytes"] = 0
    return _MEM_TOTAL_CACHE["bytes"]


def _macos_gpu_counters():
    """从 IOAccelerator 读真实 GPU 计数器（无需 root）。

    返回 (利用率%, GPU 占用内存字节)；读不到时返回 None。
    """
    try:
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-w", "0"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        mu = re.search(r'"Device Utilization %"=(\d+)', out)
        mm = re.search(r'"In use system memory"=(\d+)', out)
        if not mu:
            return None
        return int(mu.group(1)), (int(mm.group(1)) if mm else 0)
    except Exception:
        return None
# ps 的 %cpu 是"进程生命周期平均"，长时间空闲会被稀释到 0，
# 所以改用累计 CPU 时间差：两次采样之间用掉多少 CPU 秒 ÷ 墙钟秒 = 核数当量
_LAST_CPU = {"ts": 0.0, "cpu": 0.0}


def _parse_cputime(txt: str) -> float:
    txt = txt.strip()
    try:
        parts = txt.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except Exception:
        return 0.0


def _macos_vram_total() -> int:
    """读取 GPU 显存总量。system_profiler 很慢（5~10 秒），缓存 10 分钟。"""
    now = time.time()
    if _VRAM_CACHE["total"] and now - _VRAM_CACHE["at"] < 600:
        return _VRAM_CACHE["total"]

    total = 0
    try:
        out = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        for line in out.split("\n"):
            if "VRAM" in line or "Memory" in line:
                nums = re.findall(r"([\d.]+)\s*(GB|MB|TB)", line.split(":", 1)[-1].upper())
                if nums:
                    val, unit = float(nums[0][0]), nums[0][1]
                    total = int(val * {"MB": 1, "GB": 1024, "TB": 1024 * 1024}[unit] * 1024 * 1024)
                    break
    except Exception:
        total = 0

    _VRAM_CACHE.update(total=total, at=now)
    return total


def _collect_gpu_stats() -> dict | None:
    """通过系统命令采集 GPU 数据（支持 macOS 和 Linux）"""
    import platform
    
    system = platform.system()
    
    if system == "Darwin":  # macOS
        global _GPU_SOURCE
        counters = _macos_gpu_counters()
        if counters:
            util, gpu_mem = counters
            _GPU_SOURCE = "ioreg"
            return {
                "gpu_utilization_pct": float(util),
                "vram_used_bytes": gpu_mem,
                "vram_total_bytes": _macos_total_memory(),
                "temperature_celsius": 0,
                "power_draw_watts": 0,
            }

        # 兜底：读不到硬件计数器时，用推理进程 CPU 近似
        _GPU_SOURCE = "cpu"
        try:
            vram_match = _macos_vram_total()

            # macOS 无 nvidia-smi：用推理进程的 CPU% 与 RSS 近似
            ps_all = subprocess.run(
                ["ps", "-ax", "-o", "pid,cputime,rss,command"],
                capture_output=True, text=True, timeout=5
            )

            total_cpu = 0.0
            rss_bytes = 0
            for line in ps_all.stdout.splitlines():
                # 只统计真正跑推理的进程；"ollama" 会误命中本代理自己
                if "llama-server" in line or "/ollama/ollama serve" in line or " ollama serve" in line:
                    parts = line.split(None, 3)
                    if len(parts) >= 4:
                        total_cpu += _parse_cputime(parts[1])
                        try:
                            rss_bytes += int(parts[2]) * 1024
                        except ValueError:
                            pass

            now_ts = time.time()
            dt = now_ts - _LAST_CPU["ts"]
            delta = total_cpu - _LAST_CPU["cpu"]
            # 进程重启会让 cputime 归零，delta 为负时按 0 处理
            cores_now = os.cpu_count() or 1
            if _LAST_CPU["ts"] and dt > 1 and delta > 0:
                cpu_util = min(delta / dt / cores_now * 100.0, 100.0)
            else:
                cpu_util = 0.0
            _LAST_CPU.update(ts=now_ts, cpu=total_cpu)
            
            return {
                # 已经是 0~100 的核利用率
                "gpu_utilization_pct": round(cpu_util, 1),
                "vram_used_bytes": rss_bytes,
                "vram_total_bytes": vram_match or 0,
                "temperature_celsius": 0,
                "power_draw_watts": 0,
            }
        except Exception:
            return None
    
    elif system == "Linux":
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None
            
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            
            if len(parts) < 5:
                return None
            
            return {
                "gpu_utilization_pct": float(parts[0]),
                "vram_used_bytes": int(float(parts[1]) * 1024 * 1024),
                "vram_total_bytes": int(float(parts[2]) * 1024 * 1024),
                "temperature_celsius": int(parts[3]),
                "power_draw_watts": float(parts[4]),
            }
        except FileNotFoundError:
            return None
        except Exception:
            return None
    
    return None

app = FastAPI(
    title="Ollama Metrics Proxy",
    description="拦截 Ollama API 调用并记录指标",
    version="1.0.0",
    lifespan=lifespan,
)

# 注意：不要用 StaticFiles 挂载整个目录。
# 那会把 ollama_metrics.db、config.env、源码一起暴露到公网（/static/xxx 可直接下载）。
# 看板只有一个文件，用下面的 /dashboard.html 路由单独提供即可。

@app.get("/")
async def root():
    """根路径重定向到 Dashboard"""
    return FileResponse(str(SCRIPT_DIR / "dashboard.html"))

# ==================== 访问口令 ====================
COOKIE_NAME = "mm_session"
# 由口令派生的会话值：重启不变，也无需额外存密钥
_SESSION_VALUE = (hashlib.sha256(("mm:" + ACCESS_CODE).encode()).hexdigest()
                  if ACCESS_CODE else "")
_OPEN_PATHS = {"/login", "/health", "/chart.js", "/favicon.ico"}


def _cookie_ok(request: Request) -> bool:
    if not _SESSION_VALUE:
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), _SESSION_VALUE)


def _bearer_ok(request: Request) -> bool:
    if not ACCESS_CODE:
        return True
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    return bool(token) and hmac.compare_digest(token, ACCESS_CODE)


def _authed(request: Request) -> bool:
    """本机直连 / 有效 cookie / 正确 Bearer，三者任一即可。"""
    return _is_local_request(request) or _cookie_ok(request) or _bearer_ok(request)


_LOGIN_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ollama Metrics Monitor</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F0F2F3;
     font-family:ui-sans-serif,-apple-system,"PingFang SC",sans-serif;color:#111418}
.card{background:#fff;border:1px solid #E3E6E8;border-radius:12px;padding:28px;
      width:min(90vw,340px);box-shadow:0 4px 12px -2px rgba(16,20,24,.08)}
h1{margin:0 0 4px;font-size:16px}
p{margin:0 0 20px;font-size:12.5px;color:#565E65}
input{width:100%;height:38px;padding:0 12px;font-size:14px;border:1px solid #CFD4D8;
      border-radius:6px;outline:none;font-family:ui-monospace,Menlo,monospace}
input:focus{border-color:#C2410C;box-shadow:0 0 0 3px rgba(194,65,12,.12)}
button{width:100%;height:38px;margin-top:12px;border:0;border-radius:6px;
       background:#C2410C;color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{background:#7C2A08}
button:disabled{opacity:.6;cursor:default}
.err{display:none;margin-top:12px;font-size:12.5px;color:#B42318}
.err.show{display:block}
</style></head><body>
<form class="card" id="f">
  <h1>Ollama Metrics Monitor</h1>
  <p>请输入访问口令</p>
  <input id="code" name="code" type="password" autocomplete="current-password" autofocus placeholder="访问口令">
  <button type="submit" id="btn">进入看板</button>
  <div class="err" id="err">口令不正确</div>
</form>
<script>
(function(){
  var f=document.getElementById('f'), inp=document.getElementById('code'),
      btn=document.getElementById('btn'), err=document.getElementById('err');
  if(location.search.indexOf('e=1')>=0) err.classList.add('show');
  f.addEventListener('submit', async function(ev){
    ev.preventDefault();
    var code=(inp.value||'').trim();
    if(!code){ err.textContent='请输入口令'; err.classList.add('show'); return; }
    btn.disabled=true; btn.textContent='验证中…'; err.classList.remove('show');
    try{
      var r=await fetch('/login',{method:'POST',
        headers:{'Content-Type':'application/json','X-Login':'1',
                 'ngrok-skip-browser-warning':'true'},
        body:JSON.stringify({code:code})});
      if(r.ok){ location.replace('/dashboard.html?view=usage'); return; }
      err.textContent='口令不正确，请重试';
    }catch(e){ err.textContent='网络错误，请重试'; }
    err.classList.add('show'); btn.disabled=false; btn.textContent='进入看板';
  });
})();
</script>
</body></html>"""


@app.get("/login")
async def login_page():
    return Response(content=_LOGIN_HTML, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@app.post("/login")
async def login_submit(request: Request):
    from urllib.parse import parse_qs
    raw = (await request.body()).decode("utf-8", "replace")
    code = ""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            code = (json.loads(raw or "{}").get("code") or "").strip()
        except Exception:
            code = ""
    if not code:
        code = (parse_qs(raw).get("code") or [""])[0].strip()
    is_fetch = request.headers.get("x-login") == "1"
    if not ACCESS_CODE or hmac.compare_digest(code, ACCESS_CODE):
        # 关键：不要用 303 直接跳。Safari 可能在 cookie 落盘前就发出重定向请求，
        # 导致又被打回登录页（表现为“点了没反应”）。先返回中间页，让 cookie 确定写入。
        target = "/dashboard.html?view=usage"
        page = ("<!doctype html><meta charset=utf-8><title>正在进入…</title>"
                "<style>body{font-family:-apple-system,sans-serif;background:#F0F2F3;color:#111418;"
                "display:grid;place-items:center;height:100vh;margin:0}</style>"
                f"<p>正在进入看板…</p>"
                f"<script>location.replace({target!r})</script>"
                f"<noscript><a href=\'{target}\'>点此进入</a></noscript>")
        if is_fetch:
            resp = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
        else:
            resp = Response(content=page, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})
        resp.set_cookie(COOKIE_NAME, _SESSION_VALUE, max_age=30 * 24 * 3600,
                        httponly=True, samesite="lax", path="/", secure=False)
        return resp
    if is_fetch:
        return JSONResponse(status_code=401, content={"ok": False, "error": "invalid code"})
    return RedirectResponse("/login?e=1", status_code=303)


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.middleware("http")
async def access_guard(request: Request, call_next):
    """启用口令后：页面未登录跳登录页，接口未授权返回 401。"""
    if not ACCESS_CODE:
        return await call_next(request)

    path = request.url.path
    if path in _OPEN_PATHS or _authed(request):
        return await call_next(request)

    if path.startswith("/v1") or path.startswith("/api"):
        return JSONResponse(status_code=401,
                            content={"error": "unauthorized: missing or invalid API token"})
    return RedirectResponse("/login", status_code=303)


@app.get("/chart.js")
async def serve_chartjs():
    """本地提供 Chart.js，避免 CDN 依赖。"""
    f = SCRIPT_DIR / "chart.umd.min.js"
    if not f.is_file():
        return JSONResponse(status_code=404, content={"error": "chart.umd.min.js missing"})
    return FileResponse(str(f), media_type="application/javascript")


@app.get("/dashboard.html")
async def serve_dashboard():
    """提供 Dashboard 页面，并把实际代理端口注入前端。"""
    f = SCRIPT_DIR / "dashboard.html"
    html = (f.read_text(encoding="utf-8")
            .replace("__AGENT_PORT__", str(PROXY_PORT))
            .replace("__LOCAL_BASE__", f"http://127.0.0.1:{PROXY_PORT}/v1")
            .replace("__ACCESS_CODE__", ACCESS_CODE or "（未启用）"))
    return Response(content=html, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store, must-revalidate"})


# ==================== OpenAI 兼容接口 ====================

@app.get("/v1/models")
def openai_models(request: Request):
    """OpenAI 格式的模型列表"""
    try:
        resp = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=30)
        ollama_data = resp.json()
        
        # 转换为 OpenAI 格式
        models = []
        for m in ollama_data.get("models", []):
            models.append({
                "id": m["name"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "ollama",
            })
        
        return JSONResponse({"object": "list", "data": models})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI 格式对话接口 → Ollama /api/chat。

    stream=false：返回标准 chat.completion 对象。
    stream=true ：把 Ollama 的 NDJSON 转成 OpenAI SSE（data: {...} + data: [DONE]）。
    """
    import asyncio
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"

    try:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413,
                                content={"error": f"request body too large (>{MAX_BODY_BYTES} bytes)"})
        openai_req = json.loads(body)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON: {e}"})

    model = openai_req.get("model", "")
    is_stream = bool(openai_req.get("stream", False))

    ollama_req = {
        "model": model,
        "messages": openai_req.get("messages", []),
        "stream": is_stream,
    }
    if "temperature" in openai_req:
        ollama_req["temperature"] = openai_req["temperature"]

    opts = {}
    if openai_req.get("max_completion_tokens"):
        opts["num_predict"] = openai_req["max_completion_tokens"]
    elif openai_req.get("max_tokens"):
        opts["num_predict"] = openai_req["max_tokens"]
    for src, dst in (("top_p", "top_p"), ("seed", "seed")):
        if src in openai_req and openai_req[src] is not None:
            opts[dst] = openai_req[src]
    if openai_req.get("stop"):
        opts["stop"] = openai_req["stop"]
    if opts:
        ollama_req["options"] = opts

    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "content-length", "accept-encoding")}

    # ---------- 流式 ----------
    if is_stream:
        try:
            upstream = await asyncio.to_thread(
                session.post,
                f"{OLLAMA_BASE_URL}/api/chat",
                json=ollama_req,
                headers=fwd_headers,
                timeout=600,
                stream=True,
            )
        except Exception as e:
            db.log_request({
                "model": model or "unknown", "endpoint": "chat",
                "response_time_ms": (time.time() - start_time) * 1000,
                "success": False, "error_message": f"upstream connect failed: {e}",
                "client_ip": client_ip,
            })
            return JSONResponse(status_code=502, content={"error": "upstream unreachable"})

        if upstream.status_code != 200:
            err = upstream.content
            upstream.close()
            db.log_request({
                "model": model or "unknown", "endpoint": "chat",
                "response_time_ms": (time.time() - start_time) * 1000,
                "success": False,
                "error_message": err[:300].decode("utf-8", "replace"),
                "client_ip": client_ip,
            })
            return Response(content=err, status_code=upstream.status_code,
                            media_type="application/json")

        chat_id = f"chatcmpl-{int(time.time())}"
        created = int(time.time())

        def sse(obj):
            return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

        def gen():
            emitted = 0
            done_seen = False
            try:
                for raw in upstream.iter_lines(decode_unicode=False):
                    if not raw:
                        continue
                    try:
                        chunk = json.loads(raw)
                    except Exception:
                        continue

                    if chunk.get("error"):
                        # 上游报错：如实告诉客户端，不要补 finish_reason 伪装成功
                        logger.warning("上游流式返回错误: %s", chunk["error"])
                        db.log_request({
                            "model": model or "unknown", "endpoint": "chat",
                            "response_time_ms": (time.time() - start_time) * 1000,
                            "success": False,
                            "error_message": str(chunk["error"])[:300],
                            "client_ip": client_ip,
                        })
                        yield sse({"error": {"message": str(chunk["error"]),
                                             "type": "upstream_error"}})
                        yield "data: [DONE]\n\n"
                        return

                    msg = chunk.get("message") or {}
                    content = msg.get("content") or ""
                    thinking = msg.get("thinking") or ""

                    if content or thinking:
                        delta = {}
                        if thinking:
                            delta["reasoning_content"] = thinking
                        if content:
                            delta["content"] = content
                        emitted += 1
                        yield sse({
                            "id": chat_id, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        })

                    if chunk.get("done"):
                        done_seen = True
                        metrics = _extract_metrics(raw, "chat",
                                                   (time.time() - start_time) * 1000, model)
                        metrics["client_ip"] = client_ip
                        db.log_request(metrics)

                        prompt_tok = chunk.get("prompt_eval_count", 0) or 0
                        comp_tok = chunk.get("eval_count", 0) or 0
                        yield sse({
                            "id": chat_id, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": prompt_tok,
                                      "completion_tokens": comp_tok,
                                      "total_tokens": prompt_tok + comp_tok},
                        })
                        yield "data: [DONE]\n\n"
                        return
            except Exception as e:
                logger.error(f"流式转发中断: {e}")
            finally:
                upstream.close()

            # 上游提前结束或异常：仍然给出明确的收尾，避免客户端挂起
            if not done_seen:
                db.log_request({
                    "model": model or "unknown", "endpoint": "chat",
                    "response_time_ms": (time.time() - start_time) * 1000,
                    "success": False,
                    "error_message": f"stream ended without done (chunks={emitted})",
                    "client_ip": client_ip,
                })
                # 明确告知"被截断"，而不是伪装成正常结束
                yield sse({"error": {"message": f"上游流式中断（已收到 {emitted} 个分片）",
                                     "type": "stream_truncated"}})
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        })

    # ---------- 非流式 ----------
    try:
        response = await asyncio.to_thread(
            session.post,
            f"{OLLAMA_BASE_URL}/api/chat",
            json=ollama_req,
            headers=fwd_headers,
            timeout=600,
        )
    except Exception as e:
        db.log_request({
            "model": model or "unknown", "endpoint": "chat",
            "response_time_ms": (time.time() - start_time) * 1000,
            "success": False, "error_message": str(e), "client_ip": client_ip,
        })
        return JSONResponse(status_code=502, content={"error": "upstream unreachable"})

    elapsed_ms = (time.time() - start_time) * 1000
    response_body = response.content

    metrics = _extract_metrics(response_body, "chat", elapsed_ms, model)
    metrics["client_ip"] = client_ip
    db.log_request(metrics)

    try:
        ollama_resp = json.loads(response_body)
    except Exception:
        return Response(content=response_body, status_code=response.status_code,
                        headers=dict(response.headers))

    if ollama_resp.get("error"):
        return JSONResponse(status_code=response.status_code or 400,
                            content={"error": ollama_resp["error"]})

    prompt_tok = ollama_resp.get("prompt_eval_count", 0) or 0
    comp_tok = ollama_resp.get("eval_count", 0) or 0
    msg = ollama_resp.get("message") or {}

    openai_resp = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": ollama_resp.get("model", model),
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": msg.get("content", ""),
                **({"reasoning_content": msg["thinking"]} if msg.get("thinking") else {}),
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tok,
            "completion_tokens": comp_tok,
            "total_tokens": prompt_tok + comp_tok,
        },
    }
    return JSONResponse(openai_resp)


@app.post("/v1/completions")
async def openai_completions(request: Request):
    """OpenAI 格式的文本完成接口 → 转发到 Ollama /api/generate"""
    import asyncio
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    
    try:
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413,
                                content={"error": f"request body too large (>{MAX_BODY_BYTES} bytes)"})
        openai_req = json.loads(body)
        
        ollama_req = {
            "model": openai_req.get("model", ""),
            "prompt": openai_req.get("prompt", ""),
            "stream": openai_req.get("stream", False),
        }
        
        if "temperature" in openai_req:
            ollama_req["temperature"] = openai_req["temperature"]
        if "max_tokens" in openai_req:
            ollama_req["options"] = {"num_predict": openai_req["max_tokens"]}
        
        fwd_headers = {k: v for k, v in request.headers.items() 
                       if k.lower() not in ("host", "content-length")}
        
        response = await asyncio.to_thread(
            session.post,
            f"{OLLAMA_BASE_URL}/api/generate",
            json=ollama_req,
            headers=fwd_headers,
            timeout=600,
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        response_body = response.content
        
        metrics = _extract_metrics(response_body, "generate", elapsed_ms, ollama_req.get("model", ""))
        metrics["client_ip"] = client_ip
        db.log_request(metrics)
        
        if openai_req.get("stream", False):
            # 把 Ollama 的 NDJSON 转成 OpenAI SSE
            cmpl_id = f"cmpl-{int(time.time())}"
            created = int(time.time())

            def gen_sse():
                for line in response_body.split(b"\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ch = json.loads(line)
                    except Exception:
                        continue
                    text = ch.get("response") or ""
                    if text:
                        yield "data: " + json.dumps({
                            "id": cmpl_id, "object": "text_completion",
                            "created": created, "model": ollama_req.get("model", ""),
                            "choices": [{"text": text, "index": 0, "finish_reason": None}],
                        }, ensure_ascii=False) + "\n\n"
                    if ch.get("done"):
                        yield "data: " + json.dumps({
                            "id": cmpl_id, "object": "text_completion",
                            "created": created, "model": ollama_req.get("model", ""),
                            "choices": [{"text": "", "index": 0, "finish_reason": "stop"}],
                            "usage": {
                                "prompt_tokens": ch.get("prompt_eval_count", 0) or 0,
                                "completion_tokens": ch.get("eval_count", 0) or 0,
                                "total_tokens": (ch.get("prompt_eval_count", 0) or 0) + (ch.get("eval_count", 0) or 0),
                            },
                        }, ensure_ascii=False) + "\n\n"
                        yield "data: [DONE]\n\n"
                        return
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen_sse(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache",
                                              "X-Accel-Buffering": "no"})
        
        try:
            ollama_resp = json.loads(response_body)
            openai_resp = {
                "id": f"cmpl-{int(time.time())}",
                "object": "text_completion",
                "created": int(time.time()),
                "model": ollama_resp.get("model", openai_req.get("model", "")),
                "choices": [{
                    "text": ollama_resp.get("response", ""),
                    "index": 0,
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": ollama_resp.get("prompt_eval_count", 0) or 0,
                    "completion_tokens": ollama_resp.get("eval_count", 0) or 0,
                    "total_tokens": (ollama_resp.get("prompt_eval_count", 0) or 0) + (ollama_resp.get("eval_count", 0) or 0),
                },
            }
            return JSONResponse(openai_resp)
        except:
            return Response(
                content=response_body,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
            
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"OpenAI completions 请求失败: {e}")
        db.log_request({
            "model": "unknown",
            "endpoint": "/v1/completions",
            "response_time_ms": elapsed_ms,
            "success": False,
            "error_message": str(e),
            "client_ip": client_ip,
        })
        return JSONResponse(status_code=502, content={"error": f"Proxy error: {str(e)}"})


# HTTP 客户端（复用连接）
session = requests.Session()
adapter = HTTPAdapter(
    max_retries=Retry(total=2, backoff_factor=0.5),
    pool_connections=20,
    pool_maxsize=20,
)
session.mount("http://", adapter)
# requests 不读取 Session.timeout，必须每次显式传；统一在这里定义
TIMEOUT_LONG = (5, 600)   # 推理类：连接 5s，读取 600s
TIMEOUT_SHORT = (5, 30)   # 元数据类：tags / ps / models


# 注意：具体路由必须在通配符路由之前定义
@app.get("/api/tags")
def proxy_tags(request: Request):
    """代理 /api/tags（获取模型列表），不记录指标"""
    try:
        response = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=30)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/ps")
def proxy_ps(request: Request):
    """代理 /api/ps（获取运行中模型），不记录指标"""
    try:
        response = session.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=30)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.post("/api/model-residency")
async def model_residency(request: Request):
    """加载/卸载模型到内存（仅限本机）。

    enabled=true  → 发空 generate 请求让 Ollama 加载模型（keep_alive=-1 常驻）
    enabled=false → 发 keep_alive=0 请求让 Ollama 立即卸载
    """
    if not _is_local_request(request) or not _is_same_origin(request):
        return JSONResponse(status_code=403, content={"error": "仅限本机操作"})

    if request.headers.get("x-model-control") != "1":
        return JSONResponse(status_code=403, content={"error": "missing X-Model-Control header"})

    try:
        body = await request.body()
        payload = json.loads(body)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid body: {e}"})

    model = (payload.get("model") or "").strip()
    enabled = bool(payload.get("enabled", False))
    if not model:
        return JSONResponse(status_code=400, content={"error": "model is required"})

    try:
        if enabled:
            # 发一个空请求让 Ollama 加载模型，keep_alive=-1 表示常驻内存
            resp = session.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": -1},
                timeout=120,
            )
        else:
            # keep_alive=0 让 Ollama 立即卸载
            resp = session.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": model, "prompt": "", "keep_alive": 0},
                timeout=30,
            )

        if resp.status_code != 200:
            err = resp.text[:300]
            return JSONResponse(status_code=resp.status_code, content={"error": err})

        return {"status": "ok", "model": model, "enabled": enabled}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/metrics")
async def get_metrics(request: Request):
    """获取监控指标（供 Dashboard 调用）"""
    cumulative = db.get_cumulative_stats()
    recent = db.get_recent_requests(limit=20)
    hourly = db.get_hourly_stats(hours=24)
    five_min = db.get_five_min_stats(minutes=120)
    by_model = db.get_model_stats()
    gpu_stats = db.get_recent_gpu_stats(limit=360)  # 每 5 秒一采样 ≈ 近 30 分钟
    latency_pct = db.get_latency_percentiles()

    # 获取所有可用模型（从 Ollama）和运行中模型
    available_models = []
    running_models = []
    try:
        tags_resp = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if tags_resp.ok:
            available_models = [m["name"] for m in tags_resp.json().get("models", [])]
    except Exception:
        pass
    try:
        ps_resp = session.get(f"{OLLAMA_BASE_URL}/api/ps", timeout=5)
        if ps_resp.ok:
            running_models = [m["name"] for m in ps_resp.json().get("models", [])]
    except Exception:
        pass

    # 非本机访问时隐藏客户端 IP（看板对朋友开放，但 IP 不该外泄）
    if not _is_local_request(request):
        for r in recent:
            ip = r.get("client_ip") or ""
            if ip:
                parts = ip.split(".")
                r["client_ip"] = ".".join(parts[:2] + ["*", "*"]) if len(parts) == 4 else "***"

    return {
        "cumulative": cumulative,
        "recent_requests": recent,
        "hourly_stats": hourly,
        "five_min_stats": five_min,
        "by_model": by_model,
        "gpu_stats": gpu_stats,
        "latency_percentiles": latency_pct,
        "platform": "darwin" if sys.platform == "darwin" else "other",
        "gpu_source": _GPU_SOURCE,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "available_models": available_models,
        "running_models": running_models,
    }


@app.post("/reset")
def reset_data(request: Request):
    """清除所有监控数据，开始新一轮统计（仅限本机，防止公网误清/恶意清）"""
    if not _is_local_request(request) or not _is_same_origin(request):
        return JSONResponse(status_code=403,
                            content={"error": "清除仅限本机访问"})
    db.reset_all_data()
    return {"status": "ok", "message": "所有监控数据已清除"}


def _is_same_origin(request: Request) -> bool:
    """跨站表单/脚本的 Origin 与本站不同；无 Origin 的普通请求放行。"""
    origin = request.headers.get("origin") or ""
    if not origin or origin == "null":
        return not origin  # "null" 视为可疑
    host = request.headers.get("host") or ""
    return origin.split("://")[-1] == host


def _is_local_request(request: Request) -> bool:
    """判断是否为本机直连。经过 ngrok 隧道时上游会加 X-Forwarded-For。"""
    if request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


@app.get("/export")
def export_data(request: Request, format: str = "csv"):
    """导出监控数据。

    format=csv  → 逐条请求记录（Excel/Numbers 可直接打开）
    format=json → 完整快照（含累计、分模型、趋势、GPU 时序）
    """
    import io
    import csv as _csv

    if not _is_local_request(request) or not _is_same_origin(request):
        return JSONResponse(status_code=403,
                            content={"error": "导出仅限本机访问"})

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    conn = db._get_conn()

    if format.lower() == "json":
        conn.close()
        snapshot = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "cumulative": db.get_cumulative_stats(),
            "by_model": db.get_model_stats(),
            "hourly_stats": db.get_hourly_stats(hours=24),
            "five_min_stats": db.get_five_min_stats(minutes=120),
            "request_logs": db.get_recent_requests(limit=100000),
            "latency_percentiles": db.get_latency_percentiles(),
            "gpu_stats": db.get_recent_gpu_stats(limit=360),
        }
        payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
        return Response(
            content=payload.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="ollama-metrics-{ts}.json"'},
        )

    rows = conn.execute("SELECT * FROM request_logs ORDER BY id").fetchall()
    conn.close()

    buf = io.StringIO()
    buf.write("\ufeff")  # BOM，保证 Excel 正确识别 UTF-8
    fields = [
        "id", "timestamp", "model", "endpoint",
        "prompt_tokens", "completion_tokens", "total_tokens",
        "response_time_ms", "ttft_ms", "time_per_token_ms", "tokens_per_second",
        "success", "error_message", "client_ip",
    ]
    w = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        d = dict(r)
        d["success"] = "ok" if d.get("success") else "failed"
        w.writerow(d)

    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ollama-metrics-{ts}.csv"'},
    )


@app.get("/health")
def health_check():
    """健康检查"""
    try:
        resp = session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        ollama_status = resp.status_code == 200
    except:
        ollama_status = False
    
    return {
        "status": "ok" if ollama_status else "degraded",
        "ollama_reachable": ollama_status,
        "proxy_port": PROXY_PORT,
        "database": os.path.basename(DB_PATH),
    }


# /api/* 只放行"读 + 推理"，破坏性端点一律拒绝。
# 否则任何拿到公网域名的人都能 DELETE /api/delete 删模型、POST /api/pull 打满磁盘。
_API_ALLOW_GET = {"tags", "ps", "version", "show", "embed", "embeddings"}
_API_ALLOW_POST = {"chat", "generate", "show", "embed", "embeddings"}
_API_DENY = {"pull", "push", "create", "copy", "delete", "blobs"}


def _api_allowed(method: str, path: str) -> bool:
    seg = (path or "").split("/")[0].strip()
    if seg in _API_DENY:
        return False
    if method == "GET":
        return seg in _API_ALLOW_GET
    if method == "POST":
        return seg in _API_ALLOW_POST
    return False


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_api(path: str, request: Request):
    """代理 /api/* 到 Ollama（白名单），并记录指标"""
    import asyncio
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"

    if not _api_allowed(request.method, path):
        logger.warning("拒绝 /api/%s %s（非白名单或破坏性端点）", request.method, path)
        return JSONResponse(
            status_code=403,
            content={"error": f"endpoint /api/{path} is not allowed by proxy policy"},
        )
    
    # 构建目标 URL
    target_url = f"{OLLAMA_BASE_URL}/api/{path}"
    
    # 转发请求
    try:
        # 读取请求体（同步方式）
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413,
                                content={"error": f"request body too large (>{MAX_BODY_BYTES} bytes)"})
        
        # 过滤不需要转发的 header
        fwd_headers = {k: v for k, v in request.headers.items() 
                       if k.lower() not in ("host", "content-length")}
        
        # 发送请求到 Ollama
        response = await asyncio.to_thread(
            session.request,
            method=request.method,
            url=target_url,
            data=body,
            headers=fwd_headers,
            timeout=600,
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # 解析响应
        response_body = response.content
        
        # 尝试提取 Token 统计信息
        metrics = _extract_metrics(response_body, path, elapsed_ms, _model_from_body(body))
        
        # 记录到数据库
        metrics["client_ip"] = client_ip
        db.log_request(metrics)
        
        # 返回原始响应
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
        )
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"请求失败: {e}")
        
        # 记录错误
        db.log_request({
            "model": "unknown",
            "endpoint": f"/api/{path}",
            "response_time_ms": elapsed_ms,
            "success": False,
            "error_message": str(e),
            "client_ip": client_ip,
        })
        
        return JSONResponse(
            status_code=502,
            content={"error": f"Proxy error: {str(e)}"},
        )


def _model_from_body(body: bytes) -> str:
    """从原始请求体里尽力取出 model 名（用于上游不返回 model 的情况）"""
    if not body:
        return ""
    try:
        d = json.loads(body)
        if isinstance(d, dict):
            return str(d.get("model") or d.get("name") or "")
    except Exception:
        pass
    return ""


def _extract_metrics(response_body: bytes, endpoint: str, elapsed_ms: float,
                     fallback_model: str = "") -> dict:
    """从 Ollama 响应中提取 Token 统计信息。

    fallback_model: 响应里拿不到 model 时（错误响应、空响应、流式中间块），
    回退使用请求体里的 model，避免记成 unknown。
    """
    fb = fallback_model or "unknown"

    try:
        data = json.loads(response_body)
    except Exception:
        return {
            "model": fb,
            "endpoint": endpoint,
            "response_time_ms": elapsed_ms,
            "success": False,
            "error_message": "响应不是合法 JSON（可能上游超时或被中断）",
        }
    
    # 流式响应（chat/generate）：取最后一个 chunk 的 done=true
    if isinstance(data, dict) and data.get("done"):
        model = data.get("model") or fb
        prompt_tokens = data.get("prompt_eval_count", 0) or 0
        completion_tokens = data.get("eval_count", 0) or 0
        total_tokens = prompt_tokens + completion_tokens
        
        # 计算 TTFT（首字延迟）= 模型加载 + prompt 预填充，即用户等到第一个字的时间
        prompt_eval_duration_ns = data.get("prompt_eval_duration", 0) or 0
        load_duration_ns = data.get("load_duration", 0) or 0
        ttft_ms = round((prompt_eval_duration_ns + load_duration_ns) / 1e6, 2)
        
        # 计算 TPOT (每输出 Token 耗时) 和 Tokens/s
        eval_duration_ns = data.get("eval_duration", 0) or 0
        if eval_duration_ns > 0 and completion_tokens > 0:
            time_per_token_ms = round((eval_duration_ns / 1e6) / completion_tokens, 2)
            tokens_per_second = round(completion_tokens / (eval_duration_ns / 1e9), 2)
        else:
            time_per_token_ms = 0
            tokens_per_second = 0
        
        return {
            "model": model,
            "endpoint": endpoint,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "response_time_ms": elapsed_ms,
            "ttft_ms": ttft_ms,
            # 阶段分解（毫秒）：加载 / 输入处理 / 输出生成 / 上游总计
            "load_ms": round(load_duration_ns / 1e6, 2),
            "prompt_eval_ms": round(prompt_eval_duration_ns / 1e6, 2),
            "eval_ms": round(eval_duration_ns / 1e6, 2),
            "total_ms": round((data.get("total_duration", 0) or 0) / 1e6, 2),
            "time_per_token_ms": time_per_token_ms,
            "tokens_per_second": tokens_per_second,
            "success": True,
        }
    
    # 上游错误响应 {"error": "..."}
    if isinstance(data, dict) and data.get("error"):
        return {
            "model": fb,
            "endpoint": endpoint,
            "response_time_ms": elapsed_ms,
            "success": False,
            "error_message": str(data["error"])[:500],
        }

    # 非流式或嵌入等其它端点
    model = data.get("model") or fb
    return {
        "model": model,
        "endpoint": endpoint,
        "response_time_ms": elapsed_ms,
        "success": True,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=BIND_HOST,
        port=PROXY_PORT,
        log_level=LOG_LEVEL.lower(),
    )
