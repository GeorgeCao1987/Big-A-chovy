#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""REST compatibility layer for the 阿狼 × Big-A-chovy cloud service.

This module keeps the existing MCP endpoint untouched and adds plain read-only
HTTP routes for clients that cannot register custom MCP servers.  All business
logic is reused from ``server.py`` so MCP and REST return the same underlying
data and screening evidence.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse

import server as core


mcp = core.mcp
_SCAN_LOCK = asyncio.Lock()


def _bool_param(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _error_response(exc: Exception, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "error": type(exc).__name__,
            "detail": str(exc),
            "timestamp": core._now_text(),
        },
        status_code=status_code,
    )


async def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "alang-stock-data",
            "timestamp": core._now_text(),
            "mcp": "/mcp",
            "rest": {
                "health": "/api/health",
                "market": "/api/market",
                "sectors": "/api/sectors?limit=25",
                "scan": "/api/scan?mode=all&top=15&check_announcements=true",
                "stock": "/api/stock/{code}?minute_limit=120",
            },
            "read_only": True,
        }
    )


@mcp.custom_route("/api/health", methods=["GET"])
async def api_health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "service": "alang-stock-data",
            "timestamp": core._now_text(),
            "mcp_path": "/mcp",
            "rest_enabled": True,
        }
    )


@mcp.custom_route("/api/market", methods=["GET"])
async def api_market(request: Request) -> JSONResponse:
    try:
        data = await _run_sync(core.market_snapshot)
        return JSONResponse({"ok": True, "data": data})
    except Exception as exc:
        return _error_response(exc)


@mcp.custom_route("/api/sectors", methods=["GET"])
async def api_sectors(request: Request) -> JSONResponse:
    try:
        raw_limit = request.query_params.get("limit", "25")
        try:
            limit = int(raw_limit)
        except ValueError:
            return _error_response(ValueError("limit必须是整数"), 400)
        data = await _run_sync(core.sector_rank, limit)
        return JSONResponse({"ok": True, "data": data})
    except Exception as exc:
        return _error_response(exc)


@mcp.custom_route("/api/scan", methods=["GET"])
async def api_scan(request: Request) -> JSONResponse:
    try:
        mode = request.query_params.get("mode", "all")
        raw_top = request.query_params.get("top", "15")
        try:
            top = int(raw_top)
        except ValueError:
            return _error_response(ValueError("top必须是整数"), 400)
        check_announcements = _bool_param(
            request.query_params.get("check_announcements"),
            default=True,
        )
        # A full-market scan can take over a minute.  Serialize scans so two
        # callers do not double memory/network pressure on the Railway replica.
        async with _SCAN_LOCK:
            data = await _run_sync(core.scan_candidates, mode, top, check_announcements)
        return JSONResponse({"ok": True, "data": data})
    except ValueError as exc:
        return _error_response(exc, 400)
    except Exception as exc:
        return _error_response(exc)


@mcp.custom_route("/api/stock/{code}", methods=["GET"])
async def api_stock(request: Request) -> JSONResponse:
    try:
        code = request.path_params.get("code", "")
        raw_limit = request.query_params.get("minute_limit", "120")
        try:
            minute_limit = int(raw_limit)
        except ValueError:
            return _error_response(ValueError("minute_limit必须是整数"), 400)
        data = await _run_sync(core.stock_detail, code, minute_limit)
        return JSONResponse({"ok": True, "data": data})
    except ValueError as exc:
        return _error_response(exc, 400)
    except Exception as exc:
        return _error_response(exc)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )
