"""
webui.py
─────────
零依赖 WebUI — 用 Python 自带 http.server + 单页 dashboard.html。

启动：python webui.py  或  webui.bat
访问：http://127.0.0.1:8080

API 端点：
  GET /                   → dashboard.html
  GET /api/health         → { orchestrator_alive, opend_alive, last_log_ts, uptime }
  GET /api/nav            → NAV 历史 + peak + dd_pct
  GET /api/positions      → moomoo 当前持仓（如可用）
  GET /api/trades?n=20    → 最近 N 笔 trade_log
  GET /api/log?n=100      → 当天 log 最后 N 行
  GET /api/benchmark      → 若有 signals/benchmark_report.md 则读

安全：默认只绑 127.0.0.1，仅本机可访问。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).parent
SIGNALS_DIR = SCRIPT_DIR / "signals"
LOGS_DIR    = SCRIPT_DIR / "logs"
LOCK_PATH   = SCRIPT_DIR / ".orchestrator.lock"
STATE_PATH  = SCRIPT_DIR / "trader_state.json"

# ---- 通用后台缓存 ----
# 页面刷新时优先返回上一版结果（1ms），后台线程算新值刷新缓存。
# 前端根据 refreshing 标志显示"更新中..."小图标。
_WEBUI_CACHE_DIR = SCRIPT_DIR / ".webui_cache"
_WEBUI_CACHE_DIR.mkdir(exist_ok=True)
_refresh_flag: dict[str, bool] = {}
_refresh_locks: dict[str, threading.Lock] = {}


def _cached(name: str, ttl_sec: int, compute_fn):
    """返回缓存 JSON + 元数据 (cached_at / age_sec / stale / refreshing)。
    过期时后台线程刷新，本次请求仍返回旧值（首次无缓存时同步计算）。
    """
    cache_path = _WEBUI_CACHE_DIR / f"{name}.json"
    now = time.time()
    data = None
    age_sec: float | None = None
    if cache_path.exists():
        try:
            age_sec = now - cache_path.stat().st_mtime
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            data = None
    stale = (data is None) or (age_sec is not None and age_sec > ttl_sec)

    # 后台刷新 ONLY 当有旧缓存可用时（无缓存走同步计算路径，避免重复跑）
    if stale and data is not None and not _refresh_flag.get(name):
        lock = _refresh_locks.setdefault(name, threading.Lock())

        def _bg_refresh():
            with lock:
                if _refresh_flag.get(name):
                    return
                _refresh_flag[name] = True
                try:
                    fresh = compute_fn()
                    cache_path.write_text(
                        json.dumps(fresh, ensure_ascii=False), encoding="utf-8"
                    )
                except Exception:
                    pass
                finally:
                    _refresh_flag[name] = False

        threading.Thread(target=_bg_refresh, daemon=True).start()

    if data is None:
        # 首次请求：同步计算，不然客户端会拿空 dict
        try:
            data = compute_fn()
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            age_sec = 0
            stale = False
        except Exception as e:
            return {"error": str(e), "refreshing": False, "stale": True, "age_sec": None}

    return {
        **data,
        "_meta": {
            "cached_at":  datetime.fromtimestamp(cache_path.stat().st_mtime).isoformat() if cache_path.exists() else None,
            "age_sec":    int(age_sec) if age_sec is not None else 0,
            "stale":      bool(stale),
            "refreshing": bool(_refresh_flag.get(name, False)),
        },
    }

PORT = int(os.environ.get("WEBUI_PORT", "8080"))
HOST = os.environ.get("WEBUI_HOST", "127.0.0.1")


def _trump_summary_recent3(items: list) -> dict:
    """对最近 3 条推文调 Claude CLI 出一句话概括。缓存 by post_ids sha1。非阻塞。

    返回 {"text": str|None, "state": "cached"|"generating"|"empty"|"error", "post_ids": [...]}
    - 命中缓存 → text 有值
    - 未命中且未在生成 → 启动后台线程调 claude, 返回 state=generating text=None
    - 已有其它总结在跑 → 返回 state=generating
    """
    import hashlib
    if not items:
        return {"text": None, "state": "empty", "post_ids": []}
    # 按 post_time 降序取前 3
    def _pt(it):
        return it.get("post_time", "")
    top3 = sorted(items, key=_pt, reverse=True)[:3]
    ids = [it.get("post_id", "") for it in top3]
    key = hashlib.sha1("_".join(ids).encode("utf-8")).hexdigest()[:12]
    cache_path = _WEBUI_CACHE_DIR / f"trump_summary_{key}.txt"
    if cache_path.exists():
        return {"text": cache_path.read_text(encoding="utf-8").strip(),
                "state": "cached", "post_ids": ids}

    # 未命中：启动后台线程调 Claude
    if not _refresh_flag.get(f"trump_summary_{key}"):
        def _bg():
            _refresh_flag[f"trump_summary_{key}"] = True
            try:
                from ai_prompt import query_claude_cli
                previews = "\n".join(
                    f"{i+1}. [{it.get('event_type','')}] {(it.get('preview','') or '')[:200]}"
                    for i, it in enumerate(top3)
                )
                prompt = (
                    "请用一句中文（不超过 50 字）概括下面 3 条 Trump 推文的核心内容 + 市场情绪倾向。\n"
                    "只输出概括，不要前后解释，不要 markdown。\n\n"
                    f"推文：\n{previews}\n"
                )
                out, status = query_claude_cli(prompt, timeout=60)
                if out and out.strip():
                    cache_path.write_text(out.strip(), encoding="utf-8")
            except Exception:
                pass
            finally:
                _refresh_flag[f"trump_summary_{key}"] = False
        threading.Thread(target=_bg, daemon=True).start()

    return {"text": None, "state": "generating", "post_ids": ids}


def _pid_alive(pid: int) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(0x0400, 0, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        kernel32.CloseHandle(h)
        return exit_code.value == 259
    except Exception:
        return False


def _port_open(host: str, port: int) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


def _today_log_path() -> Path:
    return LOGS_DIR / f"run_{datetime.now().strftime('%Y%m%d')}.log"


def api_health() -> dict:
    orch_pid = None
    orch_alive = False
    if LOCK_PATH.exists():
        try:
            orch_pid = int(LOCK_PATH.read_text().strip())
            orch_alive = _pid_alive(orch_pid)
        except Exception:
            pass
    opend_alive = _port_open("127.0.0.1", 11111)
    log_path = _today_log_path()
    last_log_ts = None
    if log_path.exists():
        try:
            last_log_ts = datetime.fromtimestamp(log_path.stat().st_mtime).isoformat()
        except Exception:
            pass
    return {
        "orchestrator_pid":    orch_pid,
        "orchestrator_alive":  orch_alive,
        "opend_alive":         opend_alive,
        "last_log_mtime":      last_log_ts,
        "log_path":            str(log_path),
        "now":                 datetime.now(timezone.utc).isoformat(),
    }


def api_nav(days: int = 30) -> dict:
    hist_path = SIGNALS_DIR / "nav_history.jsonl"
    if not hist_path.exists():
        return {"points": [], "peak": None, "current": None, "dd_pct": 0}
    points = []
    with open(hist_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                points.append(json.loads(line))
            except Exception:
                continue
    # 按天取最后一个
    from collections import OrderedDict
    day_last = OrderedDict()
    for p in points:
        try:
            d = p["ts"][:10]
            day_last[d] = p
        except Exception:
            continue
    tail = list(day_last.values())[-days:]
    if not tail:
        return {"points": [], "peak": None, "current": None, "dd_pct": 0}
    peak = max(p.get("peak", 0) for p in tail)
    current = tail[-1].get("nav", 0)
    dd = tail[-1].get("dd_pct", 0)
    return {
        "points":  [{"ts": p["ts"][:19], "nav": p.get("nav"), "peak": p.get("peak")}
                    for p in tail],
        "peak":    peak,
        "current": current,
        "dd_pct":  dd,
    }


def api_positions() -> dict:
    """从 trader_state.json 读缓存的 ticker state。真实 moomoo 查询太慢，不实时查。"""
    if not STATE_PATH.exists():
        return {"positions": [], "peak_nav": None}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"positions": [], "peak_nav": None}
    peak_meta = state.get("__nav_peak", {})
    positions = []
    for k, v in state.items():
        if k.startswith("__"):
            continue
        if isinstance(v, dict) and v.get("last_action"):
            positions.append({
                "ticker":         k,
                "last_action":    v.get("last_action"),
                "last_side":      v.get("last_side"),
                "last_qty":       v.get("last_qty"),
                "last_price":     v.get("last_price"),
                "last_time_utc":  v.get("last_time_utc"),
                "is_core":        v.get("is_core", False),
                "pyramid_layer":  v.get("pyramid_layer"),
                "entry_conf":     v.get("entry_conf"),
                "entry_price":    v.get("entry_price"),
                "entry_high":     v.get("entry_high"),
            })
    return {
        "positions": positions,
        "peak_nav":  peak_meta.get("peak_nav"),
        "current_nav": peak_meta.get("current_nav"),
    }


def api_trades(n: int = 20) -> dict:
    path = SIGNALS_DIR / "trade_log.jsonl"
    if not path.exists():
        return {"trades": []}
    lines = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    tail = lines[-n:]
    trades = []
    for line in reversed(tail):   # 最新在前
        try:
            trades.append(json.loads(line))
        except Exception:
            continue
    return {"trades": trades, "total": len(lines)}


def api_log(n: int = 100) -> dict:
    path = _today_log_path()
    if not path.exists():
        return {"lines": [], "path": str(path)}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        tail = [ln.rstrip() for ln in all_lines[-n:]]
        return {"lines": tail, "path": str(path), "total": len(all_lines)}
    except Exception as e:
        return {"lines": [], "path": str(path), "error": str(e)}


def api_benchmark() -> dict:
    path = SIGNALS_DIR / "benchmark_report.md"
    if not path.exists():
        return {"exists": False}
    try:
        content = path.read_text(encoding="utf-8")
        return {"exists": True, "content": content, "path": str(path),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat()}
    except Exception as e:
        return {"exists": False, "error": str(e)}


def api_hmm() -> dict:
    """HMM meta-regime 当前状态。"""
    path = SIGNALS_DIR / "hmm_state.json"
    if not path.exists():
        return {"exists": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "exists":     True,
            "label":      data.get("current_label"),
            "prob":       data.get("current_prob"),
            "state":      data.get("current_state"),
            "ts":         data.get("ts"),
            "state_probs":data.get("all_state_probs", {}),
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}


def api_signals() -> dict:
    """从今日 log 解析最新每标的信号（action / conf / regime / 共振多空数 / 价格）。"""
    import re
    path = _today_log_path()
    if not path.exists():
        return {"tickers": {}}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return {"tickers": {}}

    # 倒序扫，抓每个 ticker 最新一次的完整信号块
    #   【TICKER】价格:X.XX  RSI:X.X  量比:X.X  趋势:up/down
    #     信号: XXX 置信度:N/M 依据:XXX 行情:XXX
    #     共振: 多头(X) vs 空头(Y) → XXX
    tickers = {}
    tk_re    = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+【(\w+)】"
                          r"价格:([\d.]+)\s+RSI:([\d.]+)\s+量比:([\d.]+)\s+趋势:(\w+)")
    sig_re   = re.compile(r"信号:\s+(\S+)\s+(关注买入|买入|卖出|减仓|警示|持仓观望)\s+"
                          r"置信度:(\d+)/(\d+).*?行情:(\S+)")
    reson_re = re.compile(r"共振:\s+多头\((\d+)\)\s+vs\s+空头\((\d+)\)")

    # 反向扫更快 — 每 ticker 只留最新
    seen = set()
    for i in range(len(lines) - 1, -1, -1):
        m = tk_re.match(lines[i])
        if not m:
            continue
        tk = m.group(1)
        if tk in seen:
            continue
        seen.add(tk)
        info = {
            "ticker":    tk,
            "price":     float(m.group(2)),
            "rsi":       float(m.group(3)),
            "vol_ratio": float(m.group(4)),
            "trend":     m.group(5),
            "ts":        lines[i][:19],
        }
        # 找该 ticker 之后 6 行内的 信号 + 共振
        for j in range(i, min(i + 10, len(lines))):
            sm = sig_re.search(lines[j])
            if sm and "action" not in info:
                info["action_zh"] = sm.group(2)
                info["conf"]      = int(sm.group(3))
                info["scale"]     = int(sm.group(4))
                info["regime"]    = sm.group(5)
            rm = reson_re.search(lines[j])
            if rm and "bull_count" not in info:
                info["bull_count"] = int(rm.group(1))
                info["bear_count"] = int(rm.group(2))
        tickers[tk] = info
    return {"tickers": tickers}


def api_banners() -> dict:
    """从最新 signals/snapshot_YYYYMMDD_HHMMSS.txt 解析 Trump / Gold Macro / 期权墙 3 大 banner 概要。"""
    import re
    snapshots = sorted(SIGNALS_DIR.glob("snapshot_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not snapshots:
        return {"exists": False}
    latest = snapshots[0]
    try:
        content = latest.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"exists": False}

    banners = {"snapshot_path": str(latest.name),
                "snapshot_mtime": datetime.fromtimestamp(latest.stat().st_mtime).isoformat()}

    # Trump: "推文数 X  聚合方向 XXX  幅度 XXX  score +N"
    m = re.search(r"推文数\s+(\d+)\s+聚合方向\s+(\w+)\s+幅度\s+(\w+)\s+score\s+([+-]?\d+)", content)
    if m:
        trump = {
            "posts":     int(m.group(1)),
            "direction": m.group(2),
            "magnitude": m.group(3),
            "score":     int(m.group(4)),
            "event_counts": {},
            "breaking":    [],
        }
        # 从 aggregate_latest.json 拉每条 post 的事件分类 + 爆炸新闻
        items: list = []
        try:
            agg_path = SIGNALS_DIR / "trump_cache" / "aggregate_latest.json"
            if agg_path.exists():
                agg = json.loads(agg_path.read_text(encoding="utf-8"))
                items = agg.get("active_signals", []) or []
                # 事件类型计数
                for it in items:
                    et = it.get("event_type", "UNKNOWN")
                    trump["event_counts"][et] = trump["event_counts"].get(et, 0) + 1
                # 爆炸新闻: magnitude in large/extreme OR (非 neutral AND confidence>=7)
                MAG_RANK = {"extreme": 3, "large": 2, "medium": 1, "small": 0}
                def _is_breaking(it: dict) -> bool:
                    mag = it.get("magnitude", "")
                    dr = it.get("direction", "")
                    cf = int(it.get("confidence", 0) or 0)
                    return mag in ("large", "extreme") or (dr != "neutral" and cf >= 7)
                breaking = [it for it in items if _is_breaking(it)]
                # sort by (magnitude rank desc, confidence desc)
                breaking.sort(key=lambda x: (
                    -MAG_RANK.get(x.get("magnitude", ""), 0),
                    -int(x.get("confidence", 0) or 0),
                ))
                trump["breaking"] = [{
                    "event_type": it.get("event_type", ""),
                    "direction":  it.get("direction", ""),
                    "magnitude":  it.get("magnitude", ""),
                    "confidence": it.get("confidence", 0),
                    "tickers":    it.get("tickers_affected", []) or [],
                    "preview":    (it.get("preview", "") or "")[:180],
                    "verbatim":   (it.get("verbatim_evidence", "") or "")[:180],
                    "post_time":  it.get("post_time", ""),
                } for it in breaking[:5]]
        except Exception:
            pass
        # Claude 一句话总结（对最近 3 条推文）—— 缓存到 sha1(post_ids)，非阻塞
        trump["summary"] = _trump_summary_recent3(items)
        banners["trump"] = trump

    # Gold Macro: "综合方向: bullish   score=+2  conf=8/10"
    m = re.search(r"综合方向:\s*(\w+)\s+score=([+-]?\d+)\s+conf=(\d+)/(\d+)", content)
    if m:
        gold = {
            "direction": m.group(1),
            "score":     int(m.group(2)),
            "conf":      f"{m.group(3)}/{m.group(4)}",
            "factors":   [],
        }
        # 抓 6 因子明细：▼/▲/· 前缀 + 名称（可含空格）+ dir + weight
        # 例："▼ 实际利率           dir=bearish  w=3  value=2.43 trend=rising"
        # 例："· WTI 原油         dir=neutral  w=0  value=84.38 ..."
        # name 用非贪婪 .+? 直到遇到 dir= 之前
        factor_re = re.compile(r"^\s*([▼▲·])\s+(.+?)\s+dir=(\w+)\s+w=(\d+)(.*)$", re.MULTILINE)
        for fm in factor_re.finditer(content):
            arrow, name, direction, weight, rest = fm.group(1), fm.group(2), fm.group(3), fm.group(4), fm.group(5)
            # extract value / pct_chg / trend if present
            v_m = re.search(r"value=(\S+)", rest)
            trend_m = re.search(r"trend=(\S+)", rest)
            gold["factors"].append({
                "arrow":     arrow,
                "name":      name,
                "direction": direction,
                "weight":    int(weight),
                "value":     v_m.group(1) if v_m else None,
                "trend":     trend_m.group(1) if trend_m else None,
            })
            if len(gold["factors"]) >= 6:
                break
        banners["gold_macro"] = gold

    # 期权风险等级: low/medium/high  距下次三巫日 X天
    m = re.search(r"期权风险等级:\s*(\w+)\s*\|\s*距下次三巫日\s*(\d+)天", content)
    if m:
        banners["options_risk"] = {
            "level":              m.group(1),
            "days_to_witching":   int(m.group(2)),
        }

    return {"exists": True, **banners}


def api_oil() -> dict:
    """石油宏观 — 带 5min 后台缓存。首次同步，之后刷新页面 <10ms 返回旧值 + 后台异步刷新。"""
    return _cached("oil", ttl_sec=300, compute_fn=_compute_oil)


def _compute_oil() -> dict:
    """石油宏观 — 多因子综合。

    因子构成（借鉴机构分析框架）：
      · **WTI** (CL=F)           — 美国基准价，绝对水平
      · **Brent** (BZ=F)         — 全球基准价
      · **Brent-WTI 价差**       — 正常 $2-6；扩大 = 美国供应过剩
      · **XLE** 能源板块 ETF     — 板块 vs 大盘表现，验证油价传导
      · **USD 指数** (DX-Y.NYB)  — 美元强弱（油以美元计价，负相关）
      · **美国商业原油库存** (FRED WCESTUS1) — 库存增 = 供应过剩 = 利空
      · **地缘 tag** (Trump 24h) — 最近推文提到 oil/OPEC/Iran/Hormuz 时高亮
      · **能源公司股** — XOM (Exxon) / CVX (Chevron) 参考市场对油价的定价

    评分逻辑（-3 ~ +3 综合分）：
      · +2 if 20d ≥ +8%
      · +1 if 5d ≥ +5% 或 XLE 20d > SPY 20d + 5%
      · +1 if Brent-WTI spread 扩大 > $7（供应紧张）
      · +1 if 库存 20d 下降 > 5%
      · -1 if USD 5d > +2% (强美元压油)
      · -1 if 库存增加
    """
    import re
    import urllib.request
    import yfinance as yf
    from config import _cfg

    out = {"ts": datetime.now(timezone.utc).isoformat(), "factors": []}
    prices = {}

    # 拉 yfinance 各标的
    for tk, label in [("CL=F", "wti"), ("BZ=F", "brent"), ("XLE", "xle"),
                       ("USO", "uso"), ("XOM", "xom"), ("CVX", "cvx"),
                       ("DX-Y.NYB", "dxy"), ("SPY", "spy"), ("^OVX", "ovx")]:
        try:
            df = yf.Ticker(tk).history(period="30d", interval="1d", auto_adjust=True)
            if df.empty or len(df) < 6:
                continue
            close = df["Close"].astype(float)
            price = float(close.iloc[-1])
            pct_5d  = ((price / float(close.iloc[-6])  - 1) * 100) if len(close) >= 6 else None
            pct_20d = ((price / float(close.iloc[-21]) - 1) * 100) if len(close) >= 21 else None
            prices[label] = {"price": round(price, 2), "pct_5d": round(pct_5d, 2) if pct_5d else None,
                              "pct_20d": round(pct_20d, 2) if pct_20d else None}
        except Exception:
            continue

    score = 0

    # 因子 1: WTI 绝对涨跌
    if "wti" in prices and prices["wti"]["pct_20d"] is not None:
        w = prices["wti"]
        d = "bullish" if w["pct_20d"] >= 8 else ("bearish" if w["pct_20d"] <= -8 else
             ("bullish" if w["pct_5d"] and w["pct_5d"] >= 5 else
              ("bearish" if w["pct_5d"] and w["pct_5d"] <= -5 else "neutral")))
        wt = 2 if abs(w["pct_20d"]) >= 8 else 1
        arr = "▲" if d == "bullish" else ("▼" if d == "bearish" else "·")
        out["factors"].append({
            "arrow": arr, "name": "WTI 油价", "direction": d, "weight": wt,
            "value": f"${w['price']} (20d {w['pct_20d']:+.1f}%)",
            "hint": "美国基准油价 20 天大幅涨跌指示供需变化",
        })
        if d == "bullish": score += wt
        elif d == "bearish": score -= wt

    # 因子 2: Brent-WTI 价差
    if "brent" in prices and "wti" in prices:
        spread = prices["brent"]["price"] - prices["wti"]["price"]
        # 正常 $2-6，> $7 供应紧张，< $0 罕见
        d = "bullish" if spread > 7 else ("bearish" if spread < 1 else "neutral")
        arr = "▲" if d == "bullish" else ("▼" if d == "bearish" else "·")
        out["factors"].append({
            "arrow": arr, "name": "Brent-WTI 价差", "direction": d, "weight": 1,
            "value": f"${spread:.2f} (Brent ${prices['brent']['price']} - WTI ${prices['wti']['price']})",
            "hint": "正常 $2-6；>$7 = 供应紧张利多，接近 0 = 美国供应过剩利空",
        })
        if d == "bullish": score += 1
        elif d == "bearish": score -= 1

    # 因子 3: XLE 能源板块 vs SPY
    if "xle" in prices and "spy" in prices:
        xle_p20 = prices["xle"]["pct_20d"]
        spy_p20 = prices["spy"]["pct_20d"]
        if xle_p20 is not None and spy_p20 is not None:
            diff = xle_p20 - spy_p20
            d = "bullish" if diff >= 3 else ("bearish" if diff <= -3 else "neutral")
            arr = "▲" if d == "bullish" else ("▼" if d == "bearish" else "·")
            out["factors"].append({
                "arrow": arr, "name": "XLE 能源板块", "direction": d, "weight": 1,
                "value": f"XLE {xle_p20:+.1f}% vs SPY {spy_p20:+.1f}% (差 {diff:+.1f}pp)",
                "hint": "能源股跑赢大盘 = 市场认可油价上行；跑输 = 不信任",
            })
            if d == "bullish": score += 1
            elif d == "bearish": score -= 1

    # 因子 4: 美元指数
    if "dxy" in prices and prices["dxy"]["pct_5d"] is not None:
        dxy = prices["dxy"]
        d = "bearish" if dxy["pct_5d"] >= 2 else ("bullish" if dxy["pct_5d"] <= -2 else "neutral")
        arr = "▼" if d == "bearish" else ("▲" if d == "bullish" else "·")
        out["factors"].append({
            "arrow": arr, "name": "美元指数 DXY", "direction": d, "weight": 1,
            "value": f"{dxy['price']} (5d {dxy['pct_5d']:+.1f}%)",
            "hint": "油以美元计价，美元升值 = 油价承压。DXY 5d +2% = 利空油",
        })
        if d == "bullish": score += 1
        elif d == "bearish": score -= 1

    # 因子 5: 美国零售汽油价 (FRED GASREGW) — 需求侧代理
    try:
        key = _cfg("FRED_API_KEY", "")
        if key:
            url = (f"https://api.stlouisfed.org/fred/series/observations?"
                    f"series_id=GASREGW&api_key={key}&file_type=json"
                    f"&limit=12&sort_order=desc")
            with urllib.request.urlopen(url, timeout=8) as r:
                fred = json.loads(r.read().decode())
            obs = [o for o in fred.get("observations", []) if o.get("value") not in (".", None)]
            if len(obs) >= 5:
                latest = float(obs[0]["value"])
                # 4 周前 (weekly data)
                base = float(obs[4]["value"])
                delta_pct = (latest - base) / base * 100
                # 汽油价与油价强相关，上涨=需求旺盛/成本转嫁，下跌=需求疲软
                d = "bullish" if delta_pct >= 3 else ("bearish" if delta_pct <= -3 else "neutral")
                arr = "▲" if d == "bullish" else ("▼" if d == "bearish" else "·")
                out["factors"].append({
                    "arrow": arr, "name": "美国汽油零售价", "direction": d, "weight": 1,
                    "value": f"${latest:.2f}/gal (4周 {delta_pct:+.1f}%)",
                    "hint": "零售汽油价 = 需求端信号。上涨 3%+ = 需求强劲支撑油价 / 下跌 = 需求疲软利空",
                })
                if d == "bullish": score += 1
                elif d == "bearish": score -= 1
    except Exception:
        pass

    # 因子 6: OVX 油价波动率指数（类似 VIX 之于 SPY）
    if "ovx" in prices and prices["ovx"]["price"]:
        ovx = prices["ovx"]
        # OVX < 30 平稳，30-45 关注，> 45 高波动/恐慌
        if ovx["price"] > 45:
            d = "bearish"; note = "极高（>45），市场恐慌"
        elif ovx["price"] > 35:
            d = "neutral"; note = "偏高（35-45），关注"
        elif ovx["price"] < 25:
            d = "bullish"; note = "低（<25），市场平稳"
        else:
            d = "neutral"; note = "正常（25-35）"
        arr = "▲" if d == "bullish" else ("▼" if d == "bearish" else "·")
        out["factors"].append({
            "arrow": arr, "name": "OVX 油价波动率", "direction": d, "weight": 1,
            "value": f"{ovx['price']} · {note}",
            "hint": "OVX = CBOE 原油 ETF 波动率指数（类似 VIX）。低=平稳利多，高=恐慌利空",
        })
        if d == "bullish": score += 1
        elif d == "bearish": score -= 1

    # 因子 7: 石油类地缘政治提示（借 Trump signal，如果最近有 oil/opec/iran/hormuz mention）
    try:
        snapshots = sorted(SIGNALS_DIR.glob("snapshot_*.txt"),
                            key=lambda p: p.stat().st_mtime, reverse=True)
        if snapshots:
            content = snapshots[0].read_text(encoding="utf-8", errors="replace")
            oil_kw = re.findall(r"(oil|opec|iran|hormuz|crude|petroleum|refinery|opec\+|saudi|russia oil)",
                                 content.lower())
            n = len(oil_kw)
            if n > 0:
                out["factors"].append({
                    "arrow": "·", "name": "地缘 tag", "direction": "info", "weight": 0,
                    "value": f"snapshot 里 oil/OPEC/Iran/Hormuz 关键词 x{n}",
                    "hint": "有相关地缘讨论 → 查看 Trump signal / 新闻。此项不计入 score",
                })
    except Exception:
        pass

    # 综合方向
    if score >= 2:    out["direction"] = "bullish"
    elif score <= -2: out["direction"] = "bearish"
    else:              out["direction"] = "neutral"
    out["score"] = score

    # 简要 notes
    notes = []
    if "wti" in prices:
        p = prices["wti"]
        if p["pct_20d"] and p["pct_20d"] >= 8:
            notes.append("油价 20d 大涨 → 通胀压力上升，利好油气板块，利空高估值成长股")
        elif p["pct_20d"] and p["pct_20d"] <= -8:
            notes.append("油价 20d 大跌 → 通胀降温，利多科技 / 黄金")
        if p["pct_5d"] and p["pct_5d"] <= -5:
            notes.append("油价 5d 急跌 → 需求疲软信号 / 或供应过剩")
    if not notes:
        notes.append(f"综合 score={score:+d}，多因子分歧，观察后续")
    out["notes"] = notes
    out["price"]  = prices.get("wti", {}).get("price")
    out["pct_5d"] = prices.get("wti", {}).get("pct_5d")
    out["pct_20d"] = prices.get("wti", {}).get("pct_20d")
    out["source"] = "WTI 期货 (CL=F) 主 + 5 因子"
    return out


def api_sectors() -> dict:
    """板块级 regime — 带 5min 后台缓存。"""
    return _cached("sectors", ttl_sec=300, compute_fn=_compute_sectors)


def _compute_sectors() -> dict:
    """板块级 regime 概览 —— 用 yfinance 拉基准 ETF 最近走势，给 dashboard 板块卡。

    每个板块返回：现价 / 5d% / 20d% / trend(vs MA20) / regime 标签
    regime 判定（简版，不涉及 HMM）：
      · 5d ≤ -5% → 危机
      · 5d ≤ -2% → 弱势
      · 5d 在 ±2% 内 → 中性
      · 5d ≥ +2% → 强势
      · 5d ≥ +5% → 过热
    """
    import yfinance as yf
    SECTORS = [
        {"key": "SPY",  "zh": "大盘 S&P500",   "linked": "参考"},
        {"key": "QQQ",  "zh": "纳斯达克 100",   "linked": "TQQQ 3x"},
        {"key": "SMH",  "zh": "半导体 SMH",    "linked": "SOXL 3x / DRAM / MULL"},
        {"key": "GLD",  "zh": "黄金 GLD",     "linked": "GLD 1x"},
    ]
    out = []
    for s in SECTORS:
        try:
            df = yf.Ticker(s["key"]).history(period="30d", interval="1d", auto_adjust=True)
            if df.empty:
                continue
            close = df["Close"].astype(float)
            price = float(close.iloc[-1])
            pct_5d  = ((price / float(close.iloc[-6])  - 1) * 100) if len(close) >= 6  else None
            pct_20d = ((price / float(close.iloc[-21]) - 1) * 100) if len(close) >= 21 else None
            ma20    = float(close.tail(20).mean()) if len(close) >= 20 else None
            trend   = "up" if ma20 and price > ma20 else "down"
            dist_ma = ((price - ma20) / ma20 * 100) if ma20 else None
            # regime 综合判定：短期（5d）+ 中期（20d）+ 均线相对位置
            # 优先级：20d 深亏 → 技术熊 / 5d 深亏 → 危机 / 双正 → 强势 / 其它 → 中性
            regime = "neutral"
            regime_zh = "中性"
            if pct_20d is not None and pct_20d <= -10:
                regime, regime_zh = "bear", "技术熊"
            elif pct_5d is not None and pct_5d <= -5:
                regime, regime_zh = "crisis", "危机（单日大跌）"
            elif pct_20d is not None and pct_20d <= -5:
                regime, regime_zh = "weak", "弱势"
            elif pct_5d is not None and pct_5d <= -2:
                regime, regime_zh = "pullback", "回调"
            elif pct_5d is not None and pct_20d is not None and pct_5d >= 5 and pct_20d >= 10:
                regime, regime_zh = "overheated", "过热"
            elif pct_5d is not None and pct_20d is not None and pct_5d >= 2 and pct_20d >= 2:
                regime, regime_zh = "strong", "强势"
            out.append({
                "key":       s["key"],
                "zh":        s["zh"],
                "linked":    s["linked"],
                "price":     round(price, 2),
                "pct_5d":    round(pct_5d, 2) if pct_5d is not None else None,
                "pct_20d":   round(pct_20d, 2) if pct_20d is not None else None,
                "dist_ma20": round(dist_ma, 2) if dist_ma is not None else None,
                "trend":     trend,
                "regime":    regime,
                "regime_zh": regime_zh,
            })
        except Exception as e:
            out.append({"key": s["key"], "zh": s["zh"], "linked": s["linked"], "error": str(e)})
    return {"sectors": out, "ts": datetime.now(timezone.utc).isoformat()}


def api_ai_analysis() -> dict:
    """读最新 signals/ai_analysis_*.md 供 dashboard 展示 Claude 分析。
    覆盖：
      · ai_analysis_snapshot_<ts>.md（snap.bat / orchestrator 时间戳快照）
      · ai_analysis_morning_<date>.md / ai_analysis_review_<date>.md（每日覆盖版本）
    """
    files = sorted(SIGNALS_DIR.glob("ai_analysis_*.md"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"exists": False}
    latest = files[0]
    try:
        content = latest.read_text(encoding="utf-8")
        return {
            "exists":  True,
            "path":    latest.name,
            "mtime":   datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
            "content": content,
        }
    except Exception as e:
        return {"exists": False, "error": str(e)}


def api_option_walls_chart() -> dict:
    """三个主要指数（QQQ/SMH/GLD）最近到期日期权成交量分布 + 关键墙。
    重仓 ETF 对应的板块指数：
      · QQQ  ← TQQQ 3x 追踪
      · SMH  ← SOXL 3x / DRAM / MULL 追踪
      · GLD  ← 黄金现货
    15 min 后台缓存。
    """
    return _cached("option_walls_chart", ttl_sec=900, compute_fn=_compute_option_walls_chart)


def _compute_option_walls_chart() -> dict:
    import yfinance as yf
    TICKERS = [
        {"key": "QQQ", "zh": "纳斯达克100 QQQ", "note": "TQQQ 3x 追踪"},
        {"key": "SMH", "zh": "半导体 SMH",     "note": "SOXL 3x / DRAM / MULL 追踪"},
        {"key": "GLD", "zh": "黄金 GLD",       "note": "GLD 现货追踪"},
    ]
    out = {"ts": datetime.now(timezone.utc).isoformat(), "boards": []}
    for spec in TICKERS:
        try:
            t = yf.Ticker(spec["key"])
            expiries = list(t.options or [])
            if not expiries:
                out["boards"].append({**spec, "error": "no_option_chain"})
                continue
            # 优先 0DTE / 最近周度
            exp = expiries[0]
            ch = t.option_chain(exp)
            calls, puts = ch.calls.copy(), ch.puts.copy()
            try:
                spot = float(t.history(period="1d")["Close"].iloc[-1])
            except Exception:
                spot = float(calls["strike"].median())
            lo, hi = spot * 0.90, spot * 1.10  # ATM ±10%
            calls = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)]
            puts  = puts [(puts ["strike"] >= lo) & (puts ["strike"] <= hi)]
            calls["volume"] = calls["volume"].fillna(0)
            puts["volume"]  = puts["volume"].fillna(0)
            # 聚合每个 strike
            all_strikes = sorted(set(calls["strike"].tolist()) | set(puts["strike"].tolist()))
            dist = []
            for s in all_strikes:
                cv = int(calls[calls["strike"] == s]["volume"].sum())
                pv = int(puts [puts ["strike"] == s]["volume"].sum())
                if cv + pv < 30:
                    continue
                dist.append({"strike": float(s), "call_vol": cv, "put_vol": pv})
            # 取活跃度 top 20 后按 strike 升序
            dist.sort(key=lambda x: -(x["call_vol"] + x["put_vol"]))
            dist = sorted(dist[:20], key=lambda x: x["strike"])
            call_wall = max(dist, key=lambda x: x["call_vol"], default=None) if dist else None
            put_wall  = max(dist, key=lambda x: x["put_vol"],  default=None) if dist else None
            # Max pain
            def _max_pain(dist_list):
                if not dist_list: return None
                strikes = [d["strike"] for d in dist_list]
                best_s, best_pain = None, float("inf")
                for s in strikes:
                    total = 0.0
                    for d in dist_list:
                        if d["strike"] < s: total += d["call_vol"] * (s - d["strike"])
                        elif d["strike"] > s: total += d["put_vol"] * (d["strike"] - s)
                    if total < best_pain:
                        best_pain, best_s = total, s
                return best_s
            out["boards"].append({
                **spec,
                "spot":              round(spot, 2),
                "expiry":            exp,
                "distribution":      dist,
                "call_wall_strike":  call_wall["strike"] if call_wall else None,
                "call_wall_vol":     call_wall["call_vol"] if call_wall else None,
                "put_wall_strike":   put_wall["strike"]  if put_wall  else None,
                "put_wall_vol":      put_wall["put_vol"] if put_wall  else None,
                "max_pain":          _max_pain(dist),
                "n_strikes":         len(dist),
            })
        except Exception as e:
            out["boards"].append({**spec, "error": str(e)})
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默 http 访问日志

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, path: Path, status=200):
        if not path.exists():
            self.send_error(404, f"not found: {path.name}")
            return
        body = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parts = urlparse(self.path)
        path = parts.path
        qs = parse_qs(parts.query)
        n = int(qs.get("n", ["100"])[0])
        days = int(qs.get("days", ["30"])[0])

        try:
            if path == "/" or path == "/dashboard":
                self._html(SCRIPT_DIR / "dashboard.html")
            elif path == "/api/health":
                self._json(api_health())
            elif path == "/api/nav":
                self._json(api_nav(days=days))
            elif path == "/api/positions":
                self._json(api_positions())
            elif path == "/api/trades":
                self._json(api_trades(n=n))
            elif path == "/api/log":
                self._json(api_log(n=n))
            elif path == "/api/benchmark":
                self._json(api_benchmark())
            elif path == "/api/hmm":
                self._json(api_hmm())
            elif path == "/api/signals":
                self._json(api_signals())
            elif path == "/api/banners":
                self._json(api_banners())
            elif path == "/api/ai_analysis":
                self._json(api_ai_analysis())
            elif path == "/api/sectors":
                self._json(api_sectors())
            elif path == "/api/oil":
                self._json(api_oil())
            elif path == "/api/option_walls_chart":
                self._json(api_option_walls_chart())
            else:
                self.send_error(404, f"route not found: {path}")
        except Exception as e:
            self._json({"error": str(e)}, status=500)


def main():
    print(f"WebUI 启动于 http://{HOST}:{PORT}")
    print(f"仅本机可访问（HOST=127.0.0.1）。Ctrl+C 停止。")
    server = HTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWebUI 停止")
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
