#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only MCP data service for the 阿狼 × Big-A-chovy plugin.

This file is deliberately isolated under extensions/ so upstream Big-A-chovy
files remain untouched.  It reuses the repository's existing discovery engine
and quote helpers, and exposes four model-facing tools:

- market_snapshot
- sector_rank
- scan_candidates
- stock_detail

The service does not place orders and does not make the final trading decision.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from mcp.server import MCPServer


REPO_ROOT = Path(__file__).resolve().parents[3]
SCREEN_DIR = REPO_ROOT / "daily-stock-analysis" / "scripts"
SCREEN_FILE = SCREEN_DIR / "a_share_daily_screen.py"
TZ = ZoneInfo("Asia/Shanghai")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCREEN_DIR) not in sys.path:
    sys.path.insert(0, str(SCREEN_DIR))

from tools import query_quote  # noqa: E402


mcp = MCPServer(
    "alang-stock-data",
    instructions=(
        "只提供A股实时/快照数据、Big-A-chovy候选发现和单股明细。"
        "不自动下单，不把筛选标签当作买卖结论；最终判断由阿狼选股Skill完成。"
    ),
)


@lru_cache(maxsize=1)
def _load_screener():
    """Load the existing screener without changing its package layout."""
    module_name = "big_a_chovy_screen_cloud"
    spec = importlib.util.spec_from_file_location(module_name, SCREEN_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载筛选引擎: {SCREEN_FILE}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses and some reflection paths require the module in sys.modules.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    # Cloud environments should not probe local macOS proxy ports.
    module.set_network_mode("direct")
    return module


def _now_text() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _mean(values: Iterable[float]) -> Optional[float]:
    vals = [float(v) for v in values if _is_number(v)]
    return sum(vals) / len(vals) if vals else None


def _moving_averages(k_rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    closes = [float(r["close"]) for r in k_rows if _is_number(r.get("close"))]
    out: Dict[str, Optional[float]] = {}
    for n in (5, 10, 13, 20, 60, 144):
        out[f"ma{n}"] = round(sum(closes[-n:]) / n, 4) if len(closes) >= n else None
    return out


def _fetch_index_kline(screener: Any, secid: str, limit: int = 170) -> List[Dict[str, Any]]:
    data = screener.fetch_json(
        screener.EM_KLINE_URL,
        {
            "secid": secid,
            "ut": screener.EASTMONEY_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": 101,
            "fqt": 1,
            "end": "20500101",
            "lmt": limit,
        },
        timeout=6,
        retries=1,
    )
    rows = (data.get("data") or {}).get("klines") or []
    return screener.parse_k_rows(rows)


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


def _compact_screen_result(data: Dict[str, Any]) -> Dict[str, Any]:
    sections = (
        "strict_ultra", "trend_observation", "strict_trend", "dual_pool", "dual_pool_raw",
        "pre_intersection", "intersection_states", "capital_rank", "low_ultra", "low_trend",
        "watchlist", "sector_indices", "flow_detail", "low_open_wash",
    )
    out: Dict[str, Any] = {
        "meta": data.get("meta") or {},
        "breadth": data.get("breadth") or {},
        "market_fetch_status": data.get("market_fetch_status") or {},
        "indices": data.get("indices") or [],
        "warnings": data.get("warnings") or [],
        "errors": data.get("errors") or [],
        "announcement_errors": data.get("announcement_errors") or [],
        "announcement_check_available": data.get("announcement_check_available"),
        "announcement_unknown_codes": data.get("announcement_unknown_codes") or [],
        "has_snapshot": bool(data.get("has_snapshot")),
        "note": (
            "Big-A-chovy输出是候选发现层；A/B/C、dual_pool、intersection等标签都不是最终买卖许可。"
        ),
    }
    for section in sections:
        rows = data.get(section) or []
        if isinstance(rows, list):
            out[section] = [_compact_candidate(r) if isinstance(r, dict) else r for r in rows]
        else:
            out[section] = rows
    return out


def _run_screen(mode: str, top: int, check_announcements: bool) -> Dict[str, Any]:
    allowed = {"all", "strict", "low", "watchlist"}
    mode = (mode or "all").strip().lower()
    if mode not in allowed:
        raise ValueError(f"mode必须是 {sorted(allowed)} 之一")
    top = max(3, min(int(top), 30))

    tmp = tempfile.NamedTemporaryFile(prefix="alang_screen_", suffix=".json", delete=False)
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
            timeout=240,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "未知错误")[-4000:]
            raise RuntimeError(f"筛选引擎执行失败(returncode={proc.returncode}): {detail}")
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("筛选引擎未生成JSON结果")
        payload = json.loads(tmp_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("筛选引擎JSON结构异常")
        return _compact_screen_result(payload)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def _fetch_sector_boards() -> List[Dict[str, Any]]:
    screener = _load_screener()
    screener.set_network_mode("direct")
    rows: List[Dict[str, Any]] = []
    for page in range(1, 6):
        params = {
            "pn": page,
            "pz": 100,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:90+t:2",
            "fields": "f12,f14,f2,f3,f6,f8,f62,f104,f105,f124",
            "ut": screener.EASTMONEY_UT,
        }
        page_rows: List[Dict[str, Any]] = []
        for url in screener._rank_urls(screener.CLIST_URLS):
            try:
                data = screener.fetch_json(url, params, timeout=6, retries=1)
                page_rows = ((data.get("data") or {}).get("diff") or [])
                if page_rows:
                    break
            except Exception:
                continue
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < 100:
            break
    return rows


def _percentile_by_name(rows: List[Dict[str, Any]], key: str) -> Dict[str, float]:
    valid = [(str(r.get("name") or ""), float(r[key])) for r in rows if r.get("name") and _is_number(r.get(key))]
    if not valid:
        return {}
    ordered = sorted(valid, key=lambda x: x[1])
    n = len(ordered)
    if n == 1:
        return {ordered[0][0]: 1.0}
    return {name: idx / (n - 1) for idx, (name, _) in enumerate(ordered)}


def _parse_minute_rows(lines: List[str]) -> List[Dict[str, Any]]:
    parsed: List[Dict[str, Any]] = []
    for line in lines:
        parts = str(line).replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            item: Dict[str, Any] = {"time": parts[0], "price": float(parts[1])}
            if len(parts) >= 3:
                item["volume"] = float(parts[2])
            if len(parts) >= 4:
                item["amount"] = float(parts[3])
            parsed.append(item)
        except (TypeError, ValueError):
            continue
    return parsed


def _minute_to_index(hhmm: str) -> Optional[int]:
    if not re.fullmatch(r"\d{4}", str(hhmm)):
        return None
    h, m = int(hhmm[:2]), int(hhmm[2:])
    return h * 60 + m


def _fmt_hhmm(minute_index: int) -> str:
    return f"{minute_index // 60:02d}:{minute_index % 60:02d}"


def _aggregate_15m(minutes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[int, int], List[Dict[str, Any]]] = defaultdict(list)
    for item in minutes:
        idx = _minute_to_index(str(item.get("time") or ""))
        if idx is None:
            continue
        if 570 <= idx <= 690:  # 09:30-11:30
            base = 570
            session = 0
        elif 780 <= idx <= 900:  # 13:00-15:00
            base = 780
            session = 1
        else:
            continue
        bucket = (idx - base) // 15
        buckets[(session, bucket)].append(item)

    out: List[Dict[str, Any]] = []
    for (session, bucket), items in sorted(buckets.items()):
        prices = [x["price"] for x in items if _is_number(x.get("price"))]
        if not prices:
            continue
        base = 570 if session == 0 else 780
        start = base + bucket * 15
        row: Dict[str, Any] = {
            "time": _fmt_hhmm(start),
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
        }
        # Tencent minute volume/amount are normally cumulative.  Keep the
        # delta only when the bucket is internally monotonic; otherwise omit.
        vols = [x.get("volume") for x in items if _is_number(x.get("volume"))]
        amts = [x.get("amount") for x in items if _is_number(x.get("amount"))]
        if len(vols) >= 2 and vols[-1] >= vols[0]:
            row["volume_delta"] = vols[-1] - vols[0]
        if len(amts) >= 2 and amts[-1] >= amts[0]:
            row["amount_delta"] = amts[-1] - amts[0]
        out.append(row)
    return out


def _estimate_vwap(minutes: List[Dict[str, Any]], reference_price: Optional[float]) -> Optional[float]:
    if not minutes:
        return None
    last = minutes[-1]
    vol, amount = last.get("volume"), last.get("amount")
    if not _is_number(vol) or not _is_number(amount) or float(vol) <= 0:
        return None
    candidates = [float(amount) / float(vol), float(amount) / (float(vol) * 100.0)]
    if _is_number(reference_price) and float(reference_price) > 0:
        price = float(reference_price)
        plausible = [v for v in candidates if price * 0.5 <= v <= price * 1.5]
        if plausible:
            return round(min(plausible, key=lambda v: abs(v - price)), 4)
    return None


@mcp.tool()
def market_snapshot() -> Dict[str, Any]:
    """获取主要A股指数的实时快照和5/10/13/20/60/144日均线。

    这是快速市场入口，不执行全市场股票分页扫描。需要全市场宽度时，使用
    scan_candidates，其返回的 breadth 才是完整筛选快照口径。
    """
    screener = _load_screener()
    screener.set_network_mode("direct")
    index_defs = [
        ("上证指数", "1.000001", "000001"),
        ("深证成指", "0.399001", "399001"),
        ("沪深300", "1.000300", "000300"),
        ("科创50", "1.000688", "000688"),
    ]
    params = {
        "fltt": 2,
        "invt": 2,
        "fields": "f12,f14,f2,f3,f4,f6,f104,f105,f106,f124",
        "secids": ",".join(secid for _, secid, _ in index_defs),
        "ut": screener.EASTMONEY_UT,
    }
    live_rows: List[Dict[str, Any]] = []
    for url in screener._rank_urls(screener.INDEX_URLS):
        try:
            data = screener.fetch_json(url, params, timeout=6, retries=1)
            live_rows = (data.get("data") or {}).get("diff") or []
            if live_rows:
                break
        except Exception:
            continue
    live_by_code = {str(x.get("f12")): x for x in live_rows}

    indices: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for fallback_name, secid, code in index_defs:
        raw = live_by_code.get(code, {})
        k_rows: List[Dict[str, Any]] = []
        try:
            k_rows = _fetch_index_kline(screener, secid, 170)
        except Exception as exc:
            warnings.append(f"{fallback_name}日K获取失败: {type(exc).__name__}")
        indices.append({
            "code": code,
            "name": raw.get("f14") or fallback_name,
            "price": raw.get("f2"),
            "change": raw.get("f3"),
            "change_abs": raw.get("f4"),
            "amount": raw.get("f6"),
            "up_count": raw.get("f104"),
            "down_count": raw.get("f105"),
            "flat_count": raw.get("f106"),
            "provider_timestamp": raw.get("f124"),
            "ma": _moving_averages(k_rows),
            "recent_kline": k_rows[-12:],
        })
    return {
        "timestamp": _now_text(),
        "indices": indices,
        "warnings": warnings,
        "breadth_scope": "指数接口成分统计；完整全市场宽度请读取scan_candidates.breadth",
        "same_time_amount": None,
        "same_time_amount_note": "首版尚未持久化昨日同期成交额，不能伪造同比口径",
        "source": "东方财富指数实时接口 + 东方财富指数日K",
    }


@mcp.tool()
def sector_rank(limit: int = 25) -> Dict[str, Any]:
    """扫描行业板块并返回涨幅、成交额、主力净额和上涨家数。

    recognition_score是融合辅助分，只用于缩小研究范围：涨幅35%、成交额25%、
    主力净额25%、上涨家数占比15%的横截面百分位组合。它不是阿狼原话，也不是买入许可。
    """
    limit = max(5, min(int(limit), 60))
    raw_rows = _fetch_sector_boards()
    rows: List[Dict[str, Any]] = []
    for r in raw_rows:
        name = str(r.get("f14") or "").strip()
        if not name:
            continue
        up = r.get("f104")
        down = r.get("f105")
        denom = (float(up) if _is_number(up) else 0.0) + (float(down) if _is_number(down) else 0.0)
        rows.append({
            "code": r.get("f12"),
            "name": name,
            "price": r.get("f2"),
            "change": r.get("f3"),
            "amount": r.get("f6"),
            "turnover": r.get("f8"),
            "main_net": r.get("f62"),
            "up_count": up,
            "down_count": down,
            "adv_ratio": round(float(up) / denom, 4) if denom > 0 and _is_number(up) else None,
            "provider_timestamp": r.get("f124"),
        })

    p_change = _percentile_by_name(rows, "change")
    p_amount = _percentile_by_name(rows, "amount")
    p_flow = _percentile_by_name(rows, "main_net")
    p_breadth = _percentile_by_name(rows, "adv_ratio")
    for r in rows:
        name = r["name"]
        parts = [
            (0.35, p_change.get(name)),
            (0.25, p_amount.get(name)),
            (0.25, p_flow.get(name)),
            (0.15, p_breadth.get(name)),
        ]
        available = [(w, v) for w, v in parts if v is not None]
        if available:
            total_w = sum(w for w, _ in available)
            r["recognition_score"] = round(100 * sum(w * v for w, v in available) / total_w, 1)
        else:
            r["recognition_score"] = None

    rows.sort(key=lambda x: (x.get("recognition_score") is not None, x.get("recognition_score") or -1), reverse=True)
    return {
        "timestamp": _now_text(),
        "sectors": rows[:limit],
        "total_sectors": len(rows),
        "score_note": "融合辅助分，不替代市场/板块/个股的最终量价判断",
        "source": "东方财富行业板块实时接口",
    }


@mcp.tool()
def scan_candidates(mode: str = "all", top: int = 15, check_announcements: bool = True) -> Dict[str, Any]:
    """运行仓库原有Big-A-chovy筛选引擎并返回压缩后的候选证据。

    mode支持 all / strict / low / watchlist。所有筛选标签均为发现层信号，
    最终是否可做必须交给阿狼选股Skill结合大盘、板块、趋势阶段和量价判断。
    """
    return _run_screen(mode=mode, top=top, check_announcements=check_announcements)


@mcp.tool()
def stock_detail(code: str, minute_limit: int = 120) -> Dict[str, Any]:
    """获取单股实时行情、五档、分时、15分钟聚合、日K均线和公告风险。

    适合在候选池缩小后做二次核验。首版不伪造缺失的逐笔成交、昨日同期量能或完整基本面。
    """
    code = re.sub(r"\D", "", str(code or ""))[-6:]
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码必须包含6位数字")
    minute_limit = max(15, min(int(minute_limit), 240))

    screener = _load_screener()
    screener.set_network_mode("direct")
    quotes = query_quote.fetch_realtime_quotes([code])
    quote = quotes.get(code) or {}

    raw_minutes = query_quote.fetch_minute_data(code)
    parsed_minutes = _parse_minute_rows(raw_minutes)
    ref_price = quote.get("price") if _is_number(quote.get("price")) else None
    vwap = _estimate_vwap(parsed_minutes, ref_price)

    k_rows: List[Dict[str, Any]] = []
    k_source = ""
    warnings: List[str] = []
    try:
        k_rows, k_source = screener.fetch_kline(code, 170)
    except Exception as exc:
        warnings.append(f"日K获取失败: {type(exc).__name__}")

    announcements: Dict[str, Any] = {
        "risk_status": "unknown",
        "announcement_titles": [],
        "announcement_keywords": [],
    }
    try:
        titles = screener.fetch_announcements(code, page_size=8)
        announcements = screener.classify_announcement_risk(titles)
    except Exception as exc:
        warnings.append(f"公告查询失败: {type(exc).__name__}")

    return {
        "timestamp": _now_text(),
        "code": code,
        "quote": quote,
        "estimated_vwap": vwap,
        "vwap_note": "由腾讯分时累计成交额/量估算；若单位无法自洽则返回null",
        "minute": parsed_minutes[-minute_limit:],
        "bars_15m": _aggregate_15m(parsed_minutes),
        "daily_ma": _moving_averages(k_rows),
        "daily_kline": k_rows[-40:],
        "kline_source": k_source,
        "announcements": announcements,
        "warnings": warnings,
        "limitations": [
            "逐笔主动买卖尚未云端化，五档仅为静态快照",
            "昨日同期成交量/成交额尚未持久化，不能伪造同期比较",
            "完整基本面与行业CAPEX等仍需后续工具或外部实时资料补充",
            "若该股来自scan_candidates，应同时使用其中的主力/超大单/5分钟/15分钟资金字段",
        ],
        "source": "腾讯实时/分时 + 东方财富/新浪日K + 东方财富公告",
    }


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
