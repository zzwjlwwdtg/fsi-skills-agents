"""
gold_macro.py — 黄金宏观驱动信号

聚合所有黄金价格的宏观驱动因素，输出结构化 dict 供 _gold_rules 消费。
替代 events_watch 里粗糙的 keyword-based gold_bias。

驱动逻辑（按学术 / 业界共识）：
  · 实际利率 (DFII10) — **黄金最核心驱动**（负相关 -0.7~-0.85）
    - 实际利率上升 → 黄金机会成本上升 → bearish
    - 实际利率下降 → bullish
  · 美元指数 (DXY) — 负相关 (-0.6~-0.8)
    - USD ↑ → GLD 以美元计价相对走弱 → bearish
  · Fed 资产负债表 (WALCL) — QE/QT 信号
    - 缩表 → 流动性收紧 → 利空黄金
  · 10Y 名义利率 (DGS10) — 长期资金成本
    - 升 → bearish（如果不是因通胀预期升驱动）
  · WTI 原油 (DCOILWTICO) — 通胀代理
    - 升 → 通胀预期升 → 黄金对冲需求 → bullish
  · FOMC 政策方向 — 来自 events_watch._get_event_result("FOMC Decision")
    - "降息" → bullish
    - "加息" → bearish
    - "维持" → neutral

输出 schema:
  {
    "real_rate": {"value": 1.8, "trend": "rising/falling/flat", "weight": 0-3},
    "usd_index": {"value": 102.5, "pct_5d": +0.3, "trend": "...", "weight": ...},
    "fed_balance": {"value": 7200000, "trend": "shrinking/expanding/flat", "weight": ...},
    "nominal_yield_10y": {"value": 4.54, "pct_5d": +0.05, "trend": "...", "weight": ...},
    "oil_wti": {"value": 92.6, "pct_5d": +5.0, "trend": "...", "weight": ...},
    "fomc_recent": {"direction": "dovish/hawkish/neutral", "value": "3.63%", "weight": ...},
    "composite": {
        "direction": "bullish/bearish/neutral",
        "score": -3 ~ +3,
        "confidence": 0-10,
        "reasoning": "实际利率高 + USD 强 + 缩表三重压制"
    },
    "fallback": bool   # 数据拿不到时 True，下游降级用 keyword 法
  }

调用：
  from gold_macro import get_gold_macro_signal
  sig = get_gold_macro_signal()
"""
from __future__ import annotations

from datetime import datetime


def _trend_label(curr: float, prev: float, threshold_pct: float = 0.5) -> str:
    """简单趋势：相对变化超过 threshold 算 rising/falling，否则 flat。"""
    if prev is None or prev == 0:
        return "flat"
    pct = (curr - prev) / prev * 100
    if pct > threshold_pct:
        return "rising"
    if pct < -threshold_pct:
        return "falling"
    return "flat"


def _analyze_real_rate(fred: dict) -> dict:
    """DFII10：实际利率 — 黄金最核心驱动（负相关 -0.85）。"""
    d = fred.get("DFII10", {})
    val = d.get("value")
    if val is None:
        return {"value": None, "trend": "n/a", "weight": 0,
                "direction": "neutral", "fallback": True}
    v5 = d.get("value_5d_ago")
    trend = _trend_label(val, v5, threshold_pct=2.0) if v5 else "flat"
    # 方向（对黄金影响）：实际利率升 → bearish
    direction = "bearish" if trend == "rising" else ("bullish" if trend == "falling" else "neutral")
    # 权重：核心驱动，给 2-3 分
    weight = 3 if trend != "flat" else 1
    # 实际利率绝对水平：> 2.5% 高 / < 1.0% 低
    abs_level = "high" if val > 2.5 else ("low" if val < 1.0 else "mid")
    return {"value": round(val, 3), "value_5d_ago": v5,
            "trend": trend, "abs_level": abs_level,
            "direction": direction, "weight": weight, "fallback": False}


def _analyze_usd(dxy: dict) -> dict:
    """DXY 美元指数 — 黄金负相关 (-0.7)。"""
    val = dxy.get("value")
    if val is None:
        return {"value": None, "trend": "n/a", "weight": 0,
                "direction": "neutral", "fallback": True}
    pct5 = dxy.get("pct_chg_5d", 0)
    pct20 = dxy.get("pct_chg_20d", 0)
    if pct5 > 1.0:    trend = "rising"
    elif pct5 < -1.0: trend = "falling"
    else:             trend = "flat"
    direction = "bearish" if trend == "rising" else ("bullish" if trend == "falling" else "neutral")
    # 强趋势加权
    weight = 2 if abs(pct5) > 1.0 else (1 if abs(pct5) > 0.3 else 0)
    return {"value": round(val, 2), "pct_chg_5d": round(pct5, 2),
            "pct_chg_20d": round(pct20, 2),
            "trend": trend, "direction": direction,
            "weight": weight, "fallback": False}


