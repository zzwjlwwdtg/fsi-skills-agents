"""
Overnight Premium 动态版 — 每日按"当日 dollar volume"取 top 5。

vs overnight_basket.py 的区别:
  · basket: 25 年前定 5 只 → 测 5 只大盘股的隔夜溢价
  · dynamic: 每天从池子里挑当日 dollar_vol top 5 → 测"市场关注度最高的那 5 只"

预期:
  · CAGR 可能比固定篮子高 (attention 偏差)
  · 但混进 "昨日暴涨股次日开盘跳空" 等其他 alpha 源
  · 实操难度: 池子要无 survivorship bias (本脚本只用当前存活股, 仍有 bias)

数据: yfinance daily OHLCV. 25 年.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from config import SIGNALS_DIR


# 25 年都存在 (或接近) 的美股大盘股 -- 减轻 survivorship bias
# 注意: 仍有偏差 (倒闭的雷曼/Enron 不在内)
US_UNIVERSE = [
    # 科技
    "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA",
    "INTC", "CSCO", "ORCL", "ADBE", "QCOM",
    "TXN", "AMD", "MU", "IBM",
    # 金融
    "JPM", "BAC", "C", "WFC", "GS",
    # 消费
    "WMT", "JNJ", "PG", "KO", "PEP", "MCD",
    "DIS", "HD", "NKE", "COST",
    # 能源/工业
    "XOM", "CVX", "BA", "GE", "T", "VZ",
]
# 注: GOOGL 2004 上市, 之前数据缺失 — yfinance 会自动 NaN 处理

LOOKBACK_YEARS = 25
TOP_N = 5


def fetch_universe(tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    out = {}
    for tk in tickers:
        h = yf.Ticker(tk).history(period=f"{years*365}d", interval="1d", auto_adjust=True)
        if h.empty:
            continue
        h.index = h.index.tz_localize(None) if h.index.tz else h.index
        out[tk] = h[["Open", "Close", "Volume"]]
        print(f"  [{tk}] {len(h)} 行", flush=True)
    return out


def build_panels(panel: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """对齐到一个所有股票的索引并集; 缺失日 = NaN (个股那天不参与排名)。"""
    opens   = pd.DataFrame({tk: df["Open"]   for tk, df in panel.items()})
    closes  = pd.DataFrame({tk: df["Close"]  for tk, df in panel.items()})
    volumes = pd.DataFrame({tk: df["Volume"] for tk, df in panel.items()})
    # 取并集
    idx = opens.index.union(closes.index).union(volumes.index).sort_values()
    opens   = opens.reindex(idx)
    closes  = closes.reindex(idx)
    volumes = volumes.reindex(idx)
    return opens, closes, volumes


def dynamic_top5_overnight(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    n: int = 5,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    每天 t 收盘时排名 dollar_vol = close[t] * volume[t], 取 top N。
    买入 close[t], 卖出 open[t+1]; 等权。

    返回:
      · 日收益序列 (实现在 t+1 早上)
      · top_n_history (每天选了哪几只)
    """
    dollar_vol = (closes * volumes)
    # 只在两者都有数据的位置参与排名
    valid = dollar_vol.notna() & opens.shift(-1).notna() & closes.notna()
    dollar_vol = dollar_vol.where(valid)
    # 每天对横截面排名, 取 top N
    ranks = dollar_vol.rank(axis=1, ascending=False, method="first")
    top_mask = (ranks <= n).astype(float)
    # 隔夜收益: close[t] → open[t+1]
    overnight_per_stock = (opens.shift(-1) / closes - 1)
    # 等权组合: top N 各 1/N
    n_actual = top_mask.sum(axis=1).replace(0, np.nan)  # 实际入选数 (一般 = N)
    weighted = (overnight_per_stock * top_mask).sum(axis=1) / n_actual
    return weighted.dropna(), top_mask


def top5_diagnostics(top_mask: pd.DataFrame) -> dict:
    """分析 top 5 的稳定性。"""
    counts = top_mask.sum(axis=0).sort_values(ascending=False)  # 每只股入选总天数
    total_days = (top_mask.sum(axis=1) > 0).sum()
    daily_changes = (top_mask.diff().abs().sum(axis=1) / 2).dropna()
    avg_churn = daily_changes.mean()
    return {
        "total_days": int(total_days),
        "avg_churn_per_day": float(avg_churn),
        "top10_tickers": counts.head(10).to_dict(),
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
        "cum_end": cum.iloc[-1],
    }


