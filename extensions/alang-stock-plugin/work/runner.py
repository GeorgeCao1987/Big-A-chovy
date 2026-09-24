#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ChatGPT Work execution entrypoint for 阿狼 × Big-A-chovy.

This file is additive-only and intentionally lives under extensions/ so the
upstream project can continue to sync normally.

It exposes four read-only JSON commands for Work's cloud computer:

  market   - major indices + key moving averages
  sectors  - full industry-board ranking snapshot
  scan     - run the existing Big-A-chovy candidate screener
  stock    - one-stock quote/minute/15m/daily/flow/risk detail

The runner never places orders and never makes the final trading decision.
Final interpretation belongs to the alang-stock-work Skill.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
SCREEN_DIR = REPO_ROOT / "daily-stock-analysis" / "scripts"
SCREEN_FILE = SCREEN_DIR / "a_share_daily_screen.py"
TZ = ZoneInfo("Asia/Shanghai")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCREEN_DIR) not in sys.path:
    sys.path.insert(0, str(SCREEN_DIR))

from tools import query_quote  # noqa: E402


def _load_screener():
    name = "big_a_chovy_work_screen"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCREEN_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载筛选引擎: {SCREEN_FILE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # Work 云电脑无需探测用户本机代理。
    module.set_network_mode("direct")
    return module


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _sanitize(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _sanitize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _ma(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    closes = [float(r["close"]) for r in rows if _num(r.get("close"))]
    out: Dict[str, Optional[float]] = {}
    for n in (5, 10, 13, 20, 60, 144):
        out[f"ma{n}"] = round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None
    return out


def _compact_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "code", "name", "price", "change", "turnover", "amount", "volume_ratio",
        "industry", "high", "low", "open", "prev_close", "high_pull", "cur_to_high",
        "ma5", "ma10", "ma20", "prev_ma5", "prev_ma10", "prev_ma20", "five_ret",
        "dist60", "ma20_dist", "vol_vs_avg5", "vwap", "vwap_state", "price_above_vwap",
        "main_net", "main_pct", "super_net", "super_pct", "big_net", "big_pct",
        "flow_5m_inc", "flow_15m_inc", "flow_status", "buy_ratio", "risk_status",
        "class", "risk", "score", "resonance", "dominance_type", "dominance_label",
        "sector_change", "phase", "phase_label", "trigger_price", "pullback_zone",
        "rejection_reasons", "gate_failures", "upgrade_status",
    )
    return {k: row.get(k) for k in keys if k in row}


def market_snapshot() -> Dict[str, Any]:
    s = _load_screener()
    index_defs = [
        ("1.000001", "上证指数"),
        ("0.399001", "深证成指"),
        ("1.000300", "沪深300"),
        ("1.000688", "科创50"),
    ]
    secids = ",".join(x[0] for x in index_defs)
    raw: Dict[str, Dict[str, Any]] = {}
    try:
        data = s.fetch_json(
            s.INDEX_URLS[0],
            {
                "fltt": 2,
                "invt": 2,
                "fields": "f12,f14,f2,f3,f4,f6,f104,f105,f106,f124",
                "secids": secids,
                "ut": s.EASTMONEY_UT,
            },
            timeout=6,
            retries=1,
        )
        for r in ((data.get("data") or {}).get("diff") or []):
            raw[str(r.get("f12") or "")] = r
    except Exception as exc:
        raw = {"_error": {"message": str(exc)}}

    rows = []
    for secid, expected_name in index_defs:
        code = secid.split(".", 1)[1]
        r = raw.get(code, {})
        item: Dict[str, Any] = {
            "code": code,
            "name": r.get("f14") or expected_name,
            "price": r.get("f2"),
            "change": r.get("f3"),
            "amount": r.get("f6"),
            "up_count": r.get("f104"),
            "down_count": r.get("f105"),
            "flat_count": r.get("f106"),
            "timestamp": r.get("f124"),
        }
        try:
            kdata = s.fetch_json(
                s.EM_KLINE_URL,
                {
                    "secid": secid,
                    "ut": s.EASTMONEY_UT,
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "klt": 101,
                    "fqt": 1,
                    "end": "20500101",
                    "lmt": 170,
                },
                timeout=6,
                retries=1,
            )
            klines = s.parse_k_rows((kdata.get("data") or {}).get("klines") or [])
            item["moving_averages"] = _ma(klines)
            item["last_daily"] = klines[-1] if klines else None
        except Exception as exc:
            item["moving_averages"] = {}
            item["kline_error"] = str(exc)
        rows.append(item)

    return {
        "meta": {
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Eastmoney direct snapshot + daily kline",
            "purpose": "数据证据，不是交易结论",
        },
        "indices": rows,
        "missing": [
            "昨日同期成交额尚未在Work首版提供",
            "黄白线/GJD ETF/两融/期指/A50尚未在Work首版提供",
        ],
    }


def sector_rank(top: int = 30) -> Dict[str, Any]:
    s = _load_screener()
    top = max(5, min(int(top), 100))
    boards: List[Dict[str, Any]] = []
    warnings: List[str] = []
    fields = "f12,f14,f2,f3,f6,f8,f62,f104,f105,f124"
    for page in range(1, 6):
        got = False
        params = {
            "pn": page,
            "pz": 100,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": fields,
            "ut": s.EASTMONEY_UT,
        }
        for url in s.CLIST_URLS[:3]:
            try:
                data = s.fetch_json(url, params, timeout=6, retries=1)
                diff = ((data.get("data") or {}).get("diff") or [])
                for r in diff:
                    up = r.get("f104")
                    down = r.get("f105")
                    denom = (up or 0) + (down or 0)
                    boards.append({
                        "code": r.get("f12"),
                        "name": r.get("f14"),
                        "price": r.get("f2"),
                        "change": r.get("f3"),
                        "amount": r.get("f6"),
                        "turnover": r.get("f8"),
                        "main_net": r.get("f62"),
                        "up_count": up,
                        "down_count": down,
                        "advance_ratio": round((up or 0) / denom, 4) if denom else None,
                        "timestamp": r.get("f124"),
                    })
                got = True
                if len(diff) < 100:
                    page = 999
                break
            except Exception:
                continue
        if not got:
            warnings.append(f"行业板块第{page}页获取失败")
            break
        if len(boards) and len(boards) % 100 != 0:
            break

    boards.sort(
        key=lambda x: (
            float(x.get("change")) if _num(x.get("change")) else -999.0,
            float(x.get("main_net")) if _num(x.get("main_net")) else -1e30,
        ),
        reverse=True,
    )
    return {
        "meta": {
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Eastmoney industry-board snapshot",
            "note": "排序只用于缩小研究范围；是否为主线由Skill结合成交额、资金、梯队、持续性判断。",
        },
        "sectors": boards[:top],
        "total": len(boards),
        "warnings": warnings,
    }


def scan_candidates(mode: str = "all", top: int = 15, check_announcements: bool = True) -> Dict[str, Any]:
    allowed = {"all", "strict", "low", "watchlist"}
    mode = str(mode or "all").lower().strip()
    if mode not in allowed:
        raise ValueError(f"mode必须是 {sorted(allowed)} 之一")
    top = max(3, min(int(top), 30))

    tmp = tempfile.NamedTemporaryFile(prefix="alang_work_scan_", suffix=".json", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        cmd = [
            sys.executable,
            str(SCREEN_FILE),
            "--mode", mode,
            "--format", "json",
            "--top", str(top),
            "--save", str(tmp_path),
            "--network-mode", "direct",
        ]
        if not check_announcements:
            cmd.append("--skip-announcements")
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=280,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "未知错误")[-5000:]
            raise RuntimeError(f"筛选失败(returncode={proc.returncode}): {detail}")
        payload = json.loads(tmp_path.read_text(encoding="utf-8"))
        sections = (
            "strict_ultra", "trend_observation", "strict_trend", "dual_pool", "dual_pool_raw",
            "pre_intersection", "intersection_states", "capital_rank", "low_ultra", "low_trend",
            "watchlist", "sector_indices", "flow_detail", "low_open_wash",
        )
        out: Dict[str, Any] = {
            "meta": payload.get("meta") or {},
            "breadth": payload.get("breadth") or {},
            "market_fetch_status": payload.get("market_fetch_status") or {},
            "indices": payload.get("indices") or [],
            "warnings": payload.get("warnings") or [],
            "errors": payload.get("errors") or [],
            "announcement_errors": payload.get("announcement_errors") or [],
            "announcement_check_available": payload.get("announcement_check_available"),
            "note": "Big-A标签只表示候选发现，不等于阿狼体系买点。",
        }
        for section in sections:
            rows = payload.get(section) or []
            out[section] = [_compact_candidate(r) if isinstance(r, dict) else r for r in rows] if isinstance(rows, list) else rows
        return out
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _parse_minute(lines: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in lines:
        parts = str(line).replace(",", " ").split()
        if len(parts) < 3:
            continue
        try:
            out.append({
                "time": parts[0],
                "price": float(parts[1]),
                "volume": float(parts[2]),
                "amount": float(parts[3]) if len(parts) > 3 and parts[3] not in {"-", "--"} else None,
            })
        except (TypeError, ValueError):
            continue
    return out


def _aggregate_15m(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        t = str(r.get("time") or "")
        if len(t) < 4 or not t[:4].isdigit():
            continue
        hh = int(t[:2])
        mm = int(t[2:4])
        bucket_min = (mm // 15) * 15
        key = f"{hh:02d}:{bucket_min:02d}"
        buckets.setdefault(key, []).append(r)
    out = []
    for key in sorted(buckets):
        rs = buckets[key]
        prices = [float(x["price"]) for x in rs if _num(x.get("price"))]
        vols = [float(x["volume"]) for x in rs if _num(x.get("volume"))]
        if not prices:
            continue
        out.append({
            "time": key,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(vols),
        })
    return out


def _stock_flow(code: str) -> Dict[str, Any]:
    s = _load_screener()
    try:
        secid = ("1." if str(code).startswith("6") else "0.") + str(code)
        data = s.fetch_json(
            "https://push2delay.eastmoney.com/api/qt/stock/get",
            {
                "secid": secid,
                "ut": s.EASTMONEY_UT,
                "fltt": 2,
                "invt": 2,
                "fields": "f57,f58,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
            },
            timeout=6,
            retries=1,
        )
        d = data.get("data") or {}
        return {
            "main_net": d.get("f62"),
            "main_pct": d.get("f184"),
            "super_net": d.get("f66"),
            "super_pct": d.get("f69"),
            "big_net": d.get("f72"),
            "big_pct": d.get("f75"),
            "mid_net": d.get("f78"),
            "mid_pct": d.get("f81"),
            "small_net": d.get("f84"),
            "small_pct": d.get("f87"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def stock_detail(code: str, minute_tail: int = 240) -> Dict[str, Any]:
    code = "".join(ch for ch in str(code) if ch.isdigit())[-6:]
    if len(code) != 6:
        raise ValueError("请输入6位A股代码")
    quotes = query_quote.fetch_realtime_quotes([code])
    quote = quotes.get(code) or {}
    minute_raw = query_quote.fetch_minute_data(code)
    minute = _parse_minute(minute_raw)
    minute_tail = max(30, min(int(minute_tail), 300))
    minute_view = minute[-minute_tail:]

    s = _load_screener()
    try:
        daily, ksource = s.fetch_kline(code, 170)
    except Exception as exc:
        daily, ksource = [], f"error:{exc}"

    ann: Dict[str, Any]
    try:
        titles = s.fetch_announcements(code, 8)
        ann = s.classify_announcement_risk(titles)
    except Exception as exc:
        ann = {"announcement_risk": "unknown", "announcement_titles": [], "error": str(exc)}

    return {
        "meta": {
            "timestamp": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "code": code,
            "purpose": "单股证据，不是交易结论",
        },
        "quote": quote,
        "flow": _stock_flow(code),
        "minute": minute_view,
        "k15": _aggregate_15m(minute),
        "daily": daily[-170:],
        "moving_averages": _ma(daily),
        "kline_source": ksource,
        "announcement": ann,
        "missing": [
            "Work首版不伪造逐笔主动买卖方向",
            "昨日同期量能需要后续增加历史分时缓存",
            "完整基本面/CAPEX/海外产业链需另行补证据",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="阿狼 × Big-A-chovy Work 数据入口")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("market", help="主要指数与均线")

    p_sector = sub.add_parser("sectors", help="行业板块排名")
    p_sector.add_argument("--top", type=int, default=30)

    p_scan = sub.add_parser("scan", help="运行Big-A候选筛选")
    p_scan.add_argument("--mode", choices=["all", "strict", "low", "watchlist"], default="all")
    p_scan.add_argument("--top", type=int, default=15)
    p_scan.add_argument("--skip-announcements", action="store_true")

    p_stock = sub.add_parser("stock", help="单股实时/分时/日K/资金/公告")
    p_stock.add_argument("code")
    p_stock.add_argument("--minute-tail", type=int, default=240)

    args = parser.parse_args()
    if args.command == "market":
        result = market_snapshot()
    elif args.command == "sectors":
        result = sector_rank(args.top)
    elif args.command == "scan":
        result = scan_candidates(args.mode, args.top, not args.skip_announcements)
    else:
        result = stock_detail(args.code, args.minute_tail)

    print(json.dumps(_sanitize(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
