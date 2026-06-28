"""
_backtest_divergence.py
───────────────────────
方案 C 回测：顶/底背离能否预测 5d 方向？

测试集：
  · 训练集：TQQQ/SOXL/DRAM/MULL/GLD
  · OOS：SPY/QQQ/IWM/NVDA/AAPL/TSLA/NFLX/META/7203.T/6758.T/9984.T/USO

判定：
  · 触发日 5d 下跌率 >= 基线 +8pp → 真正有边际预测力
  · 顶背离 confirmed = REDUCE 信号；底背离 = WATCH_BUY 信号
"""
from __future__ import annotations

import os
import sys
import pandas as pd
import numpy as np

os.environ.setdefault("TECHNICAL_ONLY", "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from backtest_engine import load_history, add_indicators


def _compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _detect_div(price_series: pd.Series, ind_series: pd.Series, side: str,
                lookback: int = 25, min_gap: int = 4, ind_delta_min: float = 20) -> str | None:
    if len(price_series) < lookback + 5:
        return None
    p = price_series.iloc[-lookback:].reset_index(drop=True)
    ind = ind_series.iloc[-lookback:].reset_index(drop=True)
    peaks = []
    for i in range(2, len(p) - 2):
        if side == "top":
            if p.iloc[i] == p.iloc[i-2:i+3].max():
                peaks.append(i)
        else:
            if p.iloc[i] == p.iloc[i-2:i+3].min():
                peaks.append(i)
    filtered = []
    for idx in peaks:
        if not filtered or idx - filtered[-1] >= min_gap:
            filtered.append(idx)
    if len(filtered) < 2:
        return None
    p1_i, p2_i = filtered[-2], filtered[-1]
    p1_p, p2_p = p.iloc[p1_i], p.iloc[p2_i]
    p1_x, p2_x = ind.iloc[p1_i], ind.iloc[p2_i]
    bars_since = lookback - 1 - p2_i
    if side == "top":
        if p2_p > p1_p * 1.005 and p2_x < p1_x - ind_delta_min:
            return "confirmed" if bars_since >= 2 else "forming"
    else:
        if p2_p < p1_p * 0.995 and p2_x > p1_x + ind_delta_min:
            return "confirmed" if bars_since >= 2 else "forming"
    return None


def analyze(ticker: str, days: int = 250) -> dict | None:
    try:
        df = add_indicators(load_history(ticker, days=days + 60))
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}
    if df.empty:
        return {"ticker": ticker, "error": "no history"}
    df = df.dropna(subset=["rsi_14", "ma20", "ma50", "bb_pct", "cci_20", "vol_ratio"])
    if len(df) < 80:
        return {"ticker": ticker, "error": f"only {len(df)} days"}
    df = df.iloc[-days:].copy()
    df["fwd_5d"] = (df["close"].shift(-5) / df["close"] - 1) * 100

    closes = df["close"].astype(float)
    rsi    = _compute_rsi(closes)
    cci    = df["cci_20"].astype(float)

    # 对每一天，用截至当天的历史窗口跑背离检测
    cci_top, cci_bot, rsi_top, rsi_bot = [], [], [], []
    for i in range(len(df)):
        p_win  = closes.iloc[: i + 1]
        c_win  = cci.iloc[: i + 1]
        r_win  = rsi.iloc[: i + 1]
        cci_top.append(_detect_div(p_win, c_win, "top"))
        cci_bot.append(_detect_div(p_win, c_win, "bot"))
        rsi_top.append(_detect_div(p_win, r_win, "top", ind_delta_min=8))
        rsi_bot.append(_detect_div(p_win, r_win, "bot", ind_delta_min=8))
    df["cci_top"] = cci_top
    df["cci_bot"] = cci_bot
    df["rsi_top"] = rsi_top
    df["rsi_bot"] = rsi_bot

    n = len(df)
    base = df["fwd_5d"].dropna()
    base_dn = float((base < 0).mean() * 100) if len(base) else 0
    base_avg = float(base.mean()) if len(base) else 0

    def _stats(mask):
        sub = df.loc[mask, "fwd_5d"].dropna()
        if sub.empty:
            return {"n": 0, "dn_rate": 0, "avg_fwd": 0}
        return {"n": len(sub),
                "dn_rate": round(float((sub < 0).mean() * 100), 0),
                "avg_fwd": round(float(sub.mean()), 2)}

    # 双指标 confirmed (强信号)
    mask_top_double = (df["cci_top"] == "confirmed") & (df["rsi_top"] == "confirmed")
    mask_bot_double = (df["cci_bot"] == "confirmed") & (df["rsi_bot"] == "confirmed")
    # 单指标 confirmed (中等信号)
    mask_top_single = (df["cci_top"] == "confirmed") ^ (df["rsi_top"] == "confirmed")
    mask_bot_single = (df["cci_bot"] == "confirmed") ^ (df["rsi_bot"] == "confirmed")

    return {
        "ticker": ticker,
        "n_days": n,
        "base_dn_rate": round(base_dn, 0),
        "base_avg_fwd": round(base_avg, 2),
        "top_double":   _stats(mask_top_double),
        "top_single":   _stats(mask_top_single),
        "bot_double":   _stats(mask_bot_double),
        "bot_single":   _stats(mask_bot_single),
    }


