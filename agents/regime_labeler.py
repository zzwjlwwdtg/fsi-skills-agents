"""
RegimeLabeler — 给历史每一天打 regime bucket 标签。

3 个粗 bucket（简化版，evolver 分桶训练用）:
  bull   : 强趋势上行 + 低波动 (SPY > MA50 + 5%, 或 VIX < 18 + 上升)
  bear   : 防御 / 高波动 / 下跌 (VIX > 25, 或 SPY 跌 5%+, 或趋势下行)
  neutral: 其他 (chop, 转折期, 不确定)

为什么 3 桶不是 5：训练样本量。500 天历史里 crisis 可能只有 20 天 →
evolver 跑不出统计显著规则。3 桶让每桶至少 100+ 天，可学。

调用:
  label_history(spy_df, vix_df) → pd.Series 每天的 bucket 字符串
  label_today() → (bucket, source)  实时推断
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _fetch_spy_vix_history(days: int = 800) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period=f"{days}d", interval="1d", auto_adjust=True)
        vix = yf.Ticker("^VIX").history(period=f"{days}d", interval="1d")
        if spy.empty or vix.empty:
            return (None, None)
        for d in (spy, vix):
            d.index = d.index.tz_localize(None) if d.index.tz else d.index
        return (spy, vix)
    except Exception:
        return (None, None)


def _bucket_for_day(spy_close: float, spy_ma50: float, spy_pct_1d: float,
                    vix: float) -> str:
    """单天的 regime bucket 判定。"""
    if np.isnan(spy_close) or np.isnan(spy_ma50) or np.isnan(vix):
        return "neutral"
    extension = (spy_close - spy_ma50) / spy_ma50 * 100
    # bear: 高 VIX 或单日暴跌或显著低于 MA50
    if vix > 25 or spy_pct_1d <= -3 or extension < -5:
        return "bear"
    # bull: 高于 MA50 + 低 VIX 或强趋势
    if (extension > 5 and vix < 22) or (extension > 0 and vix < 16):
        return "bull"
    # 其他都是 chop / 不确定
    return "neutral"


def label_history(spy: pd.DataFrame, vix: pd.DataFrame) -> pd.Series:
    """给 SPY 历史每一天打 bucket 标签，返回 Series<bucket>。"""
    # 对齐日期
    common = spy.index.intersection(vix.index)
    spy_aligned = spy.loc[common]
    vix_aligned = vix.loc[common]

    spy_close = spy_aligned["Close"]
    spy_ma50  = spy_close.rolling(50).mean()
    spy_pct   = spy_close.pct_change() * 100
    vix_close = vix_aligned["Close"]

    buckets = []
    for d in common:
        b = _bucket_for_day(
            float(spy_close.loc[d]),
            float(spy_ma50.loc[d]) if not pd.isna(spy_ma50.loc[d]) else float("nan"),
            float(spy_pct.loc[d]) if not pd.isna(spy_pct.loc[d]) else 0,
            float(vix_close.loc[d]),
        )
        buckets.append(b)
    return pd.Series(buckets, index=common, name="regime_bucket")


def label_today() -> str:
    """返回今天的 regime bucket (bull/neutral/bear)。"""
    try:
        from regime_today import get_today_regime
        r = get_today_regime()
        if r in ("bull_extended", "bull_pulling", "bull_trending", "bull_chop"):
            return "bull"
        if r in ("overheated", "recession_risk", "crisis"):
            return "bear"
        return "neutral"
    except Exception:
        return "neutral"


def summary_distribution(buckets: pd.Series) -> dict:
    counts = buckets.value_counts()
    return {b: int(counts.get(b, 0)) for b in ("bull", "neutral", "bear")}


if __name__ == "__main__":
    spy, vix = _fetch_spy_vix_history(800)
    if spy is None:
        print("数据拉取失败")
    else:
        labels = label_history(spy, vix)
        print(f"历史 {len(labels)} 天分桶:")
        print(summary_distribution(labels))
        print(f"\n今日: {label_today()}")
