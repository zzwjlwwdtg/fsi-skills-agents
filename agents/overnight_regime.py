"""
Overnight Premium 按市场 regime 拆分 — 是不是熊市才有效, vs SPY/QQQ 大盘对照。

把 25 年拆成 bull / bear:
  · bull: SPY > 200 日 MA
  · bear: SPY < 200 日 MA

策略:
  · 动态 top 5 隔夜
  · 固定 5 (AAPL/MSFT/NVDA/AMZN/GOOGL) 隔夜
  · SPY 隔夜 / QQQ 隔夜 (大盘隔夜对照)
  · SPY BH / QQQ BH (大盘买持对照)

输出: 按 regime 分别看年化收益 / Sharpe / 最大回撤。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path

from config import SIGNALS_DIR


US_UNIVERSE = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "NVDA",
    "INTC", "CSCO", "ORCL", "ADBE", "QCOM",
    "TXN", "AMD", "MU", "IBM",
    "JPM", "BAC", "C", "WFC", "GS",
    "WMT", "JNJ", "PG", "KO", "PEP", "MCD",
    "DIS", "HD", "NKE", "COST",
    "XOM", "CVX", "BA", "GE", "T", "VZ",
]
FIXED5 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
BENCH = ["SPY", "QQQ"]
LOOKBACK_YEARS = 25
TOP_N = 5


def fetch(ticker: str, years: int) -> pd.DataFrame | None:
    import yfinance as yf
    h = yf.Ticker(ticker).history(period=f"{years*365}d", interval="1d", auto_adjust=True)
    if h.empty:
        return None
    h.index = h.index.tz_localize(None) if h.index.tz else h.index
    return h[["Open", "Close", "Volume"]]


def fetch_panel(tickers: list[str], years: int) -> dict[str, pd.DataFrame]:
    out = {}
    for tk in tickers:
        df = fetch(tk, years)
        if df is not None:
            out[tk] = df
    return out


def dynamic_top5_overnight(opens, closes, volumes, n=5):
    dollar_vol = closes * volumes
    valid = dollar_vol.notna() & opens.shift(-1).notna() & closes.notna()
    dollar_vol = dollar_vol.where(valid)
    ranks = dollar_vol.rank(axis=1, ascending=False, method="first")
    top_mask = (ranks <= n).astype(float)
    overnight_per = (opens.shift(-1) / closes - 1)
    n_act = top_mask.sum(axis=1).replace(0, np.nan)
    ret = (overnight_per * top_mask).sum(axis=1) / n_act
    return ret.dropna()


def basket_overnight(opens, closes, tickers):
    avail = [t for t in tickers if t in opens.columns]
    closes_prev = closes[avail].shift(1)
    return (opens[avail] / closes_prev - 1).mean(axis=1).dropna()


def single_overnight(df):
    return (df["Open"] / df["Close"].shift(1) - 1).dropna()


def single_bh(df):
    return (df["Close"] / df["Close"].shift(1) - 1).dropna()


def regime_split(spy_close: pd.Series, ma_days: int = 200) -> pd.Series:
    """SPY 收盘价 > 200d MA → bull(1), 否则 bear(0)。"""
    ma = spy_close.rolling(ma_days).mean()
    return (spy_close > ma).astype(int).dropna()


def stats_split(returns: pd.Series, regime: pd.Series) -> dict:
    """整段 + bull / bear 子区间的统计。"""
    r = returns.reindex(regime.index).dropna()
    reg = regime.reindex(r.index)
    bull = r[reg == 1]
    bear = r[reg == 0]

    def block(x):
        if len(x) == 0:
            return {"days": 0, "ann": 0, "sharpe": 0, "vol": 0, "dd": 0}
        mean = x.mean() * 252
        std = x.std() * np.sqrt(252)
        cum = (1 + x).cumprod()
        peak = cum.expanding().max()
        dd = ((cum - peak) / peak).min()
        return {
            "days": len(x), "ann": mean, "sharpe": mean / std if std > 0 else 0,
            "vol": std, "dd": dd,
            "cum_end": cum.iloc[-1] if len(cum) else 1,
        }

    cum_full = (1 + r).cumprod()
    years = len(r) / 252
    cagr = cum_full.iloc[-1] ** (1/years) - 1 if years > 0 else 0
    peak = cum_full.expanding().max()
    full_dd = ((cum_full - peak) / peak).min()
    return {
        "full": {
            "days": len(r), "years": years, "cagr": cagr,
            "sharpe": (r.mean()*252) / (r.std()*np.sqrt(252)) if r.std() > 0 else 0,
            "vol": r.std() * np.sqrt(252),
            "dd": full_dd,
            "cum_end": cum_full.iloc[-1],
        },
        "bull": block(bull),
        "bear": block(bear),
    }


def main():
    print(f"拉数据 — {len(US_UNIVERSE)} 池子 + {BENCH}", flush=True)
    panel = fetch_panel(US_UNIVERSE, LOOKBACK_YEARS)
    bench = fetch_panel(BENCH, LOOKBACK_YEARS)
    spy = bench.get("SPY")
    qqq = bench.get("QQQ")
    if spy is None:
        print("SPY 缺失")
        return

    # regime 用 SPY 200d MA
    regime = regime_split(spy["Close"], ma_days=200)
    bull_pct = (regime == 1).sum() / len(regime) * 100
    print(f"\nregime: SPY 在 200MA 上方 {bull_pct:.1f}% 天数")

    # 面板
    idx = sorted(set().union(*[df.index for df in panel.values()]))
    opens   = pd.DataFrame({tk: df["Open"]   for tk, df in panel.items()}).reindex(idx)
    closes  = pd.DataFrame({tk: df["Close"]  for tk, df in panel.items()}).reindex(idx)
    volumes = pd.DataFrame({tk: df["Volume"] for tk, df in panel.items()}).reindex(idx)

    # 策略
    strategies = {
        "动态 top 5 隔夜":     dynamic_top5_overnight(opens, closes, volumes, n=TOP_N),
        "固定 5 大 隔夜":       basket_overnight(opens, closes, FIXED5),
        "SPY 隔夜":             single_overnight(spy),
        "QQQ 隔夜":             single_overnight(qqq) if qqq is not None else None,
        "SPY Buy&Hold":         single_bh(spy),
        "QQQ Buy&Hold":         single_bh(qqq) if qqq is not None else None,
    }

    results = {name: stats_split(s, regime) for name, s in strategies.items() if s is not None}

    # 报告
    W = 100
    lines = [
        "+" + "=" * (W-2) + "+",
        "|  Overnight Premium 按 regime 拆: bull (SPY>200MA) vs bear (SPY<200MA)".ljust(W-1) + "|",
        f"|  数据: {LOOKBACK_YEARS} 年, regime 中 bull 占 {bull_pct:.1f}%".ljust(W-1) + "|",
        "+" + "=" * (W-2) + "+",
        "",
        "  === 整段 (25 年全程) ===",
        f"  {'策略':<22} {'累计倍数':>11} {'CAGR':>8} {'Sharpe':>7} {'年化σ':>7} {'最大回撤':>10}",
        f"  {'-'*22} {'-'*11} {'-'*8} {'-'*7} {'-'*7} {'-'*10}",
    ]
    for name, res in results.items():
        f = res["full"]
        mult = f["cum_end"]
        mstr = f"{mult:>10.2f}x" if mult < 1000 else f"{mult:>10.2e}"
        lines.append(
            f"  {name:<22} {mstr:>11} "
            f"{f['cagr']*100:>+7.1f}% {f['sharpe']:>+7.2f} "
            f"{f['vol']*100:>6.1f}% {f['dd']*100:>+9.1f}%"
        )

    lines.append("")
    lines.append(f"  === BULL 子区间 (SPY > 200MA, {bull_pct:.0f}% 的日子) ===")
    lines.append(f"  {'策略':<22} {'年化收益':>10} {'Sharpe':>7} {'年化σ':>7} {'回撤':>9}")
    lines.append(f"  {'-'*22} {'-'*10} {'-'*7} {'-'*7} {'-'*9}")
    for name, res in results.items():
        b = res["bull"]
        lines.append(
            f"  {name:<22} {b['ann']*100:>+9.1f}% {b['sharpe']:>+7.2f} "
            f"{b['vol']*100:>6.1f}% {b['dd']*100:>+8.1f}%"
        )

    lines.append("")
    lines.append(f"  === BEAR 子区间 (SPY < 200MA, {100-bull_pct:.0f}% 的日子) ===")
    lines.append(f"  {'策略':<22} {'年化收益':>10} {'Sharpe':>7} {'年化σ':>7} {'回撤':>9}")
    lines.append(f"  {'-'*22} {'-'*10} {'-'*7} {'-'*7} {'-'*9}")
    for name, res in results.items():
        b = res["bear"]
        lines.append(
            f"  {name:<22} {b['ann']*100:>+9.1f}% {b['sharpe']:>+7.2f} "
            f"{b['vol']*100:>6.1f}% {b['dd']*100:>+8.1f}%"
        )

    lines.append("")
    lines.append("=" * W)
    lines.append("关键解读:")
    lines.append("  · 看'动态 top 5 隔夜' bull / bear 年化各自多少 → 是不是只熊市好")
    lines.append("  · 看 vs SPY/QQQ BH bull 收益 → 牛市能不能跑赢大盘")
    lines.append("  · 看 vs SPY/QQQ BH bear 表现 → 熊市是不是真的护城河")
    lines.append("=" * W)

    for line in lines:
        print(line)
    out = Path(SIGNALS_DIR) / f"overnight_regime_{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告: {out}")


if __name__ == "__main__":
    main()