def _analyze_fed_balance(fred: dict) -> dict:
    """WALCL：Fed 资产负债表。QT (缩表) → 流动性紧 → 利空黄金。"""
    d = fred.get("WALCL", {})
    val = d.get("value")
    if val is None:
        return {"value": None, "trend": "n/a", "weight": 0,
                "direction": "neutral", "fallback": True}
    v20 = d.get("value_20d_ago")
    if v20:
        pct20 = (val - v20) / v20 * 100
        # WALCL 是周频，变化幅度小：> 0.5% 算 expanding，< -0.5% 算 shrinking
        if pct20 > 0.5:    trend = "expanding"
        elif pct20 < -0.5: trend = "shrinking"
        else:              trend = "flat"
    else:
        pct20 = 0
        trend = "flat"
    direction = "bullish" if trend == "expanding" else ("bearish" if trend == "shrinking" else "neutral")
    weight = 1 if trend != "flat" else 0   # QT/QE 是慢变量，权重小
    return {"value": round(val, 0), "pct_chg_20d": round(pct20, 2),
            "trend": trend, "direction": direction,
            "weight": weight, "fallback": False}


def _analyze_nominal_yield(fred: dict) -> dict:
    """DGS10：10Y 名义利率。升 → bearish 黄金（如果不是通胀预期驱动）。"""
    d = fred.get("DGS10", {})
    val = d.get("value")
    if val is None:
        return {"value": None, "trend": "n/a", "weight": 0,
                "direction": "neutral", "fallback": True}
    v5 = d.get("value_5d_ago")
    trend = _trend_label(val, v5, threshold_pct=2.0) if v5 else "flat"
    direction = "bearish" if trend == "rising" else ("bullish" if trend == "falling" else "neutral")
    weight = 1 if trend != "flat" else 0
    return {"value": round(val, 2), "value_5d_ago": v5,
            "trend": trend, "direction": direction,
            "weight": weight, "fallback": False}


def _analyze_oil(fred: dict) -> dict:
    """DCOILWTICO：原油。升 → 通胀预期升 → 黄金对冲需求 → bullish。"""
    d = fred.get("DCOILWTICO", {})
    val = d.get("value")
    if val is None:
        return {"value": None, "trend": "n/a", "weight": 0,
                "direction": "neutral", "fallback": True}
    v5 = d.get("value_5d_ago")
    if v5:
        pct5 = (val - v5) / v5 * 100
        if pct5 > 5.0:    trend = "rising"
        elif pct5 < -5.0: trend = "falling"
        else:             trend = "flat"
    else:
        pct5 = 0
        trend = "flat"
    direction = "bullish" if trend == "rising" else ("bearish" if trend == "falling" else "neutral")
    weight = 1 if abs(pct5) > 5.0 else 0
    return {"value": round(val, 2), "pct_chg_5d": round(pct5, 2),
            "trend": trend, "direction": direction,
            "weight": weight, "fallback": False}


def _analyze_fomc() -> dict:
    """从 events_watch._get_event_result 拉最近 FOMC 决议，推鸽派/鹰派。"""
    try:
        from events_watch import _get_event_result
        # FOMC 是 events_watch._EVENT_VERIFY 里定义的；调用方式同 generate_event_calendar_report
        # 简化：直接看最近一次 FEDFUNDS 变化
        from fred_feeds import fetch_fred
        fred = fetch_fred()
        funds = fred.get("FEDFUNDS", {}).get("value")
        if funds is None:
            return {"direction": "neutral", "weight": 0, "fallback": True}
        # 拉 2 个观察看变化
        from urllib.request import Request, urlopen
        import json
        from config import FRED_API_KEY
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id=FEDFUNDS&api_key={FRED_API_KEY}"
               f"&sort_order=desc&limit=2&file_type=json")
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=8) as r:
            data = json.load(r)
        vals = [float(o["value"]) for o in data["observations"] if o["value"] != "."]
        if len(vals) < 2:
            return {"direction": "neutral", "weight": 0, "value": funds, "fallback": False}
        curr, prev = vals[0], vals[1]
        delta_bp = (curr - prev) * 100  # bp
        if delta_bp < -5:    direction, label = "dovish", f"降息 {abs(delta_bp):.0f}bp → {curr:.2f}%"
        elif delta_bp > 5:   direction, label = "hawkish", f"加息 {delta_bp:.0f}bp → {curr:.2f}%"
        else:                direction, label = "neutral", f"维持 {curr:.2f}%"
        # FOMC 影响黄金：dovish → bullish，hawkish → bearish
        gold_dir = "bullish" if direction == "dovish" else ("bearish" if direction == "hawkish" else "neutral")
        weight = 2 if direction != "neutral" else 0
        return {"direction": gold_dir, "fomc_direction": direction,
                "value": curr, "label": label, "delta_bp": delta_bp,
                "weight": weight, "fallback": False}
    except Exception:
        return {"direction": "neutral", "weight": 0, "fallback": True}


