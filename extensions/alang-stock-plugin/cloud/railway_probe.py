#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Railway runtime self-test for the 阿狼 × Big-A-chovy cloud service.

This script is intentionally read-only. It validates DNS/HTTPS reachability for
our market-data providers and then exercises the four model-facing data paths.
It always exits 0 by default so a failed probe does not take production down;
pass --strict if a non-zero exit code is desired on any failed check.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List

import requests

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import server  # noqa: E402

PREFIX = "[ALANG-PROBE]"


def emit(event: str, **payload: Any) -> None:
    row = {"event": event, **payload}
    print(f"{PREFIX} {json.dumps(row, ensure_ascii=False, default=str)}", flush=True)


def timed(label: str, fn: Callable[[], Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        value = fn()
        ms = round((time.perf_counter() - started) * 1000, 1)
        emit(label, ok=True, elapsed_ms=ms, result=value)
        return {"ok": True, "elapsed_ms": ms, "result": value}
    except Exception as exc:
        ms = round((time.perf_counter() - started) * 1000, 1)
        emit(
            label,
            ok=False,
            elapsed_ms=ms,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(limit=3),
        )
        return {"ok": False, "elapsed_ms": ms, "error": f"{type(exc).__name__}: {exc}"}


def probe_dns(host: str) -> Dict[str, Any]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = sorted({info[4][0] for info in infos})
    return {"host": host, "ips": ips[:8], "count": len(ips)}


def probe_http(name: str, url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    r = requests.get(
        url,
        params=params,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0 alang-stock-railway-probe/1.0"},
    )
    body = r.text[:180].replace("\n", " ")
    return {
        "name": name,
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "sample": body,
    }


def summarize_market() -> Dict[str, Any]:
    data = server.market_snapshot()
    rows = data.get("indices") or []
    return {
        "count": len(rows),
        "rows": [
            {
                "code": r.get("code"),
                "name": r.get("name"),
                "price": r.get("price"),
                "change": r.get("change"),
                "amount": r.get("amount"),
                "ma20": (r.get("ma") or {}).get("ma20"),
                "ma60": (r.get("ma") or {}).get("ma60"),
            }
            for r in rows
        ],
        "warnings": data.get("warnings") or [],
    }


def summarize_sectors() -> Dict[str, Any]:
    data = server.sector_rank(limit=8)
    rows = data.get("sectors") or []
    return {
        "total_sectors": data.get("total_sectors"),
        "count": len(rows),
        "top": [
            {
                "code": r.get("code"),
                "name": r.get("name"),
                "change": r.get("change"),
                "amount": r.get("amount"),
                "main_net": r.get("main_net"),
                "recognition_score": r.get("recognition_score"),
            }
            for r in rows[:5]
        ],
    }


def summarize_stock() -> Dict[str, Any]:
    data = server.stock_detail("002916", minute_limit=30)
    quote = data.get("quote") or {}
    return {
        "code": data.get("code"),
        "name": quote.get("name"),
        "price": quote.get("price"),
        "change": quote.get("change"),
        "minute_rows": len(data.get("minute") or []),
        "bars_15m": len(data.get("bars_15m") or []),
        "daily_rows": len(data.get("daily_kline") or []),
        "kline_source": data.get("kline_source"),
        "announcement_risk": (data.get("announcements") or {}).get("risk_status"),
        "warnings": data.get("warnings") or [],
    }


def summarize_scan() -> Dict[str, Any]:
    # strict still performs a real market snapshot/screen, but keeps the probe
    # output and follow-up enrichment smaller than a full all-mode report.
    data = server.scan_candidates(mode="strict", top=5, check_announcements=False)
    sections = ["strict_ultra", "strict_trend", "trend_observation", "dual_pool"]
    return {
        "has_snapshot": data.get("has_snapshot"),
        "breadth": data.get("breadth") or {},
        "market_fetch_status": data.get("market_fetch_status") or {},
        "counts": {name: len(data.get(name) or []) for name in sections},
        "warnings": (data.get("warnings") or [])[:8],
        "errors": (data.get("errors") or [])[:8],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any probe fails")
    args = parser.parse_args()

    emit("start", python=sys.version.split()[0], repo_root=str(REPO_ROOT))

    checks: List[Dict[str, Any]] = []
    hosts = [
        "push2delay.eastmoney.com",
        "push2his.eastmoney.com",
        "np-anotice-stock.eastmoney.com",
        "qt.gtimg.cn",
        "money.finance.sina.com.cn",
    ]
    for host in hosts:
        checks.append(timed(f"dns:{host}", lambda host=host: probe_dns(host)))

    http_targets = [
        (
            "eastmoney_clist",
            "https://push2delay.eastmoney.com/api/qt/clist/get",
            {"pn": 1, "pz": 1, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f2,f3"},
        ),
        (
            "eastmoney_kline",
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {"secid": "0.002916", "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56", "klt": 101, "fqt": 1, "end": "20500101", "lmt": 2},
        ),
        ("tencent_quote", "https://qt.gtimg.cn/q=sz002916", None),
        (
            "sina_kline",
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            {"symbol": "sz002916", "scale": 240, "ma": "no", "datalen": 2},
        ),
    ]
    for name, url, params in http_targets:
        checks.append(timed(f"https:{name}", lambda name=name, url=url, params=params: probe_http(name, url, params)))

    checks.append(timed("tool:market_snapshot", summarize_market))
    checks.append(timed("tool:sector_rank", summarize_sectors))
    checks.append(timed("tool:stock_detail:002916", summarize_stock))
    checks.append(timed("tool:scan_candidates:strict", summarize_scan))

    passed = sum(1 for x in checks if x.get("ok"))
    failed = len(checks) - passed
    emit("summary", passed=passed, failed=failed, total=len(checks), all_ok=(failed == 0))
    return 1 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
