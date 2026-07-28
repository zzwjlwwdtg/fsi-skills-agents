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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).parent
SIGNALS_DIR = SCRIPT_DIR / "signals"
LOGS_DIR    = SCRIPT_DIR / "logs"
LOCK_PATH   = SCRIPT_DIR / ".orchestrator.lock"
STATE_PATH  = SCRIPT_DIR / "trader_state.json"

PORT = int(os.environ.get("WEBUI_PORT", "8080"))
HOST = os.environ.get("WEBUI_HOST", "127.0.0.1")


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
        banners["trump"] = {
            "posts":     int(m.group(1)),
            "direction": m.group(2),
            "magnitude": m.group(3),
            "score":     int(m.group(4)),
        }

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
    """石油宏观：用 USO (油价 ETF) + WTI 期货 CL=F 综合。
    输出：现价 / 5d% / 20d% / MA20 dist / trend / 简单方向标签。
    """
    import yfinance as yf
    out = {"ts": datetime.now(timezone.utc).isoformat()}
    for tk, key in [("CL=F", "wti_futures"), ("USO", "uso_etf")]:
        try:
            df = yf.Ticker(tk).history(period="30d", interval="1d", auto_adjust=True)
            if df.empty or len(df) < 21:
                out[key] = {"error": "no data"}
                continue
            close = df["Close"].astype(float)
            price = float(close.iloc[-1])
            pct_5d  = ((price / float(close.iloc[-6])  - 1) * 100)
            pct_20d = ((price / float(close.iloc[-21]) - 1) * 100)
            ma20    = float(close.tail(20).mean())
            dist_ma = ((price - ma20) / ma20 * 100)
            trend = "up" if price > ma20 else "down"
            # 简单方向：油价上涨通常利多风险资产 + 通胀
            direction = "neutral"
            if pct_20d >= 8:  direction = "bullish"  # 显著上涨
            elif pct_20d <= -8: direction = "bearish"
            elif pct_5d >= 5:  direction = "bullish"
            elif pct_5d <= -5: direction = "bearish"
            out[key] = {
                "ticker":    tk,
                "price":     round(price, 2),
                "pct_5d":    round(pct_5d, 2),
                "pct_20d":   round(pct_20d, 2),
                "dist_ma20": round(dist_ma, 2),
                "trend":     trend,
                "direction": direction,
            }
        except Exception as e:
            out[key] = {"error": str(e)}
    # 综合：优先 WTI 期货，fallback USO
    primary = out.get("wti_futures") if not out.get("wti_futures", {}).get("error") else out.get("uso_etf", {})
    if primary and not primary.get("error"):
        out["direction"] = primary.get("direction")
        out["price"]     = primary.get("price")
        out["pct_5d"]    = primary.get("pct_5d")
        out["pct_20d"]   = primary.get("pct_20d")
        out["source"]    = "WTI 期货 (CL=F)" if not out.get("wti_futures", {}).get("error") else "USO 油价 ETF"
        # 影响解读
        notes = []
        if primary["pct_20d"] >= 8:
            notes.append("油价 20d 大涨 → 通胀压力上升，利好油气板块，利空高估值成长")
        elif primary["pct_20d"] <= -8:
            notes.append("油价 20d 大跌 → 通胀降温，利多科技/黄金")
        elif primary["pct_5d"] >= 5:
            notes.append("油价短期急升 → 关注地缘 / 供给紧张")
        elif primary["pct_5d"] <= -5:
            notes.append("油价短期急跌 → 需求疲软信号")
        if not notes:
            notes.append("油价窄幅震荡，宏观影响小")
        out["notes"] = notes
    return out


def api_sectors() -> dict:
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
