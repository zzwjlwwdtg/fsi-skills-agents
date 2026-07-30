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


def api_supply_chain(ticker: str) -> dict:
    """标的上下游供应链关联。Claude 生成（缓存 7 天），可选 FMP 交叉验证 peers。"""
    ticker = (ticker or "").upper().strip()
    if not ticker or len(ticker) > 8 or not ticker.replace(".", "").replace("-", "").isalnum():
        return {"error": "invalid ticker"}
    # 14 天 TTL —— 供应链变动慢，无必要频繁调 Claude（用户 quota 保护）
    return _cached(f"supply_chain_{ticker}", ttl_sec=14 * 24 * 3600,
                    compute_fn=lambda: _compute_supply_chain(ticker))


def _compute_supply_chain(ticker: str) -> dict:
    """调 Claude 生成结构化供应链 JSON，可选 FMP 交叉验证 peers。"""
    try:
        from ai_prompt import query_claude_cli
    except Exception as e:
        return {"error": f"ai_prompt import: {e}", "ticker": ticker}

    prompt = (
        "你是股票供应链分析师。为下面 ticker 输出严格 JSON（无 markdown 围栏、无 preamble、无 comment）：\n\n"
        f"Ticker: {ticker}\n\n"
        "输出格式（严格 UTF-8 JSON, keys 用英文, values 中文说明）：\n"
        "{\n"
        '  "sector":     "行业中文名（如 半导体设计/云计算/新能源车）",\n'
        '  "business":   "1 句核心业务说明",\n'
        '  "upstream":   [{"name":"供应商公司", "ticker":"股票代码或 null", "note":"提供什么", "weight":0-100 相对重要度, "confidence":"high|medium|low"}],\n'
        '  "downstream": [{"name":"客户公司",   "ticker":"股票代码或 null", "note":"买什么用途", "weight":0-100, "confidence":"high|medium|low"}],\n'
        '  "peers":      [{"name":"同行竞争公司","ticker":"股票代码或 null", "note":"竞争方向", "confidence":"high|medium|low"}]\n'
        "}\n\n"
        "要求:\n"
        "1. upstream/downstream 各 3-6 项，按 weight 从高到低\n"
        "2. peers 3-5 项\n"
        "3. ticker 字段：仅当在美股/港股/日股/A股主板上市时给出（如 TSM/2330.TW/6752.T），否则填 null\n"
        "4. weight 是你对该关系相对重要度的估计（营收占比或战略重要度），不是精确数字\n"
        "5. confidence: high=10-K 明确披露 / medium=行业公开信息 / low=推测\n"
        "6. 若是 ETF 或杠杆产品，视为其追踪的标的（TQQQ→QQQ 前十大 / SOXL→半导体链）\n"
        "7. 严格只输出 JSON 对象，不要 ``` 围栏\n"
    )
    out, status = query_claude_cli(prompt, timeout=90)
    if not out:
        return {"error": f"claude {status}", "ticker": ticker}
    # 去除潜在的 markdown 围栏
    import re
    txt = out.strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```\s*$", "", txt)
    try:
        data = json.loads(txt)
    except Exception as e:
        return {"error": f"json parse: {e}", "raw": out[:500], "ticker": ticker}

    result = {
        "ticker":     ticker,
        "sector":     data.get("sector", ""),
        "business":   data.get("business", ""),
        "upstream":   data.get("upstream", []) or [],
        "downstream": data.get("downstream", []) or [],
        "peers":      data.get("peers", []) or [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":     "claude",
    }

    # 可选：FMP 交叉验证 peers（免费 250 calls/day）
    try:
        fmp_key = _cfg_helper("FMP_API_KEY", "")
        if fmp_key:
            import urllib.request
            url = f"https://financialmodelingprep.com/api/v3/stock/peers?symbol={ticker}&apikey={fmp_key}"
            with urllib.request.urlopen(url, timeout=6) as r:
                fmp_data = json.loads(r.read().decode())
            fmp_peers = set()
            if isinstance(fmp_data, list) and fmp_data:
                fmp_peers = set(p.upper() for p in (fmp_data[0].get("peersList") or []))
            result["fmp_peers"] = sorted(fmp_peers)
            # 标记 Claude 输出的 peers 是否被 FMP 覆盖
            for p in result["peers"]:
                p_tk = (p.get("ticker") or "").upper()
                p["fmp_verified"] = bool(p_tk and p_tk in fmp_peers)
            result["source"] = "claude+fmp"
    except Exception as e:
        result["fmp_error"] = str(e)[:100]

    return result


def api_supply_chain_graph(ticker: str, depth: int = 2) -> dict:
    """多层供应链图（BFS）。返回 nodes/edges 供 D3 蜘蛛网渲染。

    每条边带 `reason`（来自 Claude 输出的 note），供 hover 显示。
    layer 记录节点到 root 的最短跳数。未 cache 的 ticker 触发后台 Claude 拉取，
    本次请求返 `pending: [...]`，前端可稍后再请求补图。
    """
    import threading
    root = (ticker or "").upper().strip()
    if not root:
        return {"error": "invalid ticker"}
    max_depth = max(1, min(int(depth or 2), 3))  # 限 1-3 层

    nodes: dict = {}
    edges: list = []
    seen_edges: set = set()
    visited: set = {root}

    def _add_node(nid, **kw):
        if nid in nodes:
            # 记住最小 layer
            if kw.get("layer", 99) < nodes[nid].get("layer", 99):
                nodes[nid]["layer"] = kw["layer"]
            return
        nodes[nid] = {"id": nid, **kw}

    _add_node(root, name=root, ticker=root, layer=0, group="center", confidence="high")

    queue = [(root, 0)]
    pending: list = []
    while queue:
        cur, layer = queue.pop(0)
        if layer >= max_depth:
            continue
        cache_path = _WEBUI_CACHE_DIR / f"supply_chain_{cur}.json"
        if not cache_path.exists():
            if cur != root and cur not in pending:
                pending.append(cur)
                # 后台触发 Claude 拉取（非阻塞）
                threading.Thread(
                    target=lambda t=cur: _compute_supply_chain(t), daemon=True
                ).start()
            continue
        try:
            sc = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "error" in sc:
            continue

        for kind, items in (
            ("supply",   sc.get("upstream",   []) or []),
            ("customer", sc.get("downstream", []) or []),
            ("peer",     sc.get("peers",      []) or []),
        ):
            for x in items:
                tk = (x.get("ticker") or "").upper().strip()
                if not tk:
                    continue  # 跳过没有 ticker 的（无法多跳）
                grp = {"supply": "up", "customer": "down", "peer": "peer"}[kind]
                _add_node(tk, name=x.get("name"), ticker=tk, layer=layer + 1,
                          group=grp, confidence=x.get("confidence"),
                          weight=x.get("weight"))
                # 边方向: supply = supplier → consumer, customer = seller → customer, peer 双向（用 target 做展示）
                src, tgt = (tk, cur) if kind == "supply" else (cur, tk)
                key = (src, tgt, kind)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({
                        "source":     src,
                        "target":     tgt,
                        "reason":     x.get("note", ""),
                        "kind":       kind,
                        "confidence": x.get("confidence"),
                    })
                if tk not in visited:
                    visited.add(tk)
                    queue.append((tk, layer + 1))

    return {
        "root":    root,
        "depth":   max_depth,
        "nodes":   list(nodes.values()),
        "edges":   edges,
        "pending": pending,   # 前端可延迟重试补图
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _cfg_helper(key: str, default: str = "") -> str:
    """Wrapper for config._cfg to avoid import-order issues."""
    try:
        from config import _cfg
        return _cfg(key, default)
    except Exception:
        return default


TICKER_TO_FUNDAMENTAL_STOCK = {
    "TQQQ": "NVDA",   # 3x QQQ, 用 QQQ 最大权重股 NVDA 代表
    "SOXL": "NVDA",   # 3x SOX, 用半导体龙头 NVDA
    "DRAM": "MU",     # Memory ETF, MU 是锚
    "MULL": "MU",     # 2x MU
    "GLD":  None,     # 大宗商品 ETF, 无 fundamentals
    "TSLA": "TSLA",
    "KLAC": "KLAC",
    "AMAT": "AMAT",
    "GOOGL":"GOOGL",
    "NVDA": "NVDA",
    "MSFT": "MSFT",
    "AAPL": "AAPL",
    # 日股（东证）：仅基本面+供应链，无期权，不进 orchestrator scan
    "TDK":      "6762.T",   # TDK — 电子元器件/固态电池/HDD磁头，AAPL/NVDA 供应链
    "KIOXIA":   "285A.T",   # キオクシア — NAND 闪存全球#2（前东芝存储），2024-12 IPO
    "FUJIKURA": "5803.T",   # 藤倉 — 光纤/海底电缆/AI 数据中心互联概念
}

# 日股关注列表（不参与 orchestrator scan，只在 dashboard 单独展示）
JP_WATCH_LIST = [
    {"ticker": "TDK",      "symbol": "6762.T", "name_zh": "TDK",      "name_en": "TDK",
     "thesis": "电子元器件龙头 · Apple/NVDA 供应链 · MLCC + 固态电池 + HDD 磁头 + 无线充电"},
    {"ticker": "KIOXIA",   "symbol": "285A.T", "name_zh": "铠侠",     "name_en": "Kioxia",
     "thesis": "NAND 闪存全球#2 · 前东芝存储 · 2024-12 IPO · Data-center SSD + Client SSD"},
    {"ticker": "FUJIKURA", "symbol": "5803.T", "name_zh": "藤仓",     "name_en": "Fujikura",
     "thesis": "光纤/海底电缆 · AI 数据中心光互联需求爆发 · NVDA GPU 集群互联受益股"},
]


def api_jp_watch() -> dict:
    """日股关注列表当前行情（不进 orchestrator scan）。5 min 缓存。"""
    return _cached("jp_watch", ttl_sec=300, compute_fn=_compute_jp_watch)


def _compute_jp_watch() -> dict:
    """3 只日股：完整技术栈（RSI/MA/BB/MACD/ADX/CCI/PSAR-lite/量比 + 共振）+ 一目均衡表。"""
    import yfinance as yf
    import pandas as pd
    import numpy as np
    out = {"ts": datetime.now(timezone.utc).isoformat(), "tickers": []}
    for entry in JP_WATCH_LIST:
        try:
            t = yf.Ticker(entry["symbol"])
            # 6 月足够算 Ichimoku 52 期 + Kijun 26 期 + 观察 60 天
            h = t.history(period="6mo", auto_adjust=True)
            if h.empty or len(h) < 55:
                out["tickers"].append({**entry, "error": f"insufficient bars ({len(h)})"})
                continue
            close = h["Close"].astype(float)
            high  = h["High"].astype(float)
            low   = h["Low"].astype(float)
            vol   = h["Volume"].astype(float)
            price = float(close.iloc[-1])
            prev  = float(close.iloc[-2])
            pct_1d = ((price / prev) - 1) * 100
            pct_5d = ((price / float(close.iloc[-6])) - 1) * 100 if len(close) >= 6 else None

            # ── RSI(14) ──
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss.replace(0, 1e-9)
            rsi_val = float((100 - 100 / (1 + rs)).iloc[-1])

            # ── MA5/20/50 ──
            ma5  = float(close.rolling(5).mean().iloc[-1])
            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None

            # ── Bollinger(20, 2σ) ──
            bb_m = close.rolling(20).mean()
            bb_s = close.rolling(20).std()
            bb_up = float((bb_m + 2 * bb_s).iloc[-1])
            bb_dn = float((bb_m - 2 * bb_s).iloc[-1])
            bb_pct_b = (price - bb_dn) / (bb_up - bb_dn) if bb_up > bb_dn else 0.5

            # ── MACD(12,26,9) ──
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            macd_dif = float(macd_line.iloc[-1])
            macd_dea = float(signal_line.iloc[-1])

            # ── ADX(14) ──
            up_move   = high.diff()
            down_move = -low.diff()
            plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0)
            minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0)
            tr1 = high - low
            tr2 = (high - close.shift()).abs()
            tr3 = (low - close.shift()).abs()
            tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().replace(0, 1e-9)
            plus_di  = 100 * plus_dm.rolling(14).mean()  / atr
            minus_di = 100 * minus_dm.rolling(14).mean() / atr
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
            adx_val = float(dx.rolling(14).mean().iloc[-1])

            # ── CCI(20) ──
            tp = (high + low + close) / 3
            sma_tp = tp.rolling(20).mean()
            mad = tp.rolling(20).apply(lambda x: (x - x.mean()).abs().mean(), raw=False)
            cci_val = float(((tp - sma_tp) / (0.015 * mad.replace(0, 1e-9))).iloc[-1])

            # ── 量比 ──
            vol_avg = float(vol.tail(20).mean())
            vol_ratio = float(vol.iloc[-1]) / vol_avg if vol_avg else 1

            # ── 一目均衡表 Ichimoku ──
            # 転換線 Tenkan(9), 基準線 Kijun(26), Senkou A/B(52), 遅行 = 当前价 推 26 天前
            tenkan_series   = (high.rolling(9).max() + low.rolling(9).min()) / 2
            kijun_series    = (high.rolling(26).max() + low.rolling(26).min()) / 2
            senkou_a_series = (tenkan_series + kijun_series) / 2
            senkou_b_series = (high.rolling(52).max() + low.rolling(52).min()) / 2
            tenkan   = float(tenkan_series.iloc[-1])
            kijun    = float(kijun_series.iloc[-1])
            senkou_a = float(senkou_a_series.iloc[-1])
            senkou_b = float(senkou_b_series.iloc[-1])
            cloud_top = max(senkou_a, senkou_b)
            cloud_bot = min(senkou_a, senkou_b)
            if price > cloud_top:
                ichi_pos, ichi_dir = "云上", "bullish"
            elif price < cloud_bot:
                ichi_pos, ichi_dir = "云下", "bearish"
            else:
                ichi_pos, ichi_dir = "云中", "neutral"
            cloud_color = "bullish" if senkou_a > senkou_b else "bearish"
            tk_cross = "金叉" if tenkan > kijun else "死叉"

            # ── 共振（bull/bear count）──
            bull, bear = 0, 0
            reasons_bull, reasons_bear = [], []
            def _add(cond, label, side):
                nonlocal bull, bear
                if cond:
                    if side == 'b': bull += 1; reasons_bull.append(label)
                    else: bear += 1; reasons_bear.append(label)
            _add(price > ma20, "价格站上MA20", 'b')
            _add(price < ma20, "价格跌破MA20", 's')
            if ma50:
                _add(ma20 > ma50, "均线多排 MA20>MA50", 'b')
                _add(ma20 < ma50, "均线空排 MA20<MA50", 's')
            _add(rsi_val < 30, f"RSI 超卖 {rsi_val:.0f}", 'b')
            _add(rsi_val > 70, f"RSI 超买 {rsi_val:.0f}", 's')
            _add(bb_pct_b < 0.1, "跌破布林下轨", 'b')
            _add(bb_pct_b > 0.9, "冲破布林上轨", 's')
            _add(macd_dif > macd_dea and macd_dif > 0, "MACD 多头零轴上", 'b')
            _add(macd_dif < macd_dea and macd_dif < 0, "MACD 空头零轴下", 's')
            _add(cci_val < -100, "CCI 超卖", 'b')
            _add(cci_val > 100, "CCI 超买", 's')
            _add(ichi_dir == "bullish", "一目 云上", 'b')
            _add(ichi_dir == "bearish", "一目 云下", 's')
            _add(tk_cross == "金叉" and price > kijun, "转换>基准 (金叉)", 'b')
            _add(tk_cross == "死叉" and price < kijun, "转换<基准 (死叉)", 's')

            # 简单 action
            if bull - bear >= 3 and rsi_val < 40: action = "关注买入"
            elif bull - bear >= 3: action = "偏多"
            elif bear - bull >= 3 and rsi_val > 60: action = "警示"
            elif bear - bull >= 3: action = "偏空"
            else: action = "观望"

            trend = "up" if price > ma20 else "down"

            # ── 时间序列（供 SVG 画 Ichimoku 云图，最后 90 天）──
            N = min(90, len(close))
            series_close   = close.tail(N).tolist()
            series_tenkan  = tenkan_series.tail(N).tolist()
            series_kijun   = kijun_series.tail(N).tolist()
            series_span_a  = senkou_a_series.tail(N).tolist()
            series_span_b  = senkou_b_series.tail(N).tolist()

            out["tickers"].append({
                **entry,
                "price":     round(price, 2),
                "pct_1d":    round(pct_1d, 2),
                "pct_5d":    round(pct_5d, 2) if pct_5d is not None else None,
                "rsi":       round(rsi_val, 1),
                "ma20":      round(ma20, 2),
                "ma50":      round(ma50, 2) if ma50 else None,
                "bb_pct_b":  round(bb_pct_b * 100, 1),
                "macd_dif":  round(macd_dif, 2),
                "macd_dea":  round(macd_dea, 2),
                "adx":       round(adx_val, 1),
                "cci":       round(cci_val, 1),
                "vol_ratio": round(vol_ratio, 2),
                "trend":     trend,
                "bull_count": bull, "bear_count": bear,
                "reasons_bull": reasons_bull, "reasons_bear": reasons_bear,
                "action_zh": action,
                "ichimoku": {
                    "tenkan":   round(tenkan, 2),
                    "kijun":    round(kijun, 2),
                    "senkou_a": round(senkou_a, 2),
                    "senkou_b": round(senkou_b, 2),
                    "position": ichi_pos,       # 云上/云中/云下
                    "direction": ichi_dir,
                    "cloud_color": cloud_color, # 云的颜色（红=空 / 绿=多）
                    "tk_cross": tk_cross,
                },
                "series": {
                    "close":  [round(float(v), 2) for v in series_close],
                    "tenkan": [round(float(v), 2) if v == v else None for v in series_tenkan],
                    "kijun":  [round(float(v), 2) if v == v else None for v in series_kijun],
                    "span_a": [round(float(v), 2) if v == v else None for v in series_span_a],
                    "span_b": [round(float(v), 2) if v == v else None for v in series_span_b],
                },
                "currency": "JPY",
            })
        except Exception as e:
            out["tickers"].append({**entry, "error": str(e)[:100]})
    return out


def api_fundamentals(ticker: str, period: str = 'year') -> dict:
    """4 个基本面指标：CROIC / Piotroski F / 金融借款 / 现金周转循环。

    period='year'    → 4 年年度（长线视角，稳）， TTL 30 天
    period='quarter' → 8 季季度（波段视角，抓拐点），TTL 15 天
    ETF 映射到代表单股（TQQQ/SOXL→NVDA, DRAM/MULL→MU）。
    """
    tk = (ticker or "").upper().strip()
    period = 'quarter' if period == 'quarter' else 'year'
    stock = TICKER_TO_FUNDAMENTAL_STOCK.get(tk, tk)
    if stock is None:
        return {"ticker": tk, "error": "no_fundamentals_for_this_type"}
    ttl = 15 * 24 * 3600 if period == 'quarter' else 30 * 24 * 3600
    return _cached(f"fundamentals_{tk}_{period}", ttl_sec=ttl,
                    compute_fn=lambda: _compute_fundamentals(tk, stock, period))


def _compute_fundamentals(tk: str, stock: str, period: str = 'year') -> dict:
    """从 yfinance 拉财报算 4 指标。period=year|quarter"""
    import yfinance as yf
    try:
        t = yf.Ticker(stock)
        if period == 'quarter':
            inc = t.quarterly_income_stmt
            bal = t.quarterly_balance_sheet
            cf  = t.quarterly_cashflow
            piotroski_lag = 4   # YoY 同季对比（避免季节性），如 Q3'25 vs Q3'24
            annualize     = 4   # 季度 CROIC × 4 = 年化，可比
            days_factor   = 91.25   # 一季度 ≈ 91 天
        else:
            inc = t.income_stmt
            bal = t.balance_sheet
            cf  = t.cashflow
            piotroski_lag = 1
            annualize     = 1
            days_factor   = 365
        if inc.empty or bal.empty or cf.empty:
            return {"ticker": tk, "source": stock, "period": period,
                    "error": f"no {period} financial statements from yfinance"}

        # yfinance 返 columns=日期（最近在左），rows=科目。倒序让最老在左
        def _get(df, keys, default=0):
            """按候选 key 列表查行，取所有列返 list（老 → 新）"""
            for k in keys:
                if k in df.index:
                    vals = list(reversed(df.loc[k].tolist()))
                    return [float(v) if v == v else 0 for v in vals]
            return [default] * len(df.columns)

        # Period 标签: year → "2025" / quarter → "Q3'25"
        def _fmt(col):
            if period == 'quarter':
                q = (col.month - 1) // 3 + 1
                return f"Q{q}'{str(col.year)[2:]}"
            return str(col.year)
        years = [_fmt(c) for c in reversed(inc.columns)]

        revenue      = _get(inc, ["Total Revenue", "TotalRevenue"])
        cogs         = _get(inc, ["Cost Of Revenue", "CostOfRevenue"])
        net_income   = _get(inc, ["Net Income", "NetIncome"])
        gross        = _get(inc, ["Gross Profit", "GrossProfit"])

        total_assets      = _get(bal, ["Total Assets", "TotalAssets"])
        total_equity      = _get(bal, ["Total Equity Gross Minority Interest", "StockholdersEquity",
                                       "Total Stockholder Equity"])
        current_assets    = _get(bal, ["Current Assets", "CurrentAssets"])
        current_liab      = _get(bal, ["Current Liabilities", "CurrentLiabilities"])
        st_debt           = _get(bal, ["Current Debt", "Short Long Term Debt", "ShortLongTermDebt",
                                       "CurrentDebt"])
        lt_debt           = _get(bal, ["Long Term Debt", "LongTermDebt"])
        cash              = _get(bal, ["Cash And Cash Equivalents", "CashAndCashEquivalents"])
        inventory         = _get(bal, ["Inventory"])
        ar                = _get(bal, ["Accounts Receivable", "AccountsReceivable"])
        ap                = _get(bal, ["Accounts Payable", "AccountsPayable"])
        shares_out        = _get(bal, ["Ordinary Shares Number", "Share Issued", "ShareIssued"])

        ocf  = _get(cf, ["Operating Cash Flow", "OperatingCashFlow", "Total Cash From Operating Activities"])
        capex = _get(cf, ["Capital Expenditure", "CapitalExpenditure", "CapitalExpenditures"])

        n = len(years)

        def _safe_div(a, b, default=None):
            return (a / b) if b else default

        # 1. CROIC = FCF / IC（%）—— 季度用 × 4 年化，可与年度比较
        croic = []
        for i in range(n):
            fcf = ocf[i] - abs(capex[i])
            ic  = (st_debt[i] + lt_debt[i]) + total_equity[i] - cash[i]
            v = _safe_div(fcf, ic)
            croic.append(round(v * annualize * 100, 2) if v is not None else None)

        # 2. 金融借款 = ST + LT debt（$M）—— point-in-time, 无 period 调整
        fin_debt = [round((st_debt[i] + lt_debt[i]) / 1e6, 1) for i in range(n)]

        # 3. 现金周转循环 = DIO + DSO - DPO（天）—— 用对应期间天数
        ccc = []
        for i in range(n):
            dio = _safe_div(inventory[i], cogs[i], 0)
            dso = _safe_div(ar[i], revenue[i], 0)
            dpo = _safe_div(ap[i], cogs[i], 0)
            v = (dio + dso - dpo) * days_factor if all(x is not None for x in (dio, dso, dpo)) else None
            ccc.append(round(v, 1) if v is not None else None)

        # 4. Piotroski F-Score（0-9）
        # year 模式: 比较前一年 (lag=1)
        # quarter 模式: YoY 同季对比 (lag=4)，避免季节性
        piotroski = [None] * min(piotroski_lag, n)  # 前 lag 期无对比
        for i in range(piotroski_lag, n):
            score = 0
            j = i - piotroski_lag  # 对比期
            # a) profitability
            score += 1 if net_income[i] > 0 else 0
            score += 1 if ocf[i] > 0 else 0
            roa_now  = _safe_div(net_income[i], total_assets[i], 0)
            roa_prev = _safe_div(net_income[j], total_assets[j], 0)
            score += 1 if roa_now > roa_prev else 0
            score += 1 if ocf[i] > net_income[i] else 0
            # b) leverage / liquidity
            score += 1 if lt_debt[i] < lt_debt[j] else 0
            cr_now  = _safe_div(current_assets[i], current_liab[i], 0)
            cr_prev = _safe_div(current_assets[j], current_liab[j], 0)
            score += 1 if cr_now > cr_prev else 0
            score += 1 if shares_out[i] <= shares_out[j] else 0
            # c) operating efficiency
            gm_now  = _safe_div(gross[i], revenue[i], 0)
            gm_prev = _safe_div(gross[j], revenue[j], 0)
            score += 1 if gm_now > gm_prev else 0
            turn_now  = _safe_div(revenue[i], total_assets[i], 0)
            turn_prev = _safe_div(revenue[j], total_assets[j], 0)
            score += 1 if turn_now > turn_prev else 0
            piotroski.append(score)

        return {
            "ticker":       tk,
            "source_stock": stock,
            "period":       period,
            "years":        years,     # 保持字段名向后兼容（年度是 "2025"，季度是 "Q3'25"）
            "croic":        croic,
            "financial_debt": fin_debt,
            "ccc":          ccc,
            "piotroski":    piotroski,
            "latest": {
                "croic":     croic[-1] if croic else None,
                "fin_debt":  fin_debt[-1] if fin_debt else None,
                "ccc":       ccc[-1] if ccc else None,
                "piotroski": piotroski[-1] if piotroski else None,
            },
        }
    except Exception as e:
        return {"ticker": tk, "source": stock, "period": period, "error": str(e)[:150]}


def api_events(days_ahead: int = 45) -> dict:
    """未来 N 天内的宏观 + 财报事件（CPI/PPI/NFP/FOMC/NVDA earnings 等）。

    数据源：events_watch.EQUITY_CALENDAR。今日的事件保留，1 天前也保留（当日盘后可能有影响）。
    """
    try:
        from events_watch import EQUITY_CALENDAR
    except Exception as e:
        return {"events": [], "error": str(e)}
    from datetime import date
    today = date.today()
    out = []
    for ev in EQUITY_CALENDAR:
        try:
            ev_date = date.fromisoformat(ev["date"])
        except Exception:
            continue
        delta = (ev_date - today).days
        if delta < -1 or delta > days_ahead:
            continue
        out.append({
            "date":   ev["date"],
            "days":   delta,
            "event":  ev["event"],
            "impact": ev.get("impact", "med"),
        })
    out.sort(key=lambda x: x["days"])
    return {"events": out, "today": today.isoformat(), "days_ahead": days_ahead}


def _ticker_ai_snapshot_parse() -> dict:
    """从最新 ai_analysis_*.md 提取 '### TICKER' 段落。旧机制，作为 live 未覆盖时的 fallback。"""
    import re
    files = sorted(SIGNALS_DIR.glob("ai_analysis_*.md"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"exists": False, "tickers": {}}
    latest = files[0]
    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        return {"exists": False, "error": str(e), "tickers": {}}
    body = content
    m_start = re.search(r"^##\s*分标的执行", body, re.MULTILINE)
    if m_start:
        body = body[m_start.end():]
    m_end = re.search(r"^##\s+", body, re.MULTILINE)
    if m_end:
        body = body[:m_end.start()]
    tickers: dict[str, str] = {}
    parts = re.split(r"^###\s+([A-Z]{2,6})\b", body, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        tk = parts[i].strip().upper()
        seg = parts[i + 1] if i + 1 < len(parts) else ""
        seg = seg.strip()
        if tk and seg:
            tickers[tk] = seg[:2000]
    return {
        "exists": True,
        "path":   latest.name,
        "mtime":  datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
        "tickers": tickers,
    }


def _ticker_ai_live_all(signals: dict, options: dict) -> dict:
    """一次 Claude 调用生成所有 tracked ticker 的即时分析。

    缓存 key = sha1(标的 + action + conf + spot + wall OI)。数据变才重跑 Claude。
    非阻塞：无缓存时后台线程跑，本次请求返 state=generating。
    """
    import hashlib
    if not signals and not options:
        return {"tickers": {}, "state": "empty"}

    tk_list = []
    for tk in sorted(TICKER_TO_OPTION_SOURCE.keys()):
        sig = signals.get(tk, {})
        opt = options.get(tk, {})
        if not sig and (not opt or 'error' in opt):
            continue
        tk_list.append((tk, sig, opt))

    if not tk_list:
        return {"tickers": {}, "state": "empty"}

    hash_input = json.dumps([
        (tk, sig.get("action_zh"), sig.get("conf"), sig.get("bull_count"), sig.get("bear_count"),
         opt.get("spot"), opt.get("call_wall_oi"), opt.get("put_wall_oi"),
         opt.get("squeeze_risk", {}).get("type") if isinstance(opt.get("squeeze_risk"), dict) else None)
        for tk, sig, opt in tk_list
    ], sort_keys=True)
    key = hashlib.sha1(hash_input.encode()).hexdigest()[:12]
    cache_path = _WEBUI_CACHE_DIR / f"ticker_ai_live_{key}.json"

    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            data["state"] = "cached"
            return data
        except Exception:
            pass

    flag_key = f"ticker_ai_live_{key}"
    if not _refresh_flag.get(flag_key):
        def _bg():
            _refresh_flag[flag_key] = True
            try:
                from ai_prompt import query_claude_cli
                lines = []
                for tk, s, o in tk_list:
                    lines.append(f"--- {tk} ---")
                    lines.append(
                        f"信号: {s.get('action_zh','?')} conf={s.get('conf','?')}/{s.get('scale','?')} "
                        f"| 多{s.get('bull_count',0)}/空{s.get('bear_count',0)} | "
                        f"RSI={s.get('rsi','?')} 量比={s.get('vol_ratio','?')} regime={s.get('regime','?')}"
                    )
                    if 'error' not in o:
                        of = o.get('offense', {}) or {}
                        ds = o.get('defense', {}) or {}
                        sr = o.get('squeeze_risk', {}) or {}
                        sm = o.get('sentiment', {}) or {}
                        lines.append(f"期权链={o.get('underlying','?')} spot=${o.get('spot')} exp={o.get('expiry')}")
                        lines.append(
                            f"  Call wall ${of.get('strike')} OI={of.get('oi',0)} 保费=${of.get('prem')} "
                            f"(距spot {of.get('dist_pct')}%) 强度{of.get('strength','?')}"
                        )
                        lines.append(
                            f"  Put  wall ${ds.get('strike')} OI={ds.get('oi',0)} 保费=${ds.get('prem')} "
                            f"(距spot {ds.get('dist_pct')}%) 强度{ds.get('strength','?')}"
                        )
                        lines.append(f"  C/P成交={sm.get('cp_ratio','?')} ({sm.get('label','')}) 挤压=[{sr.get('urgency')}]{sr.get('type')}")
                        # OI 失衡数据
                        p_oi = ds.get('oi', 0) or 0
                        c_oi = of.get('oi', 0) or 0
                        if p_oi and c_oi:
                            ratio = p_oi / c_oi
                            if ratio >= 3 or ratio <= 0.33:
                                lines.append(f"  ⚠ Put OI/Call OI = {ratio:.1f}倍 严重失衡")
                    # 基本面（若缓存里有 —— 不主动拉，避免拖慢 Claude 调用）
                    try:
                        fd_cache = _WEBUI_CACHE_DIR / f"fundamentals_{tk}.json"
                        if fd_cache.exists():
                            fd = json.loads(fd_cache.read_text(encoding="utf-8"))
                            if "error" not in fd:
                                latest = fd.get("latest", {})
                                lines.append(
                                    f"  基本面(来源 {fd.get('source_stock','?')}): CROIC={latest.get('croic')}% "
                                    f"Piotroski={latest.get('piotroski')}/9 借款=${latest.get('fin_debt')}M "
                                    f"CCC={latest.get('ccc')}天 · 4 年趋势 CROIC={fd.get('croic')}"
                                )
                    except Exception:
                        pass
                    lines.append("")

                prompt = (
                    "你是量化交易分析师。对下面每个标的用 3 行中文输出（无 preamble、无 markdown ```围栏），"
                    "格式严格如下：\n\n"
                    "### <TICKER>\n"
                    "- 综合: <多空信号+期权是否共振，1 行>\n"
                    "- 攻防: <关键防守/进攻位可操作性 + 到 spot 距离，1 行>\n"
                    "- 警示: <异常/机会/风险，无则写 暂无>\n\n"
                    "解读规则（严格遵循）：\n"
                    "1. Put OI 远大于 Call OI 时区分：ATM 附近=真恐慌 / OTM 远端=廉价保险；机构对冲(用户持仓可放心) vs 空头押跌\n"
                    "2. Call OI 远大于 Put OI 时：上方是 pin 磁吸位 / 下方无护盘\n"
                    "3. gamma_up 挤压[high] = 突破 call wall 加速上涨；put_break 挤压[high] = 跌破 put wall 加速下跌\n"
                    "4. 信号 conf ≥ 4 且期权攻防共振 → 明确机会；信号看多但 put OI 大幅堆积 → 警示 divergence\n"
                    "5. 若基本面存在 → 综合行里带一句：CROIC 趋势方向 + Piotroski 强/弱 + 借款激增警示\n"
                    "6. 严格只输出 ### 段落，不要总结不要展望不要重复问题\n\n"
                    "标的数据：\n"
                    + "\n".join(lines)
                )
                out, status = query_claude_cli(prompt, timeout=120)
                if out and out.strip():
                    import re
                    parts = re.split(r"^###\s+([A-Z]{2,6})\b", out, flags=re.MULTILINE)
                    tickers = {}
                    for i in range(1, len(parts), 2):
                        tk = parts[i].strip().upper()
                        body = parts[i + 1] if i + 1 < len(parts) else ""
                        body = body.strip()
                        if tk and body:
                            tickers[tk] = body[:1500]
                    if tickers:
                        result = {
                            "tickers": tickers,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        cache_path.write_text(
                            json.dumps(result, ensure_ascii=False), encoding="utf-8"
                        )
                # else: silent fail, state stays generating; next refresh will retry
            except Exception:
                pass
            finally:
                _refresh_flag[flag_key] = False
        threading.Thread(target=_bg, daemon=True).start()

    return {"tickers": {}, "state": "generating"}


def api_ticker_ai() -> dict:
    """每标的 Claude 分析。优先 live（覆盖所有 tracked ticker），fallback 到 snapshot。"""
    signals   = api_signals().get("tickers", {}) or {}
    opt_data  = api_ticker_options().get("tickers", {}) or {}
    live      = _ticker_ai_live_all(signals, opt_data)
    snapshot  = _ticker_ai_snapshot_parse()

    tickers: dict[str, str] = {}
    sources: dict[str, str] = {}
    # 优先 live
    for tk, body in (live.get("tickers") or {}).items():
        tickers[tk] = body
        sources[tk] = "live"
    # 补 snapshot（未被 live 覆盖的）
    for tk, body in (snapshot.get("tickers") or {}).items():
        if tk not in tickers:
            tickers[tk] = body
            sources[tk] = "snapshot"

    return {
        "exists":         bool(tickers) or live.get("state") == "generating",
        "tickers":        tickers,
        "sources":        sources,
        "live_state":     live.get("state", "empty"),  # cached / generating / empty
        "live_generated": live.get("generated_at"),
        "snapshot_path":  snapshot.get("path"),
        "snapshot_mtime": snapshot.get("mtime"),
    }


TICKER_TO_OPTION_SOURCE = {
    "TQQQ": "QQQ",   # 3x QQQ → 用 QQQ chain（同指数、更深）
    "SOXL": "SOXX",  # 3x SOX (ICE 半导体指数) → 1x 版本 SOXX，同指数最精准
    "DRAM": "DRAM",  # Roundhill Memory ETF 自身有 chain（贴近实际持仓）
    "MULL": "MU",    # 2x MU（Direxion）单股杠杆，用 MU 本体
    "GLD":  "GLD",
    "TSLA": "TSLA",
    "KLAC": "KLAC",
    "AMAT": "AMAT",
    "GOOGL": "GOOGL",
    "NVDA": "NVDA",
    "MSFT": "MSFT",
    "AAPL": "AAPL",
}


def _analyze_walls(spot, call_wall, put_wall, max_pain,
                   cw_vol, pw_vol, total_c, total_p,
                   cw_oi=0, pw_oi=0, cw_prem=None, pw_prem=None) -> dict:
    """从 walls + spot 推导 攻/防位、C/P 情绪、挤压风险。

    OI-based walls 优先（有实际持仓才有对冲压力）；vol-based 作 fallback。
    """
    r: dict = {}
    # 用 OI 做强度（若无则退回 vol）
    _c_denom = sum([cw_oi, pw_oi]) or (total_c + total_p) or 1
    def _fmt_notional(n):
        if not n: return ""
        if n >= 1e9:  return f"~${n/1e9:.1f}B"
        if n >= 1e6:  return f"~${n/1e6:.0f}M"
        if n >= 1e3:  return f"~${n/1e3:.0f}K"
        return f"~${n:.0f}"

    if put_wall is not None:
        dist_pct = round((spot - put_wall) / spot * 100, 2)  # >0 = 支撑在下方
        share    = (pw_oi / max(pw_oi + cw_oi, 1)) if (pw_oi + cw_oi) else pw_vol / max(total_p, 1)
        strength = "强" if share >= 0.35 else ("中" if share >= 0.18 else "弱")
        r["defense"] = {
            "strike":   put_wall,
            "dist_pct": dist_pct,
            "strength": strength,
            "share":    round(share * 100, 1),
            "oi":       pw_oi,
            "prem":     pw_prem,
            "notional": int(pw_oi * 100 * put_wall) if pw_oi else 0,
        }
    if call_wall is not None:
        dist_pct = round((call_wall - spot) / spot * 100, 2)
        share    = (cw_oi / max(pw_oi + cw_oi, 1)) if (pw_oi + cw_oi) else cw_vol / max(total_c, 1)
        strength = "强" if share >= 0.35 else ("中" if share >= 0.18 else "弱")
        r["offense"] = {
            "strike":   call_wall,
            "dist_pct": dist_pct,
            "strength": strength,
            "share":    round(share * 100, 1),
            "oi":       cw_oi,
            "prem":     cw_prem,
            "notional": int(cw_oi * 100 * call_wall) if cw_oi else 0,
        }

    # 挤压风险 —— OI 达标才算真信号（>500 手，避免小盘噪音）
    risk = {"type": "none", "urgency": "low",
            "detail": "当前价格远离主要期权墙，无明显挤压压力"}
    if (call_wall is not None and 0 <= (call_wall - spot) / spot * 100 <= 1.5
            and (cw_oi >= 500 or not cw_oi)):  # OI 未知时也放行
        pct = (call_wall - spot) / spot * 100
        prem_s = f" · 单手保费 ${cw_prem}" if cw_prem else ""
        oi_s = f" · OI {cw_oi:,} ({_fmt_notional(cw_oi*100*call_wall)} 名义)" if cw_oi else ""
        risk = {"type": "gamma_up", "urgency": "high",
                "detail": f"Call wall ${call_wall} 距现价仅 {pct:.1f}%{oi_s}{prem_s}。突破且放量 → 做市商需买入对冲 → 短期加速上涨（gamma squeeze）"}
    elif (put_wall is not None and 0 <= (spot - put_wall) / spot * 100 <= 1.5
            and (pw_oi >= 500 or not pw_oi)):
        pct = (spot - put_wall) / spot * 100
        prem_s = f" · 单手保费 ${pw_prem}" if pw_prem else ""
        oi_s = f" · OI {pw_oi:,} ({_fmt_notional(pw_oi*100*put_wall)} 名义)" if pw_oi else ""
        risk = {"type": "put_break", "urgency": "high",
                "detail": f"Put wall ${put_wall} 距现价仅 {pct:.1f}%{oi_s}{prem_s}。跌破 = 关键支撑丢失，止损盘 + 做市商反手对冲 → 加速下跌"}
    elif max_pain is not None and abs(spot - max_pain) / spot * 100 >= 3:
        pull = "下拉" if spot > max_pain else "上拉"
        pct = abs(spot - max_pain) / spot * 100
        risk = {"type": "max_pain_gravity", "urgency": "medium",
                "detail": f"Max Pain ${max_pain}（距现价 {pct:.1f}%）。到期日临近，期权卖方倾向将价格{pull}至此"}
    r["squeeze_risk"] = risk
    # C/P 情绪 —— 带小白详细解读
    if total_p > 0:
        cp = total_c / total_p
        if cp >= 1.8:
            label = "看多情绪偏热"
            explain = (
                f"Call 成交是 Put 的 {cp:.1f} 倍。**多头拥挤**：\n"
                "  · 大家在追多 / 抢反弹 / 押突破\n"
                "  · 历史规律：C/P > 1.8 时短期回调概率偏高（反向指标）\n"
                "  · 尤其若配合价格已涨很多 → 警惕获利了结压力"
            )
        elif cp <= 0.5:
            label = "看空情绪极端"
            explain = (
                f"Put 成交是 Call 的 {1/cp:.1f} 倍。**空头拥挤 / 大量对冲**：\n"
                "  · 场景 a) 恐慌下跌中 → 多为空头押跌\n"
                "  · 场景 b) 机构大量买 put 做保险（他们仍持股）→ 中性偏温和多\n"
                "  · 场景 c) 有明确利空事件预期（财报/宏观/政策）\n"
                "  · 历史规律：C/P < 0.5 时短期反弹概率 ~60%（『恐慌见底』反向指标）\n"
                "  · 区分 a vs b：看这些 put 是 ATM（真怕跌）还是远 OTM（廉价 tail hedge）"
            )
        else:
            label = "多空均衡"
            explain = "Call/Put 成交比例接近 1:1，市场无明显方向性偏见。"
        r["sentiment"] = {"cp_ratio": round(cp, 2), "label": label, "explain": explain}
    # 墙 OI 失衡解读（Put OI 远大于 Call OI 或反之）
    if pw_oi > 0 and cw_oi > 0:
        ratio = pw_oi / cw_oi
        wall_note = None
        if ratio >= 3:
            wall_note = (
                f"**Put 墙 OI 是 Call 墙的 {ratio:.1f} 倍**：下方『真金白银』押注远超上方。\n"
                "  · 若你手上有仓位：这是**对冲/保险堆积**的层，跌到这里通常有反弹\n"
                "  · 若空头思路：说明大家已经知道下方风险了 → 你不占信息优势\n"
                "  · 例外：如果 Put 墙很接近 spot（<2%），跌破会引发做市商反手对冲 → **加速下跌**"
            )
        elif ratio <= 0.33:
            wall_note = (
                f"**Call 墙 OI 是 Put 墙的 {1/ratio:.1f} 倍**：上方阻力/追多力量集中，下方对冲少。\n"
                "  · 通常出现在强势股 / 短期热门标的 → 上方是 pin / 磁吸位\n"
                "  · 下方无护盘 → 一旦下跌可能无缓冲、直接找下一档 support"
            )
        r["wall_imbalance"] = wall_note  # 可能是 None
    return r


def api_ticker_options() -> dict:
    """每个 tracked ticker 的期权墙 + 攻防位 + 挤压风险。10min 后台缓存。"""
    # 24h TTL —— 期权 wall/OI 日级变化就够，无必要秒级刷（拖累 yfinance + 间接
    # 让 ticker_ai 的 Claude hash 每天最多变一次）
    return _cached("ticker_options", ttl_sec=24 * 3600, compute_fn=_compute_ticker_options)


def _compute_ticker_options() -> dict:
    """对每个 tracked ticker 拉最近到期日期权链 + 分析。串行 ~15-30s 首次。"""
    import yfinance as yf
    out = {"ts": datetime.now(timezone.utc).isoformat(), "tickers": {}}
    for tk, underlying in TICKER_TO_OPTION_SOURCE.items():
        try:
            t = yf.Ticker(underlying)
            expiries = list(t.options or [])
            if not expiries:
                out["tickers"][tk] = {"underlying": underlying, "error": "no_option_chain"}
                continue
            exp = expiries[0]
            ch = t.option_chain(exp)
            calls, puts = ch.calls.copy(), ch.puts.copy()
            try:
                spot = float(t.history(period="1d")["Close"].iloc[-1])
            except Exception:
                spot = float(calls["strike"].median())
            lo, hi = spot * 0.90, spot * 1.10
            calls = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)]
            puts  = puts [(puts ["strike"] >= lo) & (puts ["strike"] <= hi)]
            calls["volume"]       = calls["volume"].fillna(0)
            puts["volume"]        = puts["volume"].fillna(0)
            if "openInterest" in calls.columns:
                calls["openInterest"] = calls["openInterest"].fillna(0)
                puts["openInterest"]  = puts["openInterest"].fillna(0)

            def _mid(row):
                """bid/ask mid 优先，fallback lastPrice；无值返回 None。"""
                if row.empty:
                    return None
                try:
                    b = float(row["bid"].iloc[0] or 0) if "bid" in row.columns else 0
                    a = float(row["ask"].iloc[0] or 0) if "ask" in row.columns else 0
                    if b > 0 and a > 0:
                        return round((b + a) / 2, 2)
                    lp = row["lastPrice"].iloc[0] if "lastPrice" in row.columns else None
                    return round(float(lp), 2) if lp else None
                except Exception:
                    return None

            all_s = sorted(set(calls["strike"].tolist()) | set(puts["strike"].tolist()))
            dist = []
            for s in all_s:
                cr = calls[calls["strike"] == s]
                pr = puts [puts ["strike"] == s]
                cv = int(cr["volume"].sum())
                pv = int(pr["volume"].sum())
                if cv + pv < 20:
                    continue
                c_oi = int(cr["openInterest"].sum()) if "openInterest" in cr.columns else 0
                p_oi = int(pr["openInterest"].sum()) if "openInterest" in pr.columns else 0
                dist.append({
                    "strike":    float(s),
                    "call_vol":  cv, "put_vol":  pv,
                    "call_oi":   c_oi, "put_oi":  p_oi,
                    "call_prem": _mid(cr),
                    "put_prem":  _mid(pr),
                })
            dist.sort(key=lambda x: -(x["call_vol"] + x["put_vol"]))
            dist = sorted(dist[:15], key=lambda x: x["strike"])
            if not dist:
                out["tickers"][tk] = {"underlying": underlying, "error": "no_liquid_strikes"}
                continue

            # Vol-based walls（图表用的还是 vol，反映日内活跃度）
            call_wall = max(dist, key=lambda x: x["call_vol"])
            put_wall  = max(dist, key=lambda x: x["put_vol"])
            # OI-based walls（分析用的是 OI，反映实际押注/持仓）
            call_wall_oi = max(dist, key=lambda x: x["call_oi"]) if any(d["call_oi"] > 0 for d in dist) else None
            put_wall_oi  = max(dist, key=lambda x: x["put_oi"])  if any(d["put_oi"] > 0 for d in dist) else None
            total_c = sum(d["call_vol"] for d in dist)
            total_p = sum(d["put_vol"] for d in dist)
            # Max pain
            best_s, best_pain = None, float("inf")
            for s in [d["strike"] for d in dist]:
                loss = 0.0
                for d in dist:
                    if d["strike"] < s: loss += d["call_vol"] * (s - d["strike"])
                    elif d["strike"] > s: loss += d["put_vol"] * (d["strike"] - s)
                if loss < best_pain:
                    best_pain, best_s = loss, s

            # 大单标记（在 wall 计算之前，方便前端拿到 flag）
            # 阈值: OI ≥ 5000 手 OR notional ≥ $30M （wall 级重要）
            for d in dist:
                cn = d["call_oi"] * 100 * d["strike"]
                pn = d["put_oi"]  * 100 * d["strike"]
                d["call_big"] = bool(d["call_oi"] >= 5000 or cn >= 30_000_000)
                d["put_big"]  = bool(d["put_oi"]  >= 5000 or pn >= 30_000_000)
                # 异常成交（vol 相对 OI 明显偏高 = 今日新建仓/大单扫单）
                d["call_unusual_vol"] = bool(d["call_vol"] > 2000 and d["call_oi"] > 0
                                             and d["call_vol"] > 0.5 * d["call_oi"])
                d["put_unusual_vol"]  = bool(d["put_vol"]  > 2000 and d["put_oi"] > 0
                                             and d["put_vol"] > 0.5 * d["put_oi"])

            # 分析优先用 OI 墙（fallback vol）
            an_call = call_wall_oi or call_wall
            an_put  = put_wall_oi  or put_wall
            analysis = _analyze_walls(
                spot=spot,
                call_wall=an_call["strike"], put_wall=an_put["strike"],
                max_pain=best_s,
                cw_vol=an_call["call_vol"], pw_vol=an_put["put_vol"],
                cw_oi=an_call["call_oi"],    pw_oi=an_put["put_oi"],
                cw_prem=an_call["call_prem"], pw_prem=an_put["put_prem"],
                total_c=total_c, total_p=total_p,
            )

            def _wall_meta(w, side):
                """把 wall dict 展平成 strike / prem / oi / notional"""
                if not w: return {}
                oi = w[f"{side}_oi"]
                prem = w[f"{side}_prem"]
                strike = w["strike"]
                notional = oi * 100 * strike  # 名义 = OI × 100 × 现价（用 strike 近似）
                return {
                    f"{side}_wall_strike":   strike,
                    f"{side}_wall_vol":      w[f"{side}_vol"],
                    f"{side}_wall_oi":       oi,
                    f"{side}_wall_prem":     prem,
                    f"{side}_wall_notional": int(notional),
                }

            # 财报上下文：从 option_walls._next_earnings_for 拿到 (股票, 财报日, 天数)
            earnings_meta = {}
            try:
                from option_walls import _TICKER_EARNINGS, _ETF_EARNINGS_LINKS, get_earnings_implied_move
                from datetime import date as _date, datetime as _dt
                today = _date.today()
                # 关联财报：先看是不是单股（直接查），再看是不是 ETF（走 links）
                candidate_stocks = [tk] if tk in _TICKER_EARNINGS else list(_ETF_EARNINGS_LINKS.get(tk, []))
                best = None
                for e_stock in candidate_stocks:
                    for d_str in _TICKER_EARNINGS.get(e_stock, []):
                        try:
                            d_obj = _dt.strptime(d_str, "%Y-%m-%d").date()
                        except Exception:
                            continue
                        days = (d_obj - today).days
                        if 0 <= days <= 60:  # 60 天窗口（比 option_walls 的 30 天宽）
                            if best is None or days < best[2]:
                                best = (e_stock, d_str, days)
                if best:
                    e_stock, e_date, e_days = best
                    earnings_meta = {
                        "earnings_stock":     e_stock,
                        "earnings_date":      e_date,
                        "days_to_earnings":   e_days,
                        "expiry_covers_earnings": exp >= e_date,
                    }
                    # 隐含波动幅度（ATM straddle 反推），只在 ≤ 14 天且是单股时算
                    if e_days <= 14 and tk in ("MU", "NVDA"):
                        try:
                            im = get_earnings_implied_move(tk, earnings_date=e_date)
                            if im and im.get("implied_move_pct"):
                                earnings_meta["implied_move_pct"] = round(im["implied_move_pct"], 2)
                        except Exception:
                            pass
            except Exception:
                pass

            out["tickers"][tk] = {
                "underlying":       underlying,
                "spot":             round(spot, 2),
                "expiry":           exp,
                "distribution":     dist,
                # 保留 vol-based walls（SVG 图用）
                **_wall_meta(call_wall, "call"),
                **_wall_meta(put_wall, "put"),
                # OI-based walls（分析用；若与 vol wall 同一 strike 则相同）
                "call_wall_oi_strike": call_wall_oi["strike"] if call_wall_oi else None,
                "put_wall_oi_strike":  put_wall_oi["strike"]  if put_wall_oi  else None,
                "max_pain":         best_s,
                **analysis,
                **earnings_meta,
            }
        except Exception as e:
            out["tickers"][tk] = {"underlying": underlying, "error": str(e)[:100]}
    return out


