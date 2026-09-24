#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fresh-container probe for the production scan path only."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import server  # noqa: E402

PREFIX = "[ALANG-SCAN-PROBE]"


def emit(event: str, **kw):
    print(f"{PREFIX} {json.dumps({'event': event, **kw}, ensure_ascii=False, default=str)}", flush=True)


def main() -> int:
    started = time.perf_counter()
    emit("start")
    try:
        data = server.scan_candidates(mode="strict", top=5, check_announcements=False)
        status = data.get("market_fetch_status") or {}
        breadth = data.get("breadth") or {}
        emit(
            "scan",
            ok=True,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            source=status.get("source"),
            complete=status.get("complete"),
            provider_total=status.get("provider_total"),
            retrieved_rows=status.get("retrieved_rows"),
            expected_pages=status.get("expected_pages"),
            received_pages=status.get("received_pages"),
            failed_pages=status.get("failed_pages"),
            has_snapshot=data.get("has_snapshot"),
            breadth_total=breadth.get("total_rows"),
            raw_total=breadth.get("raw_total_rows"),
            degraded=breadth.get("degraded"),
            counts={
                "strict_ultra": len(data.get("strict_ultra") or []),
                "strict_trend": len(data.get("strict_trend") or []),
                "trend_observation": len(data.get("trend_observation") or []),
                "dual_pool": len(data.get("dual_pool") or []),
            },
            warnings=(data.get("warnings") or [])[:8],
            errors=(data.get("errors") or [])[:8],
        )
    except Exception as exc:
        emit(
            "scan",
            ok=False,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(limit=4),
        )
    emit("summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
