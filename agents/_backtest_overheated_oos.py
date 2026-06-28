"""
_backtest_overheated_oos.py
───────────────────────────
out-of-sample 回测：用 A+B 方案跑训练集之外的标的，
判断阈值（CCI>150 / 5d>15% / RSI>68 等）是不是过拟合到
TQQQ/SOXL/DRAM/MULL/GLD。

测试集（不在原 5 标的）：
  · 美股大盘 / 板块 ETF: SPY / QQQ / IWM / DIA / TLT
  · 美股单股: NVDA / AAPL / TSLA / NFLX / META
  · 日股: 7203.T (Toyota) / 6758.T (Sony) / 9984.T (Softbank) /
          6857.T (Advantest) / 8035.T (Tokyo Electron)
  · 商品 / 外汇 ETF: USO / UUP / DBA

判断过拟合的标准：
  · 触发频率：~5-15 次 / 250d 合理；> 30 表示噪音过多
  · 5d 下跌率：> 55% 表示有边际预测力；50% ~ 随机；< 45% 反向
  · 触发日 vs 全样本基线 5d 收益对比
  · 跨资产类一致性：股 / 债 / 商品 / 单股 / 海外 都应有合理表现
"""
from __future__ import annotations

import os
import sys
import pandas as pd
import numpy as np