def api_option_walls_chart() -> dict:
    """三个主要指数（QQQ/SMH/GLD）最近到期日期权成交量分布 + 关键墙。
    重仓 ETF 对应的板块指数：
      · QQQ  ← TQQQ 3x 追踪
      · SMH  ← SOXL 3x / DRAM / MULL 追踪
      · GLD  ← 黄金现货
    15 min 后台缓存。
    """
    return _cached("option_walls_chart", ttl_sec=24 * 3600, compute_fn=_compute_option_walls_chart)


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
            elif path == "/api/ticker_options":
                self._json(api_ticker_options())
            elif path == "/api/ticker_ai":
                self._json(api_ticker_ai())
            elif path == "/api/events":
                self._json(api_events())
            elif path == "/api/supply_chain":
                tk = qs.get("ticker", [""])[0]
                self._json(api_supply_chain(tk))
            elif path == "/api/supply_chain_graph":
                tk = qs.get("ticker", [""])[0]
                dp = int(qs.get("depth", ["2"])[0])
                self._json(api_supply_chain_graph(tk, depth=dp))
            elif path == "/api/fundamentals":
                tk = qs.get("ticker", [""])[0]
                pd = qs.get("period", ["year"])[0]
                self._json(api_fundamentals(tk, period=pd))
            elif path == "/api/jp_watch":
                self._json(api_jp_watch())
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
