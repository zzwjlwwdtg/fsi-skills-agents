"""
FREDFeeds — 美联储经济数据 (FRED) 宏观指标。
免费API Key申请: https://fred.stlouisfed.org/docs/api/api_key.html
无Key时静默跳过，不影响其他模块。
"""

import urllib.request
import json
from config import FRED_API_KEY

_BASE = "https://api.stlouisfed.org/fred/series/observations"

_SERIES = {
    "T10Y2Y":   "10Y-2Y国债利差",
    "T10YIE":   "10Y盈亏平衡通胀率",
    "FEDFUNDS": "联邦基金利率",
    # 黄金宏观驱动（2026-06-15 加）
    "DGS10":    "10Y 国债名义利率",
    "DFII10":   "10Y TIPS 实际利率（黄金核心驱动）",
    "WALCL":    "Fed 资产负债表规模 (M)",
    "DCOILWTICO": "WTI 原油（通胀代理）",
}


def fetch_fred() -> dict:
    """拉取FRED关键宏观指标。无API Key或网络失败时返回空dict。
    黄金相关 series 拉 30 天历史用于算趋势（rising/falling/flat）。"""
    if not FRED_API_KEY:
        return {}
    result = {}
    # 黄金宏观 series 需要历史用于趋势计算
    gold_series = {"DGS10", "DFII10", "WALCL", "DCOILWTICO"}
    for sid, name in _SERIES.items():
        limit = 30 if sid in gold_series else 3
        try:
            url = (f"{_BASE}?series_id={sid}&api_key={FRED_API_KEY}"
                   f"&sort_order=desc&limit={limit}&file_type=json")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            vals = [float(o["value"]) for o in data["observations"] if o["value"] != "."]
            entry = {"name": name, "value": vals[0] if vals else None}
            if sid in gold_series and len(vals) >= 5:
                # 简单趋势：最新 vs 5 天前
                entry["value_5d_ago"] = vals[4] if len(vals) > 4 else None
                entry["value_20d_ago"] = vals[19] if len(vals) > 19 else None
                entry["history"] = vals[:20]  # 最近 20 个观察
            result[sid] = entry
        except Exception as e:
            result[sid] = {"name": name, "value": None, "error": str(e)}
    return result


def yield_curve_label(v) -> str:
    if v is None:  return "N/A"
    if v < -0.5:   return "深度倒挂 (历史衰退信号)"
    if v < 0:      return "轻微倒挂 (警惕)"
    if v < 0.5:    return "趋于平坦"
    return                "正常"


def inflation_exp_label(v) -> str:
    if v is None:  return "N/A"
    if v > 3.0:    return "通胀预期偏高"
    if v > 2.5:    return "通胀预期警戒"
    if v > 2.0:    return "通胀预期中性"
    return                "通胀预期温和"