def main():
    print(f"拉 {len(US_UNIVERSE)} 只股票, {LOOKBACK_YEARS} 年...", flush=True)
    panel = fetch_universe(US_UNIVERSE, LOOKBACK_YEARS)
    if len(panel) < 10:
        print(f"数据不足: 只拿到 {len(panel)} 只")
        return
    opens, closes, volumes = build_panels(panel)
    print(f"\n面板: {opens.shape} (天 × 股)")

    # 策略 1: 动态 top 5 隔夜
    ret_dyn, top_mask = dynamic_top5_overnight(opens, closes, volumes, n=TOP_N)
    s_dyn = stats(ret_dyn, "动态 top 5 隔夜 (每日按 dollar_vol 选)")

    # 对照 1: 固定 5 只(前 5 大盘) 隔夜
    fixed5 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
    fixed5_avail = [t for t in fixed5 if t in opens.columns]
    closes_prev = closes[fixed5_avail].shift(1)
    overnight_fixed = (opens[fixed5_avail] / closes_prev - 1).dropna()
    ret_fixed = overnight_fixed.mean(axis=1)
    s_fixed = stats(ret_fixed, "固定 5 只 (AAPL/MSFT/NVDA/AMZN/GOOGL) 隔夜")

    # 对照 2: 全宇宙等权 BH (基线)
    all_bh = (closes / closes.shift(1) - 1).mean(axis=1).dropna()
    s_bh = stats(all_bh, "全 35 只 等权 BH (基线)")

    # 诊断
    diag = top5_diagnostics(top_mask)

    # 报告
    W = 90
    lines = [
        "+" + "=" * (W-2) + "+",
        "|  Overnight Premium 动态版: 每日按 dollar_vol 选 top 5".ljust(W-1) + "|",
        f"|  池子: 35 只美股大盘, yfinance {LOOKBACK_YEARS} 年".ljust(W-1) + "|",
        "+" + "=" * (W-2) + "+",
        "",
        f"  共同交易日: {s_dyn['n']} ({s_dyn['years']} 年)",
        f"  Top 5 平均日换手: {diag['avg_churn_per_day']:.2f} 只/天 (5 进 5 出 max=5)",
        "",
        f"  {'策略':<46} {'累计倍数':>11} {'CAGR':>8} {'Sharpe':>7} {'年化σ':>7} {'最大回撤':>10}",
        f"  {'-'*46} {'-'*11} {'-'*8} {'-'*7} {'-'*7} {'-'*10}",
    ]
    for s in [s_dyn, s_fixed, s_bh]:
        mult = s.get("cum_end", 1)
        mstr = f"{mult:>10.2f}x" if mult < 1000 else f"{mult:>10.2e}"
        lines.append(
            f"  {s['name']:<46} {mstr:>11} "
            f"{s.get('cagr',0)*100:>+7.1f}% {s.get('sharpe',0):>+7.2f} "
            f"{s.get('vol',0)*100:>6.1f}% {s.get('max_dd',0)*100:>+9.1f}%"
        )
    lines.append("")
    lines.append("  Top 5 入选最多的 10 只 (累计入选天数):")
    for tk, days in diag["top10_tickers"].items():
        pct = days / s_dyn['n'] * 100 if s_dyn['n'] > 0 else 0
        lines.append(f"    {tk:<8} {int(days):>6} 天  ({pct:>5.1f}% 的交易日)")
    lines.append("")
    lines.append("=" * W)
    lines.append("解读:")
    lines.append("  · 动态 top 5 > 固定 5 只 → attention bias 真的能加成")
    lines.append("  · 动态 top 5 ≈ 固定 5 只 → 隔夜溢价主要来自'大盘股'本身, 不是流动性")
    lines.append("  · 动态 top 5 << 固定 5 只 → 高流动性股反而隔夜溢价低 (反直觉)")
    lines.append("")
    lines.append("⚠ 偏差提示:")
    lines.append("  · 池子用'当前活着的 35 只' → 仍有 survivorship bias")
    lines.append("  · 真要做需用 Russell 1000 全成分历史名单 + 退市股 (CRSP 数据库)")
    lines.append("=" * W)

    for line in lines:
        print(line)
    out = Path(SIGNALS_DIR) / f"overnight_dynamic_{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告: {out}")


if __name__ == "__main__":
    main()