def get_gold_macro_signal() -> dict:
    """主入口：拉所有宏观数据 → 聚合成 gold_macro_signal dict。

    任何子模块失败都不抛错，只在对应字段标 fallback=True。
    全部 fallback 时整体 fallback=True，下游降级到原 keyword 法。
    """
    from fred_feeds import fetch_fred
    from data_feeds import fetch_dxy

    try:
        fred = fetch_fred()
    except Exception:
        fred = {}
    try:
        dxy = fetch_dxy()
    except Exception:
        dxy = {}

    real_rate = _analyze_real_rate(fred)
    usd = _analyze_usd(dxy)
    fed_bs = _analyze_fed_balance(fred)
    nominal = _analyze_nominal_yield(fred)
    oil = _analyze_oil(fred)
    fomc = _analyze_fomc()

    # 加权聚合：每个因子按 weight × direction_sign 累加
    sub_signals = [real_rate, usd, fed_bs, nominal, oil, fomc]
    total_score = 0
    reasons = []
    for s in sub_signals:
        d = s.get("direction")
        w = s.get("weight", 0)
        if d == "bullish":  total_score += w
        elif d == "bearish": total_score -= w

    # 整体方向
    if total_score >= 2:
        composite_dir = "bullish"
    elif total_score <= -2:
        composite_dir = "bearish"
    else:
        composite_dir = "neutral"

    # 推理（前 3 个最重的因子）
    sorted_subs = sorted(
        [("real_rate", real_rate), ("usd", usd), ("fed_balance", fed_bs),
         ("nominal_yield", nominal), ("oil", oil), ("fomc", fomc)],
        key=lambda x: x[1].get("weight", 0), reverse=True
    )
    for name, s in sorted_subs[:3]:
        if s.get("weight", 0) > 0 and s.get("direction") != "neutral":
            reasons.append(f"{name}({s.get('direction')})")
    reasoning = " + ".join(reasons) if reasons else "无强宏观信号"

    # confidence：累计权重越高越自信
    total_weight = sum(s.get("weight", 0) for s in sub_signals)
    confidence = min(total_weight * 2, 10)

    all_fallback = all(s.get("fallback", False) for s in sub_signals)

    return {
        "ts": datetime.now().isoformat(),
        "real_rate": real_rate,
        "usd_index": usd,
        "fed_balance": fed_bs,
        "nominal_yield_10y": nominal,
        "oil_wti": oil,
        "fomc_recent": fomc,
        "composite": {
            "direction": composite_dir,
            "score": total_score,
            "confidence": confidence,
            "reasoning": reasoning,
        },
        "fallback": all_fallback,
    }


def format_gold_macro_banner(sig: dict) -> list[str]:
    """格式化为多行 banner 输出（供 snapshot / orchestrator 显示）。"""
    W = 76
    lines = ["+" + "=" * (W - 2) + "+",
             f"|  Gold Macro Signal  |  {sig.get('ts', '')[:16]}".ljust(W - 1) + "|",
             "+" + "=" * (W - 2) + "+"]
    if sig.get("fallback"):
        lines.append("  ⚠ 全部宏观数据不可用（无 FRED key 或网络）— 降级到 keyword 法")
        lines.append("=" * W)
        return lines

    comp = sig["composite"]
    lines.append(f"  综合方向: {comp['direction']:<8}  score={comp['score']:+d}  conf={comp['confidence']}/10")
    lines.append(f"  关键驱动: {comp['reasoning']}")
    lines.append("  " + "-" * (W - 4))

    def _fmt(name: str, sub: dict, *fields):
        if sub.get("fallback"):
            return f"  {name:<14} 数据不可用"
        d = sub.get("direction", "neutral")
        w = sub.get("weight", 0)
        arrow = {"bullish": "▲", "bearish": "▼", "neutral": "·"}.get(d, "·")
        parts = []
        for f in fields:
            v = sub.get(f)
            if v is not None:
                parts.append(f"{f}={v}")
        extra = " ".join(parts)
        return f"  {arrow} {name:<14} dir={d:<8} w={w}  {extra}"

    lines.append(_fmt("实际利率", sig["real_rate"], "value", "trend", "abs_level"))
    lines.append(_fmt("美元指数", sig["usd_index"], "value", "pct_chg_5d", "trend"))
    lines.append(_fmt("10Y名义利率", sig["nominal_yield_10y"], "value", "trend"))
    lines.append(_fmt("Fed 资产负债表", sig["fed_balance"], "trend", "pct_chg_20d"))
    lines.append(_fmt("WTI 原油", sig["oil_wti"], "value", "pct_chg_5d", "trend"))
    lines.append(_fmt("FOMC 政策", sig["fomc_recent"], "label", "direction"))
    lines.append("=" * W)
    return lines


def _cli_main():
    import sys, json
    sys.stdout.reconfigure(line_buffering=True)
    sig = get_gold_macro_signal()
    for line in format_gold_macro_banner(sig):
        print(line)
    print()
    print(json.dumps(sig, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli_main()
