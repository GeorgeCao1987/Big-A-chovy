#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Focused Railway probe comparing requests trust_env paths for EastMoney clist."""
from __future__ import annotations

import json
import time
from typing import Any

import requests

URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
UT = "bd1d9ddb04089700cf9c27f6f7426281"
FIELDS = "f12,f14,f2,f3,f4,f5,f6,f7,f8,f10,f15,f16,f17,f18,f20,f21,f100,f124,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87"
PARAMS = {
    "pn": 1,
    "pz": 100,
    "po": 1,
    "np": 1,
    "ut": UT,
    "fltt": 2,
    "invt": 2,
    "fid": "f12",
    "fs": "m:1+t:2,m:0+t:6,m:0+t:80,m:1+t:23",
    "fields": FIELDS,
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) daily-stock-analysis/1.0",
    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
PREFIX = "[ALANG-CLIST-PROBE]"


def emit(event: str, **kw: Any) -> None:
    print(f"{PREFIX} {json.dumps({'event': event, **kw}, ensure_ascii=False, default=str)}", flush=True)


def run(label: str, trust_env: bool) -> None:
    session = requests.Session()
    session.trust_env = trust_env
    started = time.perf_counter()
    try:
        r = session.get(URL, params=PARAMS, headers=HEADERS, timeout=12, verify=False)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        parsed = r.json()
        data = parsed.get("data") or {}
        diff = data.get("diff") or []
        emit(
            label,
            ok=True,
            trust_env=trust_env,
            status=r.status_code,
            elapsed_ms=elapsed,
            total=data.get("total"),
            diff_len=len(diff),
            rc=parsed.get("rc"),
            final_url=r.url,
        )
    except Exception as exc:
        emit(label, ok=False, trust_env=trust_env, error_type=type(exc).__name__, error=str(exc))
    finally:
        session.close()


def main() -> int:
    run("trust_env_false", False)
    run("trust_env_true", True)
    emit("summary", ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
