"""bond_monitor.py — 美债收益率 + TIPS 实际利率 + GLD 联动监控.

**思路**：黄金的直接对手是 **实际利率** (TIPS, DFII10)，不是名义收益率。
- 实际利率 UP → GLD DOWN (历史相关性 -0.7 到 -0.9)
- 20d rolling correlation 反过来（>0）时 = "hedge 关系破裂 · 通胀 regime shift 警报"

数据源（全免费）：
- yfinance: ^TNX (10Y ×10) / ^FVX (5Y ×10) / ^IRX (13W ×100) / ^TYX (30Y ×10)
- FRED: DGS2 (2Y) / DFII10 (10Y TIPS 实际) / T10Y2Y (2s10s spread)
- yfinance: GLD (作为 correlation base)

统一返回结构：
{
  "asof": "2026-08-06T...",
  "yields": {
    "10y":  {"value": 4.25, "chg_1d_bps": +5, "chg_5d_bps": -12, "chg_20d_bps": +18, "z_score_20d": 1.4, "history": [...]},
    "2y":   {...},
    "5y":   {...},
    "30y":  {...},
    "tips_10y": {...}      # 关键
  },
  "spreads": {
    "2s10s":   {"value": 0.45, "regime": "flat" | "normal" | "steep" | "inverted"},
  },
  "gld_correlation": {
    "vs_10y":       -0.62,   # 20d rolling correlation
    "vs_tips_10y":  -0.78,   # 关键：GLD vs TIPS 实际利率
    "regime":       "normal_hedge" | "broken" | "aligned",
    "reason":       "TIPS 实际利率 vs GLD 20d correlation = -0.78, 正常对冲关系"
  },
  "anomalies": [
    {"metric": "10y", "reason": "10Y 单日 +12 bps (2.3σ)", "severity": "high"},
    ...
  ]
}
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


# yfinance 收益率 symbol 需缩放（^TNX 值为 yield ×10）
_YF_YIELDS = {
    "10y":  {"symbol": "^TNX", "scale": 0.1,  "name": "10Y 国债名义"},
    "5y":   {"symbol": "^FVX", "scale": 0.1,  "name": "5Y 国债"},
    "30y":  {"symbol": "^TYX", "scale": 0.1,  "name": "30Y 国债"},
    "3m":   {"symbol": "^IRX", "scale": 1.0,  "name": "3M 短端"},
}


def _fetch_yield_history(symbol: str, period_days: int = 60):
    """从 yfinance 拉某 yield symbol 的历史 close 序列。"""
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period=f"{period_days}d", auto_adjust=False)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def _fetch_fred_series(series_id: str, days: int = 60) -> Optional[list]:
    """FRED 拉某个 series，返 list of (date, value) tuples。"""
    try:
        import urllib.request, json as _json
        from config import FRED_API_KEY
        if not FRED_API_KEY:
            return None
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={FRED_API_KEY}"
               f"&sort_order=desc&limit={days + 5}&file_type=json")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = _json.load(r)
        out = []
        for o in data.get("observations", []):
            v = o.get("value")
            if v and v != ".":
                try:
                    out.append((o["date"], float(v)))
                except ValueError:
                    continue
        return out
    except Exception:
        return None


def _compute_yield_metrics(values: list[float], asof: str = "") -> dict:
    """给 values (最新在 [0])，算今日/5d/20d 变化 (bps) + z-score."""
    if not values or len(values) < 2:
        return {"value": values[0] if values else None, "error": "insufficient_data"}
    v0 = values[0]
    v1 = values[1] if len(values) > 1 else v0
    v5 = values[5] if len(values) > 5 else v0
    v20 = values[20] if len(values) > 20 else v0
    hist_20 = values[:20]
    # 日变化的 z-score
    daily_chgs = [values[i] - values[i+1] for i in range(min(19, len(values)-1))]
    import statistics
    try:
        std = statistics.stdev(daily_chgs) if len(daily_chgs) >= 2 else 0
        today_chg = v0 - v1
        z_score = (today_chg / std) if std > 0 else 0
    except Exception:
        z_score = 0
    return {
        "value":        round(v0, 3),
        "chg_1d_bps":   round((v0 - v1) * 100, 1),
        "chg_5d_bps":   round((v0 - v5) * 100, 1),
        "chg_20d_bps":  round((v0 - v20) * 100, 1),
        "z_score_20d":  round(z_score, 2),
        "history":      [round(v, 3) for v in hist_20],
        "asof":         asof,
    }


def _rolling_corr(a: list[float], b: list[float], window: int = 20) -> Optional[float]:
    """简易 Pearson correlation. a[0] 是最新，b 同."""
    if not a or not b:
        return None
    n = min(len(a), len(b), window)
    if n < 5:
        return None
    ax = a[:n]
    bx = b[:n]
    mean_a = sum(ax) / n
    mean_b = sum(bx) / n
    num = sum((ax[i] - mean_a) * (bx[i] - mean_b) for i in range(n))
    den_a = sum((ax[i] - mean_a) ** 2 for i in range(n)) ** 0.5
    den_b = sum((bx[i] - mean_b) ** 2 for i in range(n)) ** 0.5
    if den_a == 0 or den_b == 0:
        return None
    return round(num / (den_a * den_b), 3)


def _spread_regime(spread: float) -> str:
    """2s10s 利差 → regime label."""
    if spread < -0.20: return "深度倒挂"
    if spread < 0:     return "轻微倒挂"
    if spread < 0.30:  return "曲线平坦"
    if spread < 0.80:  return "正常"
    return                     "陡峭化"


def _correlation_regime(corr: float | None) -> tuple[str, str]:
    """GLD vs TIPS 相关性 → regime + reason."""
    if corr is None:
        return ("unknown", "数据不足无法计算")
    if corr <= -0.5:
        return ("normal_hedge", f"TIPS 实际利率 vs GLD = {corr}，正常对冲关系（黄金按剧本涨跌）")
    if corr <= 0:
        return ("weak_hedge",   f"相关性 {corr}，对冲关系变弱")
    if corr <= 0.3:
        return ("aligned",      f"相关性 {corr}，正相关（可能通胀 regime，两者同向）")
    return ("broken",           f"相关性 {corr}，明显正相关，黄金 hedge 关系破裂 — 警惕 regime shift")


def get_bond_monitor() -> dict:
    """入口：拉所有 yield + GLD 计算 correlation + anomaly."""
    asof = datetime.now().isoformat(timespec="minutes")
    yields_out = {}

    # 1) yfinance yield symbols
    for key, cfg in _YF_YIELDS.items():
        df = _fetch_yield_history(cfg["symbol"], period_days=60)
        if df is None or df.empty:
            continue
        # yfinance 返 index=date, columns=[Open, High, Low, Close, ...]
        # 最新在最后，reverse 让 [0] 是最新
        closes = df["Close"].tolist()[::-1]
        vals = [v * cfg["scale"] for v in closes]
        metrics = _compute_yield_metrics(vals, asof=df.index[-1].strftime("%Y-%m-%d"))
        metrics["name"] = cfg["name"]
        metrics["source"] = f"yfinance {cfg['symbol']}"
        yields_out[key] = metrics

    # 2) FRED: 2Y (yfinance 无) + TIPS 10Y 实际利率
    for key, sid, name in [
        ("2y",       "DGS2",   "2Y 国债"),
        ("tips_10y", "DFII10", "10Y TIPS 实际利率"),
    ]:
        rows = _fetch_fred_series(sid, days=60)
        if not rows:
            continue
        vals = [v for _, v in rows]
        metrics = _compute_yield_metrics(vals, asof=rows[0][0] if rows else "")
        metrics["name"] = name
        metrics["source"] = f"FRED {sid}"
        yields_out[key] = metrics

    # 3) 2s10s spread
    spreads_out = {}
    rows = _fetch_fred_series("T10Y2Y", days=30)
    if rows:
        v0 = rows[0][1]
        v20 = rows[19][1] if len(rows) > 19 else v0
        spreads_out["2s10s"] = {
            "value":        round(v0, 3),
            "chg_20d_bps":  round((v0 - v20) * 100, 1),
            "regime":       _spread_regime(v0),
            "asof":         rows[0][0],
        }

    # 4) GLD correlation
    gld_corr = {}
    try:
        import yfinance as yf
        gld_df = yf.Ticker("GLD").history(period="60d", auto_adjust=False)
        if gld_df is not None and not gld_df.empty:
            gld_closes = gld_df["Close"].tolist()[::-1]  # [0] = 最新
            # 计算 daily returns
            gld_rets = [(gld_closes[i] / gld_closes[i+1] - 1) * 100
                        for i in range(min(len(gld_closes) - 1, 25))]
            # vs 10Y 名义 changes (bps)
            if "10y" in yields_out and yields_out["10y"].get("history"):
                y10_hist = yields_out["10y"]["history"]
                y10_chgs = [(y10_hist[i] - y10_hist[i+1]) * 100
                            for i in range(min(len(y10_hist) - 1, 25))]
                gld_corr["vs_10y"] = _rolling_corr(gld_rets, y10_chgs, window=20)
            # vs TIPS 实际利率 changes (bps) — 关键
            if "tips_10y" in yields_out and yields_out["tips_10y"].get("history"):
                tips_hist = yields_out["tips_10y"]["history"]
                tips_chgs = [(tips_hist[i] - tips_hist[i+1]) * 100
                             for i in range(min(len(tips_hist) - 1, 25))]
                gld_corr["vs_tips_10y"] = _rolling_corr(gld_rets, tips_chgs, window=20)
    except Exception as e:
        gld_corr["error"] = str(e)[:100]

    regime, reason = _correlation_regime(gld_corr.get("vs_tips_10y"))
    gld_corr["regime"] = regime
    gld_corr["reason"] = reason

    # 5) Anomaly detection: |z_score_20d| >= 2 = flag
    anomalies = []
    for key, m in yields_out.items():
        if isinstance(m, dict) and m.get("z_score_20d"):
            z = abs(m["z_score_20d"])
            if z >= 2.0:
                sev = "high" if z >= 3.0 else "medium"
                dir_zh = "上冲" if m.get("chg_1d_bps", 0) > 0 else "下探"
                anomalies.append({
                    "metric":   key,
                    "reason":   f"{m['name']} 单日 {m['chg_1d_bps']:+.1f} bps ({z:.1f}σ · {dir_zh})",
                    "severity": sev,
                })

    return {
        "asof":            asof,
        "yields":          yields_out,
        "spreads":         spreads_out,
        "gld_correlation": gld_corr,
        "anomalies":       anomalies,
    }


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(get_bond_monitor(), ensure_ascii=False, indent=2, default=str))
