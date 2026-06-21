"""
QuantSignal — 把 strategy_evolver 跑出的 evolved_rules_*.json 转成
可被 decision_agent 直接消费的"量化共振分"。

定位：
  decision_agent 原本只有 技术(_tech_*) + 宏观(_macro_*) + 事件(_event_*)
  三个评分维度。这里新增第 4 个维度 quant —— 把进化规则的"今天哪些
  规则触发了 + 它们的回测胜率"折算成 0-3 分，加到 bear / bull 总分上。

接口：
  evaluate(ticker, mkt) -> {
    "buy_hits":   [{"name":..., "wr":..., "n":...}, ...],
    "sell_hits":  [...],
    "buy_score":  0-3,
    "sell_score": 0-3,
    "n_rules":    本 ticker 加载的存活规则数,
    "ts":         规则文件 mtime ISO,
  }

缓存：按文件 mtime 缓存，文件更新自动重载（evolver 每日 pre-open 跑）。
"""
import json
from datetime import datetime
from pathlib import Path

from config import SIGNALS_DIR


_BUY_ACTIONS  = {"BUY", "WATCH_BUY"}
_SELL_ACTIONS = {"REDUCE", "SELL"}

# 单条规则的质量门槛——比 strategy_evolver.load_evolved_rules 的 55% 更严
_MIN_WR = 65.0
_MIN_N  = 5

# (ticker -> (mtime, rules)) 缓存
_cache: dict[str, tuple[float, list[dict]]] = {}


def _rules_path(ticker: str, bucket: str | None = None) -> Path:
    """按 regime bucket 找规则文件 (bucket 为空 fallback 到老 pooled 版)。"""
    suffix = f"_{bucket}" if bucket else ""
    return Path(SIGNALS_DIR) / f"evolved_rules_{ticker.replace('.', '-')}{suffix}.json"


def _load(ticker: str, bucket: str | None = None) -> tuple[list[dict], float | None]:
    # 优先用 bucket 规则；缺失则 fallback 到 pooled (老文件)
    path = _rules_path(ticker, bucket)
    if not path.exists() and bucket:
        path = _rules_path(ticker, None)
    if not path.exists():
        return [], None
    mtime = path.stat().st_mtime
    cache_key = f"{ticker}:{bucket or 'pooled'}"
    cached = _cache.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1], mtime
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        survivors = [
            r for r in data.get("survivors", [])
            if r.get("test_wr", 0) >= _MIN_WR
            and r.get("test_n", 0) >= _MIN_N
        ]
    except Exception:
        survivors = []
    _cache[cache_key] = (mtime, survivors)
    return survivors, mtime


def _check(val, op: str, threshold) -> bool:
    if val is None:
        return False
    try:
        if op == "=":  return val == threshold
        if op == ">":  return val > threshold
        if op == "<":  return val < threshold
        if op == ">=": return val >= threshold
        if op == "<=": return val <= threshold
    except TypeError:
        return False
    return False


def _eval_rule(mkt: dict, rule: dict) -> bool:
    conds = rule.get("conditions") or []
    if not conds:
        return False
    return all(_check(mkt.get(f), op, th) for f, op, th in conds)


def _score(hits: list[dict]) -> int:
    """命中数 + 平均胜率 → 0-3。
       阈值偏保守，避免过早把高频弱信号当强信号。"""
    if not hits:
        return 0
    n = len(hits)
    avg_wr = sum(h["wr"] for h in hits) / n
    if n >= 3 and avg_wr >= 75: return 3
    if n >= 2 and avg_wr >= 70: return 2
    if n >= 1 and avg_wr >= 70: return 1
    return 0


def evaluate(ticker: str, mkt: dict) -> dict:
    # 按今日 regime bucket 加载对应规则集（治本：bull 时不用 bear 学的规则）
    try:
        from regime_labeler import label_today
        bucket = label_today()
    except Exception:
        bucket = None
    rules, mtime = _load(ticker, bucket=bucket)
    buy_hits: list[dict] = []
    sell_hits: list[dict] = []
    for r in rules:
        if not _eval_rule(mkt, r):
            continue
        item = {"name": r.get("name") or r.get("id"),
                "wr":   round(r.get("test_wr", 0), 1),
                "n":    int(r.get("test_n", 0)),
                "action": r.get("action")}
        if r.get("action") in _BUY_ACTIONS:
            buy_hits.append(item)
        elif r.get("action") in _SELL_ACTIONS:
            sell_hits.append(item)
    # Regime-aligned: bull regime 不输出 sell_score, bear regime 不输出 buy_score
    # (避免 quant 在 trend 中触发反向信号 → 减少过砍/过追)
    buy_score  = _score(buy_hits)
    sell_score = _score(sell_hits)
    if bucket == "bull":
        sell_score = 0
        sell_hits  = []
    elif bucket == "bear":
        buy_score  = 0
        buy_hits   = []
    return {
        "buy_hits":     buy_hits,
        "sell_hits":    sell_hits,
        "buy_score":    buy_score,
        "sell_score":   sell_score,
        "n_rules":      len(rules),
        "regime_bucket": bucket,
        "ts":           datetime.fromtimestamp(mtime).isoformat() if mtime else None,
    }


def summary_line(quant: dict | None) -> str:
    """单行简报，给 notifier/log 用。"""
    if not quant or quant.get("n_rules", 0) == 0:
        return "[quant] (无进化规则)"
    bh = quant["buy_hits"]; sh = quant["sell_hits"]
    parts = [f"rules={quant['n_rules']}",
             f"bull={quant['buy_score']}({len(bh)})",
             f"bear={quant['sell_score']}({len(sh)})"]
    if bh:
        parts.append("BUY:" + ",".join(f"{h['name'][:18]}@{h['wr']}%" for h in bh[:3]))
    if sh:
        parts.append("SELL:" + ",".join(f"{h['name'][:18]}@{h['wr']}%" for h in sh[:3]))
    return "[quant] " + " | ".join(parts)
