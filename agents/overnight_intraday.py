"""
Overnight Premium 回测 — 经典学术异象。

策略 A "隔夜":    每天收盘买, 第二天开盘卖。捕获 (Open[t+1] - Close[t]) 收益
策略 B "日内":    每天开盘买, 当天收盘卖。捕获 (Close[t] - Open[t]) 收益
策略 BH:         buy-and-hold (基线)

学术参考:
  · Cliff, Cooper, Gulen (2008) "Return Differences Between Trading and
    Non-Trading Hours: Like Night and Day"
  · Bogousslavsky (2021) "The cross-section of intraday and overnight
    returns"

数据源: yfinance (含 Open / Close / dividends 复权后).
拉 25+ 年 (1999 起)。结果保存到 signals/overnight_intraday_report.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from config import SIGNALS_DIR


TICKERS = [
    "MU",     # 论文里的例子
    "TQQQ", "SOXL", "GLD",      # 我们的核心
    "SPY", "QQQ",                # 大盘对照
    "NVDA", "AAPL", "MSFT",      # 美股龙头对照
    # 日本股 (yfinance 用 .T 后缀; 注意 yf 也支持 ^N225 指数)
    "7203.T",   # 丰田
    "9984.T",   # 软银 G
    "6758.T",   # 索尼
    "8035.T",   # 东京威力科创 (半导体设备龙头)
    "6857.T",   # 爱德万测试 (半导体)
    "9432.T",   # NTT
    "^N225",    # 日经 225 指数
]
LOOKBACK_YEARS = 25


def fetch_daily(ticker: str, years: int = 25) -> pd.DataFrame | None:
    """yfinance 拉 daily OHLC (复权)。"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        h = t.history(period=f"{years*365}d", interval="1d", auto_adjust=True)
        if h.empty:
            return None
        h.index = h.index.tz_localize(None) if h.index.tz else h.index
        return h[["Open", "Close"]]
    except Exception as e:
        print(f"[{ticker}] fetch failed: {e}")
        return None


def compute_strategies(df: pd.DataFrame) -> dict:
    """
    给定 OHLC，算 3 个策略每日收益序列 + 累计收益:
      overnight : close[t-1] → open[t]   收益 = open[t]/close[t-1] - 1
      intraday  : open[t] → close[t]      收益 = close[t]/open[t]  - 1
      bh        : close[t-1] → close[t]   收益 = close[t]/close[t-1] - 1
    """
    o = df["Open"].astype(float)
    c = df["Close"].astype(float)
    c_prev = c.shift(1)
    overnight = (o / c_prev - 1).dropna()
    intraday  = (c / o - 1).dropna()
    bh        = (c / c_prev - 1).dropna()
    return {
        "overnight": overnight,
        "intraday":  intraday,
        "bh":        bh,
    }


def stats(returns: pd.Series, name: str) -> dict:
    """计算策略的累计收益 / CAGR / Sharpe / max drawdown / 胜率。"""
    if returns.empty:
        return {"name": name, "n": 0}
    cum = (1 + returns).cumprod()
    n = len(returns)
    years = n / 252
    total_return = cum.iloc[-1] - 1
    cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0
    mean = returns.mean() * 252
    std = returns.std() * np.sqrt(252)
    sharpe = mean / std if std > 0 else 0
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    max_dd = dd.min()
    win_rate = (returns > 0).sum() / len(returns) * 100
    return {
        "name":       name,
        "n":          n,
        "years":      round(years, 1),
        "total_ret":  total_return,
        "cagr":       cagr,
        "sharpe":     sharpe,
        "max_dd":     max_dd,
        "win_rate":   win_rate,
        "cum_end":    cum.iloc[-1],
    }


def fmt_pct(x: float) -> str:
    """大数特化: > 100x 用 e 记号, 其他用 %。"""
    if abs(x) >= 100:
        return f"{x*100:.2e}%" if abs(x) >= 10000 else f"{x*100:,.0f}%"
    return f"{x*100:+.2f}%"