os.environ.setdefault("TECHNICAL_ONLY", "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from backtest_engine import load_history, add_indicators, build_mkt
from decision_agent import _caution_check, _is_overheated


# ── 测试集（全部 out-of-sample，不在原训练集）─────────────────────────
OOS_GROUPS = {
    "美股大盘 ETF":  ["SPY", "QQQ", "IWM", "DIA"],
    "板块/债 ETF":   ["TLT", "VXUS", "EEM"],
    "美股单股":      ["NVDA", "AAPL", "TSLA", "NFLX", "META"],
    "日股大盘":      ["7203.T", "6758.T", "9984.T", "6857.T", "8035.T"],
    "商品/外汇":     ["USO", "UUP", "DBA"],
}


def _enrich_df(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["cum_5d_pct"]  = (d["close"] / d["close"].shift(5)  - 1) * 100
    d["cum_10d_pct"] = (d["close"] / d["close"].shift(10) - 1) * 100
    d["dist_from_ma20"] = (d["close"] - d["ma20"]) / d["ma20"] * 100
    daily_ret = d["close"].pct_change()
    d["vol_20d_annual"] = daily_ret.rolling(20).std() * (252 ** 0.5) * 100
    d["fwd_5d"] = (d["close"].shift(-5) / d["close"] - 1) * 100
    return d


def _enrich_mkt(row, ticker_full: str) -> dict:
    mkt = build_mkt(ticker_full, row)
    mkt["cum_5d_pct"]  = row.get("cum_5d_pct")
    mkt["cum_10d_pct"] = row.get("cum_10d_pct")
    mkt["dist_from_ma20_pct"] = row.get("dist_from_ma20")
    mkt["bb_upper"]    = float(row.get("bb_upper", 0) or 0)
    mkt["vol_20d_annual"] = row.get("vol_20d_annual")
    return mkt


def analyze_ticker(ticker: str, days: int = 250) -> dict | None:
    """返回单标的统计。失败返回 None。"""
    try:
        df = add_indicators(load_history(ticker, days=days + 60))
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}
    if df.empty:
        return {"ticker": ticker, "error": "no history"}
    df = df.dropna(subset=["rsi_14", "ma20", "ma50", "bb_pct", "cci_20", "vol_ratio"])
    if len(df) < 60:
        return {"ticker": ticker, "error": f"only {len(df)} days valid"}
    df = _enrich_df(df).iloc[-days:]
    df = df.dropna(subset=["cum_5d_pct"])

    # 跑每日 CAUTION + overheated 检查
    caution_dates, oh_dates = [], []
    full = ticker.startswith(".") and ticker or (f"US.{ticker}" if "." not in ticker else ticker)
    for date, r in df.iterrows():
        mkt = _enrich_mkt(r, full)
        c, _ = _caution_check(mkt)
        o, _ = _is_overheated(mkt)
        if c: caution_dates.append(date)
        if o: oh_dates.append(date)

    n_total = len(df)
    base_fwd = df["fwd_5d"].dropna()
    base_avg = float(base_fwd.mean()) if len(base_fwd) else 0
    base_dn  = float((base_fwd < 0).mean() * 100) if len(base_fwd) else 0

    def _stats(dates: list) -> dict:
        sub = df.loc[dates, "fwd_5d"].dropna() if dates else pd.Series([], dtype=float)
        if sub.empty:
            return {"n": 0, "dn_rate": 0, "avg_fwd": 0}
        return {
            "n": len(sub),
            "dn_rate": round(float((sub < 0).mean() * 100), 0),
            "avg_fwd": round(float(sub.mean()), 2),
        }

    return {
        "ticker":  ticker,
        "n_days":  n_total,
        "base_dn_rate": round(base_dn, 0),
        "base_avg_fwd": round(base_avg, 2),
        "caution":  _stats(caution_dates),
        "overheated": _stats(oh_dates),
    }


def main():
    print("=" * 110)
    print("  A+B 方案 OUT-OF-SAMPLE 回测（验证是否过拟合到 TQQQ/SOXL/DRAM/MULL/GLD）")
    print("=" * 110)
    print()
    print(f"  {'ticker':<10} {'days':>5} {'base_dn%':>9} {'base_avg':>10} "
          f"{'CAU n':>6} {'CAU_dn%':>9} {'CAU_avg':>9} "
          f"{'OH n':>5} {'OH_dn%':>8} {'OH_avg':>8} {'判定':<14}")
    print("  " + "-" * 105)

    all_results = []
    for group, tickers in OOS_GROUPS.items():
        print(f"\n  ── {group} ──")
        for tk in tickers:
            r = analyze_ticker(tk)
            if r is None or r.get("error"):
                err = r.get("error", "?") if r else "?"
                print(f"  {tk:<10}  ❌ {err}")
                continue
            cau = r["caution"]
            oh  = r["overheated"]
            # 判定
            cau_edge = cau["dn_rate"] - r["base_dn_rate"] if cau["n"] > 3 else None
            oh_edge  = oh["dn_rate"]  - r["base_dn_rate"] if oh["n"]  > 3 else None
            verdict_parts = []
            if cau_edge is not None:
                if cau_edge > 8:    verdict_parts.append("CAU+")
                elif cau_edge > 0:  verdict_parts.append("CAU·")
                else:               verdict_parts.append("CAU-")
            if oh_edge is not None:
                if oh_edge > 8:     verdict_parts.append("OH+")
                elif oh_edge > 0:   verdict_parts.append("OH·")
                else:               verdict_parts.append("OH-")
            verdict = " ".join(verdict_parts) or "样本少"

            print(f"  {tk:<10} {r['n_days']:>5d} {r['base_dn_rate']:>8.0f}% {r['base_avg_fwd']:>+9.2f}% "
                  f"{cau['n']:>5d} {cau['dn_rate']:>7.0f}% {cau['avg_fwd']:>+8.2f}% "
                  f"{oh['n']:>4d} {oh['dn_rate']:>6.0f}% {oh['avg_fwd']:>+7.2f}% {verdict}")
            all_results.append(r)

    # 跨标的聚合
    print()
    print("=" * 110)
    print("  聚合统计（所有 OOS 标的）")
    print("=" * 110)
    if all_results:
        # 加权平均（按样本数）
        def _agg(key):
            total_n = sum(r[key]["n"] for r in all_results)
            if total_n == 0:
                return None
            wdr = sum(r[key]["n"] * r[key]["dn_rate"] for r in all_results) / total_n
            wfwd = sum(r[key]["n"] * r[key]["avg_fwd"] for r in all_results) / total_n
            return {"n": total_n, "dn_rate": wdr, "avg_fwd": wfwd}

        total_days = sum(r["n_days"] for r in all_results)
        base_dn = sum(r["n_days"] * r["base_dn_rate"] for r in all_results) / total_days
        base_avg = sum(r["n_days"] * r["base_avg_fwd"] for r in all_results) / total_days
        print(f"  基线（无触发）: 5d 下跌率 {base_dn:.1f}%   平均 5d 收益 {base_avg:+.2f}%")
        agg_cau = _agg("caution")
        agg_oh  = _agg("overheated")
        if agg_cau:
            edge = agg_cau["dn_rate"] - base_dn
            print(f"  CAUTION 触发  : n={agg_cau['n']}  5d 下跌率 {agg_cau['dn_rate']:.1f}% "
                  f"({edge:+.1f}pp vs 基线)  平均 5d {agg_cau['avg_fwd']:+.2f}%")
        if agg_oh:
            edge = agg_oh["dn_rate"] - base_dn
            print(f"  overheated 触发: n={agg_oh['n']}  5d 下跌率 {agg_oh['dn_rate']:.1f}% "
                  f"({edge:+.1f}pp vs 基线)  平均 5d {agg_oh['avg_fwd']:+.2f}%")

    print()
    print("  判定符号：")
    print("    CAU+/OH+ : 触发日 5d 下跌率 > 基线 +8pp（有边际预测力）")
    print("    CAU·/OH· : 触发日略好于基线（+0-8pp）")
    print("    CAU-/OH- : 触发日反而胜率更低（反指标）")


if __name__ == "__main__":
    main()
