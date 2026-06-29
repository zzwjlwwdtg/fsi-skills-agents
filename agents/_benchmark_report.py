"""
_benchmark_report.py
────────────────────
对比系统 NAV 表现 vs SPY/QQQ buy-and-hold。

输出：
  · 累计收益对比
  · 年化收益
  · Sharpe ratio
  · Max Drawdown
  · alpha vs SPY（超额收益）

数据源：
  · 系统 NAV 历史：signals/nav_history.jsonl（每个 ET window paper_trader 写入）
  · SPY/QQQ：yfinance 同期日 K

接入：
  · 手动跑：python _benchmark_report.py
  · 每周末跑：weekly.bat 已接（与 module_accuracy + calibration 一起）
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import os
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

HIST_PATH = Path(__file__).parent / "signals" / "nav_history.jsonl"
REPORT_PATH = Path(__file__).parent / "signals" / "benchmark_report.md"


def load_nav_history() -> pd.DataFrame:
    if not HIST_PATH.exists():
        return pd.DataFrame()
    rows = []
    with open(HIST_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts").sort_index()
    # 每日取最后一笔 NAV
    df = df.groupby(df.index.date).last()
    df.index = pd.to_datetime(df.index)
    return df


def load_benchmark(start_date, end_date, ticker: str = "SPY") -> pd.Series:
    import yfinance as yf
    t = yf.Ticker(ticker)
    df = t.history(start=start_date - pd.Timedelta(days=5),
                    end=end_date + pd.Timedelta(days=2),
                    interval="1d", auto_adjust=True)
    if df.empty:
        return pd.Series(dtype=float)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df["Close"]


def _max_drawdown(series: pd.Series) -> float:
    """Returns max DD as negative percentage."""
    cummax = series.cummax()
    dd = (series - cummax) / cummax * 100
    return float(dd.min()) if not dd.empty else 0


def _sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    if returns.empty or returns.std() == 0:
        return 0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def _annualized_return(series: pd.Series, periods_per_year: int = 252) -> float:
    if len(series) < 2:
        return 0
    total_return = series.iloc[-1] / series.iloc[0] - 1
    days = (series.index[-1] - series.index[0]).days
    if days <= 0:
        return 0
    return (1 + total_return) ** (365 / days) - 1


def compute_stats(nav_series: pd.Series, name: str) -> dict:
    daily_ret = nav_series.pct_change().dropna()
    total_ret = nav_series.iloc[-1] / nav_series.iloc[0] - 1 if len(nav_series) >= 2 else 0
    ann_ret = _annualized_return(nav_series)
    sharpe = _sharpe(daily_ret)
    max_dd = _max_drawdown(nav_series)
    return {
        "name":      name,
        "n_days":    len(nav_series),
        "first":     nav_series.iloc[0] if not nav_series.empty else 0,
        "last":      nav_series.iloc[-1] if not nav_series.empty else 0,
        "total_ret": total_ret * 100,
        "ann_ret":   ann_ret * 100,
        "sharpe":    sharpe,
        "max_dd":    max_dd,
    }


def main():
    nav = load_nav_history()
    if nav.empty:
        print("❌ signals/nav_history.jsonl 为空或不存在")
        print("   → 等 orchestrator 跑几个 ET window 后再来")
        return 1

    nav_series = nav["nav"]
    start_dt, end_dt = nav_series.index[0], nav_series.index[-1]

    print("=" * 78)
    print("  Benchmark 报告")
    print(f"  期间: {start_dt.date()} → {end_dt.date()}  ({len(nav)} 个交易日)")
    print("=" * 78)

    if len(nav) < 5:
        print(f"\n⚠️  只有 {len(nav)} 个数据点，统计意义不足。建议 ≥ 20 个交易日再看。")
        print()

    sys_stats = compute_stats(nav_series, "系统 NAV")

    spy_close = load_benchmark(start_dt, end_dt, "SPY")
    qqq_close = load_benchmark(start_dt, end_dt, "QQQ")

    # 把基准对齐到系统 NAV 的日期范围
    spy = spy_close.reindex(nav_series.index, method="ffill").dropna()
    qqq = qqq_close.reindex(nav_series.index, method="ffill").dropna()

    spy_norm = spy / spy.iloc[0] * sys_stats["first"] if not spy.empty else pd.Series()
    qqq_norm = qqq / qqq.iloc[0] * sys_stats["first"] if not qqq.empty else pd.Series()

    spy_stats = compute_stats(spy_norm, "SPY buy & hold") if not spy_norm.empty else None
    qqq_stats = compute_stats(qqq_norm, "QQQ buy & hold") if not qqq_norm.empty else None

    def _row(s):
        if s is None:
            return ""
        return (f"  {s['name']:<18} {s['first']:>12,.0f} → {s['last']:>12,.0f}  "
                f"{s['total_ret']:>+7.2f}%  ann={s['ann_ret']:>+6.2f}%  "
                f"Sharpe={s['sharpe']:>+5.2f}  MaxDD={s['max_dd']:>+6.2f}%")

    print()
    print(_row(sys_stats))
    if spy_stats: print(_row(spy_stats))
    if qqq_stats: print(_row(qqq_stats))

    print()
    print("=" * 78)
    print("  Alpha 分析（相对 SPY）")
    print("=" * 78)
    if spy_stats:
        alpha_total = sys_stats["total_ret"] - spy_stats["total_ret"]
        alpha_ann   = sys_stats["ann_ret"]   - spy_stats["ann_ret"]
        verdict = ("✅ 系统跑赢基准" if alpha_total > 0
                    else "❌ 系统跑输基准——edge 存疑")
        print(f"  累计 alpha     : {alpha_total:+.2f}%")
        print(f"  年化 alpha     : {alpha_ann:+.2f}%")
        print(f"  Sharpe 差     : {sys_stats['sharpe'] - spy_stats['sharpe']:+.2f}")
        print(f"  Max DD 差    : {sys_stats['max_dd'] - spy_stats['max_dd']:+.2f}pp  "
              f"({'风控更好' if sys_stats['max_dd'] > spy_stats['max_dd'] else '回撤更深'})")
        print(f"  → {verdict}")

    # 写 markdown 报告
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(f"# Benchmark 报告\n\n")
            f.write(f"生成时间: {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"期间: {start_dt.date()} → {end_dt.date()}  ({len(nav)} 个交易日)\n\n")
            f.write(f"## 累计表现\n\n")
            f.write(f"| 标的 | 起 | 终 | 累计 | 年化 | Sharpe | Max DD |\n")
            f.write(f"|---|---|---|---|---|---|---|\n")
            for s in [sys_stats, spy_stats, qqq_stats]:
                if s is None: continue
                f.write(f"| {s['name']} | ${s['first']:,.0f} | ${s['last']:,.0f} | "
                        f"{s['total_ret']:+.2f}% | {s['ann_ret']:+.2f}% | "
                        f"{s['sharpe']:+.2f} | {s['max_dd']:+.2f}% |\n")
            if spy_stats:
                f.write(f"\n## vs SPY\n\n")
                f.write(f"- 累计 alpha: **{sys_stats['total_ret'] - spy_stats['total_ret']:+.2f}%**\n")
                f.write(f"- 年化 alpha: **{sys_stats['ann_ret'] - spy_stats['ann_ret']:+.2f}%**\n")
                f.write(f"- Max DD 差: {sys_stats['max_dd'] - spy_stats['max_dd']:+.2f}pp\n")
        print(f"\n报告保存到: {REPORT_PATH}")
    except Exception as exc:
        print(f"\n报告保存失败: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