def analyze_ticker(ticker: str, years: int) -> list[dict]:
    df = fetch_daily(ticker, years)
    if df is None or len(df) < 250:
        print(f"[{ticker}] 数据不足")
        return []
    s = compute_strategies(df)
    rows = [
        stats(s["overnight"], "隔夜 (收盘买 → 开盘卖)"),
        stats(s["intraday"],  "日内 (开盘买 → 收盘卖)"),
        stats(s["bh"],        "Buy & Hold (基线)"),
    ]
    for r in rows:
        r["ticker"] = ticker
    return rows


def format_report(all_rows: list[dict]) -> list[str]:
    W = 88
    lines = [
        "+" + "=" * (W - 2) + "+",
        "|  Overnight Premium 回测：隔夜 vs 日内 vs Buy&Hold".ljust(W - 1) + "|",
        f"|  数据源: yfinance (复权 OHLC) · 回溯 {LOOKBACK_YEARS} 年".ljust(W - 1) + "|",
        "+" + "=" * (W - 2) + "+",
    ]
    by_ticker: dict[str, list[dict]] = {}
    for r in all_rows:
        by_ticker.setdefault(r["ticker"], []).append(r)
    for tk, rows in by_ticker.items():
        if not rows:
            continue
        rep_n = rows[0].get("n", 0)
        rep_y = rows[0].get("years", 0)
        lines.append("")
        lines.append(f"  === {tk} ===  {rep_n} 个交易日 / 约 {rep_y} 年")
        lines.append(f"  {'策略':<28} {'累计倍数':>12} {'CAGR':>9} {'Sharpe':>7} {'胜率':>7} {'最大回撤':>10}")
        lines.append(f"  {'-'*28} {'-'*12} {'-'*9} {'-'*7} {'-'*7} {'-'*10}")
        for r in rows:
            mult = r.get("cum_end", 1)
            cagr = r.get("cagr", 0)
            sharpe = r.get("sharpe", 0)
            wr = r.get("win_rate", 0)
            dd = r.get("max_dd", 0)
            mult_str = f"{mult:>11.2f}x" if mult < 1000 else f"{mult:>11.2e}"
            lines.append(
                f"  {r['name']:<28} {mult_str:>12} "
                f"{cagr*100:>+8.1f}% {sharpe:>+7.2f} "
                f"{wr:>6.1f}% {dd*100:>+9.1f}%"
            )
    # 总结
    lines.append("")
    lines.append("=" * W)
    lines.append("解读:")
    lines.append("  · 隔夜 (Overnight): 收盘买开盘卖, 捕捉非交易时段收益")
    lines.append("  · 日内 (Intraday): 开盘买收盘卖, 捕捉交易时段收益")
    lines.append("  · 如果隔夜累计倍数 >> 日内 → 收益主要在非交易时段产生 (Overnight Premium)")
    lines.append("  · 这是已被学术验证的真实异象 (非阴谋论)")
    lines.append("")
    lines.append("⚠ 注意:")
    lines.append("  · 此策略对零售不可交易: 每天来回滑点+佣金 = -0.05-0.3%/天 → 长期亏光")
    lines.append("  · MOO/MOC 委托对零售经常成交在不利价 — 真实滑点远大于本回测的零摩擦假设")
    lines.append("  · 学术价值: 揭示市场结构性 bias; 机构能用但成本极低")
    lines.append("=" * W)
    return lines


def main():
    all_rows = []
    for tk in TICKERS:
        print(f"[{tk}] 拉数据 + 计算策略...", flush=True)
        all_rows.extend(analyze_ticker(tk, LOOKBACK_YEARS))

    report_lines = format_report(all_rows)
    for line in report_lines:
        print(line)

    out_path = Path(SIGNALS_DIR) / f"overnight_intraday_{datetime.now().strftime('%Y%m%d')}.md"
    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"\n报告已保存: {out_path}")


if __name__ == "__main__":
    main()
