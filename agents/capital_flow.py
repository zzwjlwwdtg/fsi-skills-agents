"""capital_flow.py — 大单/散户资金流向 unified adapter.

美股：moomoo OpenD `get_capital_distribution` — 实时（≤15min 延迟）super/big/mid/small
      净流入分解。需要 moomoo 已订阅相应市场行情。

日股：yfinance 5min K 线 volume anomaly proxy — moomoo JP 需付费订阅，暂用
      成交量代理：某 5min bar 成交量 > 20 日同时间段均值 × 3 → 可疑大单执行。
      T+1 用 JPX ToSTNeT 印证（jp_tostnet.py）。

统一返回结构：
{
  "ticker":       "NVDA",
  "asof":         "2026-08-05T15:20 ET",
  "source":       "moomoo" | "yfinance_intraday" | "unavailable",
  "flow": {          # 有 source=moomoo 时才有完整字段
    "super_net":  270_000_000.0,   # USD
    "big_net":    ...,
    "mid_net":    ...,
    "small_net":  ...,
    "total_net":  ...,
    "smart_pct":  0.42,            # (super_net+big_net)/total_turnover
  },
  "anomaly": {                     # 通用异常标记（两种 source 都有）
    "detected":   True,
    "reason":     "10:38 5min bar 3.2× avg volume",
    "score":      0.85,            # 0-1
    "peak_bars":  [ {time, vol, ratio, price}, ... ]   # 仅 JP intraday 有
  }
}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

# JP 市场对 US.xxx 前缀 tickers 用 moomoo；对 JP.xxxx / xxxx.T 用 yfinance intraday
_JP_TICKER_SUFFIX = ".T"


def _is_jp(ticker: str) -> bool:
    t = (ticker or "").upper().strip()
    return t.endswith(_JP_TICKER_SUFFIX) or t.startswith("JP.")


def _to_yf_symbol(ticker: str) -> str:
    """JP → 6981.T；US.NVDA → NVDA；NVDA → NVDA."""
    t = (ticker or "").upper().strip()
    if t.startswith("JP.") and not t.endswith(".T"):
        return f"{t[3:]}.T"
    if t.startswith("US."):
        return t[3:]
    return t


# ────────────── US 分支 (moomoo) ──────────────

def _fetch_us_flow(ticker: str) -> Optional[dict]:
    try:
        from moomoo_data import get_capital_distribution_via_openD
    except Exception:
        return None
    raw = get_capital_distribution_via_openD(ticker)
    if not raw:
        return None
    total_turnover = raw["total_in"] + raw["total_out"]
    smart_net = raw["super_net"] + raw["big_net"]
    result = {
        "super_net": raw["super_net"],
        "big_net":   raw["big_net"],
        "mid_net":   raw["mid_net"],
        "small_net": raw["small_net"],
        "total_net": raw["net_total"],
        "smart_pct": (smart_net / total_turnover) if total_turnover > 0 else 0,
    }
    # anomaly: super+big net 占比 >±15% 且绝对值 >$50M → 强信号
    smart_pct = float(result["smart_pct"])
    detected = bool(abs(smart_pct) >= 0.15 and abs(smart_net) >= 5e7)
    reason = ""
    if detected:
        direction = "净流入" if smart_net > 0 else "净流出"
        reason = f"主力（super+big）{direction} ${smart_net/1e6:+.1f}M（占总成交额 {smart_pct*100:+.1f}%）"
    return {
        "flow":    {k: float(v) for k, v in result.items()},
        "anomaly": {
            "detected": detected,
            "reason":   reason,
            "score":    float(min(abs(smart_pct) / 0.30, 1.0)) if detected else 0.0,
        },
        "asof":    raw.get("update_time"),
        "source":  "moomoo",
    }


# ────────────── JP 分支 (yfinance intraday volume) ──────────────

def _fetch_jp_flow(ticker: str) -> Optional[dict]:
    """yfinance 5min K → 检测量能异常 bar。"""
    try:
        import yfinance as yf
    except Exception:
        return None
    sym = _to_yf_symbol(ticker)
    try:
        # 拉最近 60 天 5min（yfinance 限制 60 天），需要 20 日基线
        df = yf.Ticker(sym).history(period="60d", interval="5m",
                                    auto_adjust=False)
        if df is None or df.empty:
            return None
    except Exception:
        return None

    import pandas as pd
    df = df.copy()
    # 时区归一化（yfinance 返 Tokyo 或 UTC 混，转 Asia/Tokyo）
    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("Asia/Tokyo")
    except Exception:
        pass

    df["time_of_day"] = df.index.strftime("%H:%M")
    df["date"] = df.index.strftime("%Y-%m-%d")

    # 计算每个时段过去 20 交易日的平均 volume（同时段对比，剔除盘前盘后）
    baseline = df.groupby("time_of_day")["Volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=5).mean()
    )
    df["baseline_vol"] = baseline
    df["vol_ratio"] = df["Volume"] / df["baseline_vol"].replace(0, float("nan"))

    # 计算 daily 均量（用来算每天的 day_ratio）
    daily_totals = df.groupby("date")["Volume"].sum()
    daily_avg = float(daily_totals.tail(20).mean()) if len(daily_totals) else 0

    # 大单信号阈值（去噪）：
    #   ratio ≥ 5× 均量（原 3× 太松，小盘容易触发）
    #   value_oku ≥ 1.0 億円 (~$0.7M) 剔除小碎单
    # 前端渲染的 "异常 bar" 全部满足此双门槛
    RATIO_MIN = 5.0
    VALUE_OKU_MIN = 1.0

    def _analyze_one_day(day_df, date_str: str) -> dict:
        """给定一天的 5min bars → 该日的 anomaly + aggregate summary。"""
        # 初筛：vol_ratio ≥ RATIO_MIN & 最低成交量
        raw_bars = day_df[
            (day_df["vol_ratio"] >= RATIO_MIN) & (day_df["Volume"] >= 10_000)
        ].sort_values("vol_ratio", ascending=False)

        peak_bars = []
        for ts, row in raw_bars.head(8).iterrows():
            o = float(row["Open"])
            c = float(row["Close"])
            chg_pct = (c - o) / o * 100 if o > 0 else 0
            if chg_pct > 0.10:
                direction = "buy"
            elif chg_pct < -0.10:
                direction = "sell"
            else:
                direction = "flat"
            vol = int(row["Volume"])
            value_oku = round(vol * c / 1e8, 2)
            # 二筛：金额 ≥ ¥1億 才算大单
            if value_oku < VALUE_OKU_MIN:
                continue
            peak_bars.append({
                "time":      ts.strftime("%H:%M"),
                "vol":       vol,
                "ratio":     round(float(row["vol_ratio"]), 2),
                "open":      round(o, 2),
                "price":     round(c, 2),
                "chg_pct":   round(chg_pct, 2),
                "direction": direction,
                "value_oku": value_oku,
                "date":      date_str,           # 让 highlights 反溯来源日
            })

        buy_shares  = sum(b["vol"] for b in peak_bars if b["direction"] == "buy")
        sell_shares = sum(b["vol"] for b in peak_bars if b["direction"] == "sell")
        buy_value  = round(sum(b["value_oku"] for b in peak_bars if b["direction"] == "buy"), 2)
        sell_value = round(sum(b["value_oku"] for b in peak_bars if b["direction"] == "sell"), 2)
        net_bias = "neutral"
        if buy_shares >= sell_shares * 2 and buy_shares >= 20_000:
            net_bias = "buy"
        elif sell_shares >= buy_shares * 2 and sell_shares >= 20_000:
            net_bias = "sell"

        # 该日全部 bar 的 tick-rule 净方向（不只 anomaly，用于对齐"主力流出"这种定义）
        day_up_bars   = day_df[day_df["Close"] > day_df["Open"]]
        day_down_bars = day_df[day_df["Close"] < day_df["Open"]]
        full_up_value   = round(float((day_up_bars["Volume"]   * day_up_bars["Close"]).sum())   / 1e8, 2)
        full_down_value = round(float((day_down_bars["Volume"] * day_down_bars["Close"]).sum()) / 1e8, 2)
        full_up_shares   = int(day_up_bars["Volume"].sum())
        full_down_shares = int(day_down_bars["Volume"].sum())
        full_bias = "neutral"
        if full_up_value >= full_down_value * 1.5:
            full_bias = "buy"
        elif full_down_value >= full_up_value * 1.5:
            full_bias = "sell"

        # 日 K 涨跌
        day_open  = float(day_df.iloc[0]["Open"])
        day_close = float(day_df.iloc[-1]["Close"])
        day_chg_pct = round((day_close / day_open - 1) * 100, 2) if day_open > 0 else 0

        day_total_vol = float(day_df["Volume"].sum())
        day_ratio = float(round(day_total_vol / daily_avg, 2)) if daily_avg > 0 else 0

        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            date_short = f"{d.month}/{d.day}"
        except Exception:
            date_short = date_str

        return {
            "trading_date":   date_str,
            "date_short":     date_short,
            "peak_bars":      peak_bars,
            "day_ratio":      day_ratio,
            "day_chg_pct":    day_chg_pct,
            "day_open":       round(day_open, 2),
            "day_close":      round(day_close, 2),
            # anomaly-only aggregates
            "net_bias":       net_bias,
            "buy_shares":     buy_shares,
            "sell_shares":    sell_shares,
            "buy_value_oku":  buy_value,
            "sell_value_oku": sell_value,
            # full-day tick-rule aggregates (all bars, 更贴近 app 的"主力"定义)
            "full_bias":            full_bias,
            "full_up_shares":       full_up_shares,
            "full_down_shares":     full_down_shares,
            "full_up_value_oku":    full_up_value,
            "full_down_value_oku":  full_down_value,
        }

    # 最近 N 个交易日（不足则有多少给多少）
    n_days = 5
    unique_dates = sorted(df["date"].unique(), reverse=True)[:n_days]
    days_out = []
    for dstr in unique_dates:
        day_df = df[df["date"] == dstr].copy()
        if day_df.empty:
            continue
        days_out.append(_analyze_one_day(day_df, dstr))
    if not days_out:
        return None

    # 大单精选：从 5 日全部 anomaly bars 里挑 top 3（按 ratio × value_oku 综合评分）
    all_bars = []
    for d in days_out:
        for b in d.get("peak_bars", []):
            score = b["ratio"] * b["value_oku"]   # 简单综合分：既大又异常
            all_bars.append({**b, "_score": round(score, 2), "date_short": d["date_short"]})
    highlights = sorted(all_bars, key=lambda x: x["_score"], reverse=True)[:3]

    top_day = days_out[0]   # 最近一日 = 顶层 backward-compat 字段
    detected = bool(len(top_day["peak_bars"]) >= 1 or top_day["day_ratio"] >= 1.8)
    reason = ""
    if top_day["peak_bars"]:
        top_bar = top_day["peak_bars"][0]
        dir_zh = {"buy": "主动买", "sell": "主动卖", "flat": "换手"}[top_bar["direction"]]
        reason = (f"{top_day['date_short']} {top_bar['time']} {top_bar['ratio']}× 均值 · "
                  f"{dir_zh} ¥{top_bar['value_oku']}億 (@¥{top_bar['price']})")
    elif top_day["day_ratio"] >= 1.8:
        reason = f"{top_day['date_short']} 当日总量 {top_day['day_ratio']:.2f}× 20 日日均"

    return {
        "flow": None,
        "anomaly": {
            "detected":     detected,
            "reason":       reason,
            "score":        float(min((max(top_day["day_ratio"] - 1, 0)
                                       + len(top_day["peak_bars"]) * 0.2), 1.0)),
            # backward-compat: 顶层字段 = 最近一日（原有 UI 无缝）
            "peak_bars":    top_day["peak_bars"],
            "day_ratio":    top_day["day_ratio"],
            "trading_date": top_day["trading_date"],
            "date_short":   top_day["date_short"],
            "net_bias":     top_day["net_bias"],
            "buy_shares":   top_day["buy_shares"],
            "sell_shares":  top_day["sell_shares"],
            "buy_value_oku":  top_day["buy_value_oku"],
            "sell_value_oku": top_day["sell_value_oku"],
            # 新增：5 日历史，前端可展开对比
            "days":         days_out,
            # 5 日大单精选（top 3 by ratio*value_oku）
            "highlights":   highlights,
            # 阈值参数（前端展示 tooltip）
            "thresholds":   {"ratio_min": RATIO_MIN, "value_oku_min": VALUE_OKU_MIN},
        },
        "asof":   df.index.max().strftime("%Y-%m-%d %H:%M %Z"),
        "source": "yfinance_intraday",
    }


# ────────────── 统一入口 ──────────────

def get_capital_flow(ticker: str) -> dict:
    """入口：US → moomoo；JP → yfinance intraday。失败返 source=unavailable。"""
    t = (ticker or "").upper().strip()
    if _is_jp(t):
        r = _fetch_jp_flow(t)
    else:
        r = _fetch_us_flow(t)
    if not r:
        return {
            "ticker": t,
            "source": "unavailable",
            "flow":   None,
            "anomaly": {"detected": False, "reason": "", "score": 0},
            "asof":   None,
        }
    return {"ticker": t, **r}


if __name__ == "__main__":
    import json as _json
    import sys
    for tk in (sys.argv[1:] or ["NVDA", "6981.T", "TSLA"]):
        print(f"\n=== {tk} ===")
        print(_json.dumps(get_capital_flow(tk), ensure_ascii=False, indent=2, default=str))
