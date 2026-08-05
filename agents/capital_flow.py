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

    # 今日的 bars（本日日本时间日期）
    today_jp = df.index.max().strftime("%Y-%m-%d")
    today = df[df["date"] == today_jp].copy()
    if today.empty:
        # 若非交易日/盘外时段，用最近有数据的一天
        latest_date = df["date"].max()
        today = df[df["date"] == latest_date].copy()

    # 异常 bar：ratio ≥ 3 且成交量 ≥ 10 * 1000（避免小盘噪音）
    anomaly_bars = today[
        (today["vol_ratio"] >= 3.0) & (today["Volume"] >= 10_000)
    ].sort_values("vol_ratio", ascending=False)

    peak_bars = []
    for ts, row in anomaly_bars.head(8).iterrows():
        o = float(row["Open"])
        c = float(row["Close"])
        chg_pct = (c - o) / o * 100 if o > 0 else 0
        # 方向：主动买 = close>open 拉升，主动卖 = close<open 压价
        if chg_pct > 0.10:
            direction = "buy"
        elif chg_pct < -0.10:
            direction = "sell"
        else:
            direction = "flat"
        vol = int(row["Volume"])
        value_yen = vol * c
        peak_bars.append({
            "time":      ts.strftime("%H:%M"),
            "vol":       vol,
            "ratio":     round(float(row["vol_ratio"]), 2),
            "open":      round(o, 2),
            "price":     round(c, 2),  # keep 'price'=close for backward compat
            "chg_pct":   round(chg_pct, 2),
            "direction": direction,
            "value_oku": round(value_yen / 1e8, 2),   # 億円 (JP notional unit)
        })

    # 汇总：按方向拆分股数 → 买/卖比
    buy_shares  = sum(b["vol"] for b in peak_bars if b["direction"] == "buy")
    sell_shares = sum(b["vol"] for b in peak_bars if b["direction"] == "sell")
    buy_value_oku  = round(sum(b["value_oku"] for b in peak_bars if b["direction"] == "buy"), 2)
    sell_value_oku = round(sum(b["value_oku"] for b in peak_bars if b["direction"] == "sell"), 2)
    net_bias = "neutral"
    if buy_shares >= sell_shares * 2 and buy_shares >= 20_000:
        net_bias = "buy"
    elif sell_shares >= buy_shares * 2 and sell_shares >= 20_000:
        net_bias = "sell"

    # 今日 total volume vs 20 日日均
    daily_total_today = float(today["Volume"].sum())
    daily_avg = df.groupby("date")["Volume"].sum().tail(20).mean()
    day_ratio = daily_total_today / daily_avg if daily_avg > 0 else 0

    detected = bool(len(peak_bars) >= 1 or day_ratio >= 1.8)
    reason = ""
    if peak_bars:
        top = peak_bars[0]
        dir_zh = {"buy": "主动买", "sell": "主动卖", "flat": "换手"}[top["direction"]]
        reason = f"{top['time']} {top['ratio']}× 均值 · {dir_zh} ¥{top['value_oku']}億 (@¥{top['price']})"
    elif day_ratio >= 1.8:
        reason = f"当日总量 {day_ratio:.2f}× 20 日日均"

    return {
        "flow": None,   # yfinance 无 broker 分类，无法拆 super/big/mid/small
        "anomaly": {
            "detected":  detected,
            "reason":    reason,
            "score":     float(min((max(day_ratio - 1, 0) + len(peak_bars) * 0.2), 1.0)),
            "peak_bars": peak_bars,
            "day_ratio": float(round(day_ratio, 2)),
            "net_bias":       net_bias,
            "buy_shares":     buy_shares,
            "sell_shares":    sell_shares,
            "buy_value_oku":  buy_value_oku,
            "sell_value_oku": sell_value_oku,
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
