#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple hosted-runtime connectivity probe for Vercel."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict


def _probe(host: str, url: str, timeout: float = 4.0) -> Dict[str, Any]:
    started = time.time()
    out: Dict[str, Any] = {"host": host, "dns": False, "https": False}
    try:
        addrs = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        out["dns"] = True
        out["addresses"] = addrs[:4]
    except Exception as exc:
        out["dns_error"] = f"{type(exc).__name__}: {exc}"
        out["elapsed_ms"] = round((time.time() - started) * 1000, 1)
        return out

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 alang-stock-health/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sample = resp.read(256)
            out["https"] = True
            out["status"] = getattr(resp, "status", 200)
            out["sample_bytes"] = len(sample)
    except Exception as exc:
        out["https_error"] = f"{type(exc).__name__}: {exc}"
    out["elapsed_ms"] = round((time.time() - started) * 1000, 1)
    return out


def build_health() -> Dict[str, Any]:
    probes = [
        _probe(
            "push2delay.eastmoney.com",
            "https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f57,f58,f43,f44,f45,f46,f47,f48",
        ),
        _probe("qt.gtimg.cn", "https://qt.gtimg.cn/q=sh000001"),
        _probe(
            "money.finance.sina.com.cn",
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=2",
        ),
        _probe("github.com", "https://github.com/"),
    ]
    return {
        "ok": any(p.get("https") for p in probes[:3]),
        "runtime": "vercel",
        "region": os.environ.get("VERCEL_REGION"),
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA"),
        "probes": probes,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = json.dumps(build_health(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)
