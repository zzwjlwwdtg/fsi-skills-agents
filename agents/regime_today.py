"""
RegimeToday — 系统级"今日 regime"单一源。

设计原则（5-29 用户原话："重点是决策矩阵吧，知道现在是那种 regime，然后
提示，根据这个为前提然后给决策"）：
  · 每天 pre-open **算一次**，写入 regime_state.json
  · 所有下游（universe_picker / decision_agent / pca_sox / notifier）都读它
  · 决策的"前提" — 先告诉用户今天什么 regime，再讲规则

输入用**板块级**而不是单股：
  · SOX 28 只成分股的 MKT 等权收益（5/20 日均 + 今日）
  · 宏观: VIX, F&G, T10Y2Y
  · SPY 当日涨跌（broad-market sanity）

输出: {bull_trending / overheated / recession_risk / crisis / neutral}

decision_agent.get_decision 接 board_regime=... 后用本日 regime；
只有单股**当日暴跌 ≤ -5%** 才被允许 override 成 crisis（保护该单股）。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from notifier import logger
from atomic_io import atomic_write_json


REGIME_STATE_PATH = Path(__file__).parent / "regime_state.json"
ET = ZoneInfo("America/New_York")
_STALE_WARNED_FOR: str | None = None


def _next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _market_date(now: datetime | None = None) -> str:
    """Return the trading date this process should reason about, in ET.

    After the US after-hours session ends, the next actionable session is the
    next weekday. This prevents a late-night restart from silently reusing
    yesterday's regime as tomorrow's premise.
    """
    now_et = now.astimezone(ET) if now else datetime.now(ET)
    d = now_et.date()
    if now_et.weekday() >= 5:
        d = _next_weekday(d)
    elif now_et.hour >= 20:
        d = _next_weekday(d + timedelta(days=1))
    return d.isoformat()

# 与 decision_agent.get_regime 的判定一致，把板块涨跌映射到 zone
def _pct_zone(p: float) -> str:
    if p <= -5: return "crash"
    if p <= -2: return "drop"
    if p <= -1: return "mild_drop"
    if p >=  5: return "surge"
    if p >=  2: return "pop"
    if p >=  1: return "mild_pop"
    return "normal"


def _fetch_spy_today_pct() -> Optional[float]:
    try:
        import yfinance as yf
        h = yf.Ticker("SPY").history(period="5d", interval="1d")
        if len(h) < 2: return None
        return float((h["Close"].iloc[-1] - h["Close"].iloc[-2]) / h["Close"].iloc[-2] * 100)
    except Exception:
        return None


def _fetch_spy_extension_and_atr() -> tuple[Optional[float], Optional[float]]:
    """返回 (SPY 现价相对 MA50 偏离 %, 5日 ATR / 20日 ATR 比)。用于 bull 子类判断。"""
    try:
        import yfinance as yf
        import numpy as np
        h = yf.Ticker("SPY").history(period="80d", interval="1d")
        if len(h) < 50: return (None, None)
        close = h["Close"]
        ma50 = close.rolling(50).mean().iloc[-1]
        extension = (close.iloc[-1] - ma50) / ma50 * 100
        # True Range
        tr = np.maximum(h["High"] - h["Low"],
                        np.maximum(abs(h["High"] - h["Close"].shift()),
                                   abs(h["Low"] - h["Close"].shift())))
        atr5  = tr.tail(5).mean()
        atr20 = tr.tail(20).mean()
        atr_ratio = atr5 / atr20 if atr20 > 0 else None
        return (float(extension), float(atr_ratio) if atr_ratio else None)
    except Exception:
        return (None, None)


def _build_board_inputs() -> dict:
    """聚合 SOX 板块因子 + 宏观 + SPY。失败的字段填 None。"""
    out = {
        "sox_mkt_today_pct": None, "sox_mkt_5d_pct": None, "sox_mkt_20d_pct": None,
        "spy_today_pct":     None,
        "vix": None, "fg": None, "t10y2y": None,
    }
    # SOX 板块因子
    try:
        from pca_sox import fetch_returns, compute_factors
        returns = fetch_returns()
        if returns is not None and not returns.empty:
            factors = compute_factors(returns)
            mkt = factors["MKT"]
            out["sox_mkt_today_pct"] = float(mkt.iloc[-1] * 100)
            out["sox_mkt_5d_pct"]    = float(mkt.tail(5).mean() * 100)
            out["sox_mkt_20d_pct"]   = float(mkt.tail(20).mean() * 100)
    except Exception as e:
        logger.warning(f"[regime] SOX 因子拉取失败: {e}")
    # SPY 当日 + 子类指标
    out["spy_today_pct"] = _fetch_spy_today_pct()
    ext, atr_r = _fetch_spy_extension_and_atr()
    out["spy_extension_pct"] = ext
    out["spy_atr_ratio"]     = atr_r
    # 宏观
    try:
        from data_feeds import fetch_vix, fetch_fear_greed
        out["vix"] = fetch_vix()
        out["fg"]  = (fetch_fear_greed() or {}).get("score")
    except Exception as e:
        logger.warning(f"[regime] VIX/F&G 拉取失败: {e}")
    try:
        from fred_feeds import fetch_fred
        out["t10y2y"] = (fetch_fred().get("T10Y2Y") or {}).get("value")
    except Exception as e:
        logger.warning(f"[regime] FRED 拉取失败: {e}")
    return out


def _classify(inp: dict) -> str:
    """
    板块级输入 → 8 种 regime。
    base 5 个: bull_trending / overheated / recession_risk / crisis / neutral
    Layer 1 新增 bull 3 子类:
      bull_extended : 现价远高于 MA50 (>10% extension)，强动量延续，**完全 disable REDUCE**
      bull_pulling  : 现价靠近 MA20 (回调买入区)，dip = BUY 机会
      bull_chop     : 5d ATR > 2x 20d ATR (波动放大)，紧仓 + 高 conf 才下单
    """
    sox_today = inp.get("sox_mkt_today_pct") or 0
    spy_today = inp.get("spy_today_pct")     or 0
    sox_5d    = inp.get("sox_mkt_5d_pct")    or 0
    sox_20d   = inp.get("sox_mkt_20d_pct")   or 0

    board_today = min(sox_today, spy_today) if spy_today else sox_today
    macro = {"vix": inp.get("vix"), "fg_score": inp.get("fg"),
             "t10y2y": inp.get("t10y2y")}
    board_mkt = {
        "trend":    "up"   if sox_20d > 0      else "down",
        "ma_stack": "bull" if sox_5d  > sox_20d else "bear",
        "pct_chg":  board_today,
        "pct_chg_zone": _pct_zone(board_today),
    }
    try:
        from decision_agent import get_regime
        base = get_regime(macro, board_mkt)
    except Exception as e:
        logger.warning(f"[regime] classify 失败: {e}")
        return "neutral"

    # 仅 bull_trending 拆子类
    if base != "bull_trending":
        return base

    # 用 SPY 的位置 + 波动估算子类
    try:
        spy_extension = inp.get("spy_extension_pct")  # 现价 vs MA50
        atr_ratio     = inp.get("spy_atr_ratio")      # 5d ATR / 20d ATR
        if spy_extension is not None and spy_extension > 10:
            return "bull_extended"   # 强动量延续
        if atr_ratio is not None and atr_ratio > 2.0:
            return "bull_chop"       # 波动放大
        if spy_extension is not None and abs(spy_extension) < 3:
            return "bull_pulling"    # 接近 MA20 = 回调买入区
    except Exception:
        pass
    return "bull_trending"           # 默认还是粗 bull


def detect_and_save_regime() -> dict:
    """pre-open 调用：算一次 → 写文件 → 返回 dict。"""
    inputs = _build_board_inputs()
    regime = _classify(inputs)
    now_utc = datetime.now(timezone.utc)
    today  = _market_date(now_utc)
    info = {
        "date":   today,
        "regime": regime,
        "ts":     now_utc.isoformat(),
        "ts_et":  now_utc.astimezone(ET).isoformat(),
        "inputs": inputs,
    }
    atomic_write_json(REGIME_STATE_PATH, info)
    return info


def _warn_stale(data: dict, expected: str) -> None:
    global _STALE_WARNED_FOR
    actual = data.get("date")
    key = f"{actual}->{expected}"
    if _STALE_WARNED_FOR == key:
        return
    _STALE_WARNED_FOR = key
    logger.warning(
        f"[regime] regime_state.json 已过期: date={actual!r}, "
        f"expected_market_date={expected!r}; fallback neutral"
    )


def _load_state(*, allow_stale: bool = False) -> dict | None:
    if not REGIME_STATE_PATH.exists():
        return None
    try:
        data = json.loads(REGIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if allow_stale:
        return data
    expected = _market_date()
    if data.get("date") != expected:
        _warn_stale(data, expected)
        return None
    return data


def get_today_regime() -> str:
    """轻量调用：读市场日期匹配的 regime；缺失/失效 fallback 'neutral'。"""
    data = _load_state()
    if not data:
        return "neutral"
    return data.get("regime", "neutral") or "neutral"


def get_today_info(*, allow_stale: bool = False) -> dict:
    """完整的 regime info（含 inputs）。默认拒绝过期状态。"""
    return _load_state(allow_stale=allow_stale) or {}


_REGIME_LABEL = {
    "bull_trending":  "牛市延续 (追趋势, 偏多)",
    "overheated":     "过热警戒 (反转/减仓为主)",
    "recession_risk": "衰退风险 (避险偏向, 仅极端入场)",
    "crisis":         "危机防御 (现金为王, 几乎不动)",
    "neutral":        "中性 (无强方向)",
}


def format_regime_banner(info: dict) -> list[str]:
    """给 logger 用的醒目横幅。规则即前提。"""
    W = 76
    regime = info.get("regime", "neutral")
    label  = _REGIME_LABEL.get(regime, regime)
    inputs = info.get("inputs") or {}

    def _fmt(v, suffix=""):
        if v is None: return "N/A"
        return f"{v:+.2f}{suffix}" if isinstance(v, (int, float)) else str(v)

    lines = [
        "█" * W,
        f"█  今日 REGIME = {regime}  ({label})".ljust(W - 1) + "█",
        f"█  所有今日决策以此为前提（单股暴跌 ≤-5% 时该股 override 成 crisis）".ljust(W - 1) + "█",
        "█" * W,
        f"  输入: SOX 今日={_fmt(inputs.get('sox_mkt_today_pct'),'%'):>8}  "
        f"5日={_fmt(inputs.get('sox_mkt_5d_pct'),'%'):>8}  "
        f"20日={_fmt(inputs.get('sox_mkt_20d_pct'),'%'):>8}",
        f"        SPY 今日={_fmt(inputs.get('spy_today_pct'),'%'):>8}  "
        f"VIX={_fmt(inputs.get('vix')):>6}  "
        f"F&G={_fmt(inputs.get('fg')):>5}  "
        f"T10Y2Y={_fmt(inputs.get('t10y2y')):>6}",
        f"  写入: {REGIME_STATE_PATH.name}  ts={info.get('ts','')[:19]}",
    ]
    # 解读
    rules = {
        "bull_trending":  "  规则: 顺动量, 高残差 z>+2σ 跟仓；REDUCE 阈值放宽",
        "overheated":     "  规则: 反转候选, 低残差 z<-2σ 反弹；REDUCE 阈值收紧",
        "recession_risk": "  规则: 仅 |z|>2.5σ 才动, 反转策略 + 风控优先",
        "crisis":         "  规则: 不开新仓, 卫星仓全空, 核心仓减半",
        "neutral":        "  规则: 仅 |z|>3σ 极端才入场",
    }
    if regime in rules:
        lines.append(rules[regime])
    lines.append("=" * W)
    return lines


if __name__ == "__main__":
    info = detect_and_save_regime()
    for line in format_regime_banner(info):
        print(line)
