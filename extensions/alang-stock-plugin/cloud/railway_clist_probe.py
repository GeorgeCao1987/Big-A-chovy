#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused Railway probe for EastMoney clist behavior used by fetch_market()."""
from __future__ import annotations

import json
import socket
import time
from typing import Any, Dict

import requests

HOSTS = [
    "https://push2delay.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
]
UT = "bd1d9ddb04089700cf9c27f6f7426281"
FULL_FIELDS = "f12,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,f20,f21,f100,f124,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
FS = "m:1+t:2,m:0+t:6,m:0+t:80,m:1+t:23"
PREFIX = "[ALANG-CLIST-PROBE]"


def emit(name: str, **kw: Any) -> None:
    print(f"{PREFIX} {json.dumps({'event': name, **kw}, ensure_ascii=False, default=str)}", flush=True)


def one(url: str, label: str, params: Dict[str, Any]) -> None:
    started = time.perf_counter()
    try:
        host = url.split('/')[2]
        ips = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        r = requests.get(
            url,
            params=params,
            timeout=12,
            verify=False,
            headers={
                "User-Agent": "Mozilla/5.0 alang-clist-probe/1.0",
                "Referer": "https://quote.eastmoney.com/center/gridlist.html",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        sample = r.text[:260].replace("\n", " ")
        parsed = None
        try:
            parsed = r.json()
        except Exception:
            pass
        data = (parsed or {}).get("data") if isinstance(parsed, dict) else None
        diff = (data or {}).get("diff") if isinstance(data, dict) else None
        emit(
            label,
            ok=True,
            host=host,
            ips=ips[:6],
            status=r.status_code,
            elapsed_ms=elapsed,
            total=(data or {}).get("total") if isinstance(data, dict) else None,
            diff_len=len(diff or []) if isinstance(diff, list) else None,
            rc=(parsed or {}).get("rc") if isinstance(parsed, dict) else None,
            sample=sample,
            final_url=r.url,
        )
    except Exception as exc:
        emit(label, ok=False, error_type=type(exc).__name__, error=str(exc))


def main() -> int:
    variants = {
        "exact_f12_full": {
            "pn": 1, "pz": 100, "po": 1, "np": 1, "ut": UT,
            "fltt": 2, "invt": 2, "fid": "f12", "fs": FS, "fields": FULL_FIELDS,
        },
        "f3_full": {
            "pn": 1, "pz": 100, "po": 1, "np": 1, "ut": UT,
            "fltt": 2, "invt": 2, "fid": "f3", "fs": FS, "fields": FULL_FIELDS,
        },
        "f12_basic": {
            "pn": 1, "pz": 100, "po": 1, "np": 1, "ut": UT,
            "fltt": 2, "invt": 2, "fid": "f12", "fs": FS,
            "fields": "f12,f14,f2,f3,f5,f6,f8,f10,f15,f18,f21",
        },
        "f3_basic": {
            "pn": 1, "pz": 100, "po": 1, "np": 1, "ut": UT,
            "fltt": 2, "invt": 2, "fid": "f3", "fs": FS,
            "fields": "f12,f14,f2,f3,f5,f6,f8,f10,f15,f18,f21",
        },
    }
    for url in HOSTS:
        host = url.split('/')[2].replace('.', '_')
        for variant, params in variants.items():
            one(url, f"{host}:{variant}", params)
    emit("summary", ok=True, variants=len(variants), hosts=len(HOSTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