def main():
    in_sample = ["TQQQ", "SOXL", "DRAM", "MULL", "GLD"]
    oos = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "TSLA", "NFLX", "META",
           "7203.T", "6758.T", "9984.T", "8035.T", "USO", "TLT"]

    def _print(group_name: str, tickers: list):
        print("=" * 110)
        print(f"  {group_name}")
        print("=" * 110)
        print(f"  {'ticker':<9} {'base_dn%':>9} "
              f"{'TopDouble n':>11} {'dn%':>5} {'avg':>7}  "
              f"{'TopSingle n':>11} {'dn%':>5} {'avg':>7}  "
              f"{'BotDouble n':>11} {'dn%':>5} {'avg':>7}  "
              f"{'BotSingle n':>11} {'dn%':>5} {'avg':>7}")
        print("  " + "-" * 105)
        results = []
        for tk in tickers:
            r = analyze(tk)
            if r is None or r.get("error"):
                print(f"  {tk:<9}  ❌ {r.get('error') if r else '?'}")
                continue
            print(f"  {tk:<9} {r['base_dn_rate']:>8.0f}% "
                  f"{r['top_double']['n']:>11d} {r['top_double']['dn_rate']:>4.0f}% {r['top_double']['avg_fwd']:>+7.2f}%  "
                  f"{r['top_single']['n']:>11d} {r['top_single']['dn_rate']:>4.0f}% {r['top_single']['avg_fwd']:>+7.2f}%  "
                  f"{r['bot_double']['n']:>11d} {r['bot_double']['dn_rate']:>4.0f}% {r['bot_double']['avg_fwd']:>+7.2f}%  "
                  f"{r['bot_single']['n']:>11d} {r['bot_single']['dn_rate']:>4.0f}% {r['bot_single']['avg_fwd']:>+7.2f}%")
            results.append(r)
        return results

    print(f"\n方案 C 回测 — 顶/底背离能否预测 5d 方向？\n")
    in_res = _print("训练集 (5 标的，用于设计调参)", in_sample)
    oos_res = _print("OOS 测试集 (14 标的)", oos)

    # 聚合
    def _agg(results, key):
        total_n = sum(r[key]["n"] for r in results)
        if total_n == 0: return None
        wdr = sum(r[key]["n"] * r[key]["dn_rate"] for r in results) / total_n
        wfwd = sum(r[key]["n"] * r[key]["avg_fwd"] for r in results) / total_n
        return {"n": total_n, "dn_rate": round(wdr, 1), "avg_fwd": round(wfwd, 2)}

    def _base_agg(results):
        total = sum(r["n_days"] for r in results)
        wdr = sum(r["n_days"] * r["base_dn_rate"] for r in results) / total
        wavg = sum(r["n_days"] * r["base_avg_fwd"] for r in results) / total
        return wdr, wavg

    for name, res in [("训练集", in_res), ("OOS", oos_res)]:
        if not res: continue
        bdr, bavg = _base_agg(res)
        print(f"\n  {name} 聚合（基线 5d 下跌率 {bdr:.1f}% / 平均 {bavg:+.2f}%）:")
        for key, label in [("top_double", "顶背离双共振"), ("top_single", "顶背离单"),
                            ("bot_double", "底背离双共振"), ("bot_single", "底背离单")]:
            agg = _agg(res, key)
            if agg:
                edge = agg["dn_rate"] - bdr
                want_high = key.startswith("top")
                arrow = "✓" if (edge > 8 if want_high else edge < -8) else (
                    "·" if abs(edge) <= 4 else "✗")
                print(f"    {label:<14}: n={agg['n']:>3}  5d 下跌率 {agg['dn_rate']:>5.1f}% "
                      f"({edge:+6.1f}pp)  平均 {agg['avg_fwd']:+6.2f}% {arrow}")


if __name__ == "__main__":
    main()
