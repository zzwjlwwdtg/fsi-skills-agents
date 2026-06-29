"""
_backtest_inverse_etf.py
────────────────────────
P4.4 OOS：crisis regime 时自动 BUY 反向 ETF 是否能赚？

假设：当 TQQQ/SOXL 触发 "crisis regime"（单日 ≤ -5% 缩放）时，
      买入对应反向 ETF（SQQQ/SOXS）持有 N 天，应该跑赢 0%。

测试集：
  · TQQQ → SQQQ
  · SOXL → SOXS
  · SPY  → SH（OOS）
  · QQQ  → PSQ（OOS）

判定：
  · 5d 上涨率 ≥ 60%（反向 ETF 涨 = 主体跌延续）
  · 平均 5d 收益 ≥ +2%
  · 否则不上线
"""
from __future__ import annotations

import os
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import yfinance as yf
import pandas as pd
import numpy as np


PAIRS = [
    # (主体, 反向, 主体杠杆) — crisis 触发 = 主体当日缩放后 ≤ -5%
    ("TQQQ", "SQQQ", 3.0),
    ("SOXL", "SOXS", 3.0),
    ("SPY",  "SH",   1.0),
    ("QQQ",  "PSQ",  1.0),
]
HORIZONS = [1, 3, 5, 10]


def analyze(main_tk: str, inv_tk: str, lev: float, days: int = 500) -> dict:
    try:
        main_df = yf.Ticker(main_tk).history(period=f"{days}d", interval="1d", auto_adjust=True)
        inv_df  = yf.Ticker(inv_tk ).history(period=f"{days}d", interval="1d", auto_adjust=True)
    except Exception as e:
        return {"error": str(e)}
    if main_df.empty or inv_df.empty:
        return {"error": "no data"}

    main_df = main_df.rename(columns={"Close": "close"})
    inv_df  = inv_df.rename(columns={"Close": "close"})
    if main_df.index.tz is not None:
        main_df.index = main_df.index.tz_localize(None)
    if inv_df.index.tz is not None:
        inv_df.index = inv_df.index.tz_localize(None)

    main_df["pct"] = main_df["close"].pct_change() * 100
    main_df["pct_scaled"] = main_df["pct"] / lev   # 缩放回 1x 等效

    # 触发：主体当日缩放后 ≤ -5%
    triggers = main_df[main_df["pct_scaled"] <= -5].copy()
    if triggers.empty:
        return {"main": main_tk, "inv": inv_tk, "n_trigger": 0,
                "horizons": {h: {"n": 0} for h in HORIZONS}}

    # 对每次触发，记录次日开盘买入反向 ETF（用 close 代理），N 天后收益
    # 简化：用触发日的 close 作为入场价（实际应是次日 open）
    results = {h: [] for h in HORIZONS}
    for date, row in triggers.iterrows():
        if date not in inv_df.index:
            continue
        entry_price = float(inv_df.loc[date, "close"])
        for h in HORIZONS:
            try:
                fwd_dates = inv_df.index[inv_df.index > date][:h]
                if len(fwd_dates) < h:
                    continue
                exit_price = float(inv_df.loc[fwd_dates[-1], "close"])
                ret = (exit_price - entry_price) / entry_price * 100
                results[h].append(ret)
            except Exception:
                continue

    horizons_stat = {}
    for h, rets in results.items():
        if not rets:
            horizons_stat[h] = {"n": 0, "up_rate": 0, "avg": 0}
            continue
        horizons_stat[h] = {
            "n": len(rets),
            "up_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 0),
            "avg":     round(sum(rets) / len(rets), 2),
        }
    return {
        "main":       main_tk,
        "inv":        inv_tk,
        "lev":        lev,
        "n_trigger":  len(triggers),
        "horizons":   horizons_stat,
    }


def main():
    print("=" * 100)
    print("  P4.4 OOS：crisis regime → 买入反向 ETF 能赚吗？")
    print("=" * 100)
    print()
    print(f"  {'main':<6} {'inv':<6} {'lev':>4} {'#触发':>6}  " +
          "  ".join([f"{h}d↑% / avg" for h in HORIZONS]))
    print("  " + "-" * 90)

    all_results = []
    for main_tk, inv_tk, lev in PAIRS:
        r = analyze(main_tk, inv_tk, lev)
        if r.get("error"):
            print(f"  {main_tk:<6} {inv_tk:<6}  ❌ {r['error']}")
            continue
        all_results.append(r)
        line = f"  {r['main']:<6} {r['inv']:<6} {r['lev']:>3.1f}x {r['n_trigger']:>5d}   "
        for h in HORIZONS:
            s = r["horizons"][h]
            if s["n"] > 0:
                line += f"  {s['up_rate']:>4.0f}% / {s['avg']:>+6.2f}%"
            else:
                line += f"      (n=0)    "
        print(line)

    # 聚合
    print()
    print("=" * 100)
    print("  聚合（全部对子）")
    print("=" * 100)
    for h in HORIZONS:
        total_n = sum(r["horizons"][h]["n"] for r in all_results)
        if total_n == 0: continue
        avg_up   = sum(r["horizons"][h]["up_rate"] * r["horizons"][h]["n"] for r in all_results) / total_n
        avg_ret  = sum(r["horizons"][h]["avg"]     * r["horizons"][h]["n"] for r in all_results) / total_n
        verdict = "✅ 通过" if (avg_up >= 60 and avg_ret >= 2.0) else "❌ 不达标"
        print(f"  {h}d  n={total_n:>3}  上涨率 {avg_up:>5.1f}%  平均收益 {avg_ret:>+6.2f}%  {verdict}")

    print()
    print("  门槛: 上涨率 ≥ 60% AND 平均收益 ≥ +2% 才能 ship。")
    print("  这是单向防御（反向 ETF 做空）, 失败就只能撤回，不该上 live。")


if __name__ == "__main__":
    main()
