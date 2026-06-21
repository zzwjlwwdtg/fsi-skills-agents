"""
Overnight Premium 篮子策略回测 — 5 只流动性最好的股票等权轮换。

回答用户问题:
  · 单只 MU/Toyota 隔夜策略：538x / 1.49e6x
  · 但单只承担 individual stock risk (-100% 可能)
  · 等权 5 只能否得到同样收益且 vol 更低?

策略:
  · BASKET_OVERNIGHT : 每天收盘等权买 5 只, 次日开盘等权卖
  · BASKET_INTRADAY  : 每天开盘等权买 5 只, 当天收盘等权卖
  · BASKET_BH        : 等权买入持有

数据: yfinance daily OHLC. 25 年.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from config import SIGNALS_DIR


# 美股 5 大流动性最佳（按日均成交量）
US_BASKET = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
# 日股 5 大流动性最佳 (TOPIX 大盘)
JP_BASKET = ["7203.T", "6758.T", "9984.T", "8035.T", "6857.T"]

LOOKBACK_YEARS = 25


def fetch_panel(tickers: list[str], years: int) -> dict[str, pd.DataFrame] | None:
    import yfinance as yf
    out = {}
    for tk in tickers:
        h = yf.Ticker(tk).history(period=f"{years*365}d", interval="1d", auto_adjust=True)
        if h.empty:
            continue
        h.index = h.index.tz_localize(None) if h.index.tz else h.index
        out[tk] = h[["Open","Close"]]
    if len(out) < 2:
        return None
    return out


def align_panel(panel: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """对齐到所有股票都有数据的交易日。"""
    opens  = pd.DataFrame({tk: df["Open"]  for tk, df in panel.items()})
    closes = pd.DataFrame({tk: df["Close"] for tk, df in panel.items()})
    opens  = opens.dropna()
    closes = closes.dropna()
    common = opens.index.intersection(closes.index)
    return opens.loc[common], closes.loc[common]


def basket_strategies(opens: pd.DataFrame, closes: pd.DataFrame) -> dict[str, pd.Series]:
    """每天等权配 N 只标的, 算 3 个策略的收益序列。"""
    # 每只股票每天的 overnight / intraday 收益
    closes_prev = closes.shift(1)
    overnight = (opens / closes_prev - 1).dropna()
    intraday  = (closes / opens - 1).dropna()
    bh        = (closes / closes_prev - 1).dropna()
    # 等权篮子: 每天每只各占 1/N
    n = opens.shape[1]
    return {
        "overnight": overnight.sum(axis=1) / n,
        "intraday":  intraday.sum(axis=1)  / n,
        "bh":        bh.sum(axis=1)        / n,
    }


def stats(returns: pd.Series, name: str) -> dict:
    if returns.empty:
        return {"name": name, "n": 0}
    cum = (1 + returns).cumprod()
    n = len(returns)
    years = n / 252
    total = cum.iloc[-1] - 1
    cagr = (cum.iloc[-1]) ** (1/years) - 1 if years > 0 else 0
    mean = returns.mean() * 252
    std = returns.std() * np.sqrt(252)
    sharpe = mean / std if std > 0 else 0
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    return {
        "name": name, "n": n, "years": round(years,1),
        "total": total, "cagr": cagr, "sharpe": sharpe,
        "vol": std, "max_dd": dd.min(),
        "win_rate": (returns > 0).sum() / n * 100,
        "cum_end": cum.iloc[-1],
    }


def analyze(label: str, tickers: list[str], years: int) -> list[dict]:
    print(f"[{label}] {tickers}")
    panel = fetch_panel(tickers, years)
    if not panel:
        return []
    opens, closes = align_panel(panel)
    s = basket_strategies(opens, closes)
    rows = [
        stats(s["overnight"], f"[{label}] 5股等权 隔夜"),
        stats(s["intraday"],  f"[{label}] 5股等权 日内"),
        stats(s["bh"],        f"[{label}] 5股等权 BH (基线)"),
    ]
    # 顺便算每只单股 overnight，对比"集中 vs 分散"
    closes_prev = closes.shift(1)
    overnight = (opens / closes_prev - 1).dropna()
    for tk in tickers:
        single = overnight[tk]
        rows.append(stats(single, f"[{label}] {tk} 单股 隔夜"))
    for r in rows:
        r["group"] = label
    return rows


def format_report(rows: list[dict]) -> list[str]:
    W = 92
    lines = [
        "+" + "="*(W-2) + "+",
        "|  Overnight Premium 篮子 vs 单股对照: 流动性最佳 5 股等权轮换".ljust(W-1) + "|",
        f"|  数据源: yfinance ({LOOKBACK_YEARS} 年, 复权)".ljust(W-1) + "|",
        "+" + "="*(W-2) + "+",
    ]
    by_group: dict[str, list[dict]] = {}
    for r in rows:
        by_group.setdefault(r["group"], []).append(r)
    for group, grp_rows in by_group.items():
        if not grp_rows: continue
        n_days = grp_rows[0].get("n",0)
        n_yrs  = grp_rows[0].get("years",0)
        lines.append("")
        lines.append(f"  === {group} ===  共同交易日 {n_days} / 约 {n_yrs} 年")
        lines.append(f"  {'策略':<32} {'累计倍数':>12} {'CAGR':>9} {'Sharpe':>7} {'年化σ':>7} {'最大回撤':>10}")
        lines.append(f"  {'-'*32} {'-'*12} {'-'*9} {'-'*7} {'-'*7} {'-'*10}")
        for r in grp_rows:
            mult = r.get("cum_end", 1)
            mstr = f"{mult:>11.2f}x" if mult < 1000 else f"{mult:>11.2e}"
            lines.append(
                f"  {r['name'][len(group)+3:]:<32} {mstr:>12} "
                f"{r.get('cagr',0)*100:>+8.1f}% {r.get('sharpe',0):>+7.2f} "
                f"{r.get('vol',0)*100:>6.1f}% {r.get('max_dd',0)*100:>+9.1f}%"
            )
    # 解读
    lines.append("")
    lines.append("=" * W)
    lines.append("关键对照:")
    lines.append("  · 5 股等权 隔夜 vs 单股最佳 隔夜  → 篮子摊薄收益但拉低 vol → Sharpe 通常更高")
    lines.append("  · 5 股等权 隔夜 vs 等权 BH        → 看是否仍跑赢 buy-and-hold")
    lines.append("  · 5 股等权 日内 vs 单股 日内       → 验证 intraday 亏损是否系统性")
    lines.append("=" * W)
    return lines


def main():
    all_rows = []
    all_rows.extend(analyze("US-5", US_BASKET, LOOKBACK_YEARS))
    all_rows.extend(analyze("JP-5", JP_BASKET, LOOKBACK_YEARS))
    lines = format_report(all_rows)
    for line in lines:
        print(line)
    out = Path(SIGNALS_DIR) / f"overnight_basket_{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告: {out}")


if __name__ == "__main__":
    main()
