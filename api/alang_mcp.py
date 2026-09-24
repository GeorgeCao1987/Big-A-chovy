#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stateless MCP endpoint for Vercel.

This adapter is additive-only. It deliberately avoids adding new Python
packages so Vercel can deploy the repository with the existing root
requirements.txt. The actual market logic remains in
extensions/alang-stock-plugin/work/runner.py.

Public route is rewritten from /mcp -> /api/alang_mcp by vercel.json.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_FILE = REPO_ROOT / "extensions" / "alang-stock-plugin" / "work" / "runner.py"
SERVER_NAME = "alang-stock-data"
SERVER_VERSION = "0.1.0-vercel"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_runner():
    name = "alang_stock_vercel_runner"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, RUNNER_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 runner: {RUNNER_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    return value


def _probe_host(host: str, url: str | None = None, timeout: float = 4.0) -> Dict[str, Any]:
    started = time.time()
    out: Dict[str, Any] = {"host": host, "dns": False, "https": None}
    try:
        addrs = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        out["dns"] = True
        out["addresses"] = addrs[:4]
    except Exception as exc:
        out["dns_error"] = f"{type(exc).__name__}: {exc}"
        out["elapsed_ms"] = round((time.time() - started) * 1000, 1)
        return out

    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 alang-stock-health/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(256)
                out["https"] = True
                out["status"] = getattr(resp, "status", 200)
                out["sample_bytes"] = len(body)
        except Exception as exc:
            out["https"] = False
            out["https_error"] = f"{type(exc).__name__}: {exc}"
    out["elapsed_ms"] = round((time.time() - started) * 1000, 1)
    return out


def health_check() -> Dict[str, Any]:
    """Probe DNS and outbound HTTPS from the hosted runtime."""
    probes = [
        _probe_host(
            "push2delay.eastmoney.com",
            "https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f57,f58,f43,f44,f45,f46,f47,f48",
        ),
        _probe_host("qt.gtimg.cn", "https://qt.gtimg.cn/q=sh000001"),
        _probe_host(
            "money.finance.sina.com.cn",
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=2",
        ),
        _probe_host("github.com", "https://github.com/"),
    ]
    return {
        "ok": any(p.get("https") is True for p in probes[:3]),
        "runtime": "vercel",
        "region": os.environ.get("VERCEL_REGION"),
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA"),
        "probes": probes,
        "note": "行情源只要至少一个可用即可继续；最终工具仍会返回数据质量与降级信息。",
    }


TOOLS = [
    {
        "name": "health_check",
        "description": "检查托管环境对东财、腾讯、新浪及GitHub的DNS和HTTPS连通性。部署后应先调用此工具。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "market_snapshot",
        "description": "取得上证、深证成指、沪深300、科创50实时/快照数据及5/10/13/20/60/144日均线。只提供证据，不做交易结论。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sector_rank",
        "description": "扫描A股行业板块，返回涨幅、成交额、主力净额、上涨/下跌家数等，用于阿狼Skill先选方向。",
        "inputSchema": {
            "type": "object",
            "properties": {"top": {"type": "integer", "minimum": 5, "maximum": 100, "default": 30}},
            "additionalProperties": False,
        },
    },
    {
        "name": "scan_candidates",
        "description": "运行Big-A-chovy全市场候选发现。A/B/C、dual_pool、intersection等仅为发现标签，不等于买点。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["all", "strict", "low", "watchlist"], "default": "all"},
                "top": {"type": "integer", "minimum": 3, "maximum": 30, "default": 15},
                "check_announcements": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "stock_detail",
        "description": "取得指定A股的实时行情、五档、分时、15分钟聚合、日K均线、资金与公告风险。",
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string", "pattern": "^[0-9]{6}$"},
                "minute_tail": {"type": "integer", "minimum": 30, "maximum": 300, "default": 240},
            },
            "additionalProperties": False,
        },
    },
]


def _call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    if name == "health_check":
        return health_check()
    runner = _load_runner()
    if name == "market_snapshot":
        return runner.market_snapshot()
    if name == "sector_rank":
        return runner.sector_rank(arguments.get("top", 30))
    if name == "scan_candidates":
        return runner.scan_candidates(
            arguments.get("mode", "all"),
            arguments.get("top", 15),
            arguments.get("check_announcements", True),
        )
    if name == "stock_detail":
        return runner.stock_detail(arguments.get("code", ""), arguments.get("minute_tail", 240))
    raise ValueError(f"未知工具: {name}")


def _rpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


def _handle_rpc(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    req_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    # Force modern clients to use their documented legacy fallback. This keeps
    # the Vercel function stateless without implementing the full 2026 discovery
    # envelope by hand. ChatGPT/SDK clients that probe first will fall back to
    # initialize on the same URL.
    if method == "server/discover":
        return _rpc_error(req_id, -32601, "Method not found")

    if method == "initialize":
        requested = str(params.get("protocolVersion") or "2025-11-25")
        supported = {"2025-11-25", "2025-06-18", "2025-03-26"}
        negotiated = requested if requested in supported else "2025-11-25"
        return _rpc_result(
            req_id,
            {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "只提供A股实时/快照数据和Big-A候选发现。"
                    "最终判断由阿狼Skill完成；不得把候选标签直接当买卖结论。"
                ),
            },
        )

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _rpc_error(req_id, -32602, "arguments必须是对象")
        try:
            value = _json_safe(_call_tool(name, arguments))
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            result: Dict[str, Any] = {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }
            # Current MCP clients accept object structuredContent on legacy
            # revisions. Our tools all return objects.
            if isinstance(value, dict):
                result["structuredContent"] = value
            return _rpc_result(req_id, result)
        except Exception as exc:
            err = {
                "tool": name,
                "type": type(exc).__name__,
                "message": str(exc),
                "runtime": "vercel",
                "region": os.environ.get("VERCEL_REGION"),
            }
            return _rpc_result(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps(err, ensure_ascii=False)}],
                    "isError": True,
                },
            )

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


class handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST,OPTIONS,GET")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type,Accept,MCP-Protocol-Version,Mcp-Session-Id,Mcp-Method,Mcp-Name,Authorization",
        )

    def _send_json(self, status: int, obj: Any) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        self._send_json(
            200,
            {
                "service": SERVER_NAME,
                "version": SERVER_VERSION,
                "status": "ok",
                "mcp": "/mcp",
                "health": "/health",
                "note": "MCP为无状态POST；GET仅用于部署探活。",
            },
        )

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 1_000_000:
                self._send_json(400, _rpc_error(None, -32700, "Invalid request body"))
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                self._send_json(400, _rpc_error(None, -32600, "Invalid Request"))
                return
            result = _handle_rpc(payload)
            if result is None:
                self.send_response(202)
                self._cors()
                self.end_headers()
                return
            self._send_json(200, result)
        except json.JSONDecodeError as exc:
            self._send_json(400, _rpc_error(None, -32700, f"Parse error: {exc}"))
        except Exception as exc:
            self._send_json(500, _rpc_error(None, -32603, f"Internal error: {type(exc).__name__}: {exc}"))
