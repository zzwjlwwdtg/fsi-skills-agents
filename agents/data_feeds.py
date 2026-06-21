"""
DataFeeds — 公开 API 数据聚合，零 API Key 要求。
数据源: Yahoo Finance (yfinance) + CNN Fear & Greed
"""

import urllib.request
import json
import yfinance as yf

WATCHLIST = {
    "TQQQ":      "3x纳指",
    "SOXL":      "3x半导体",
    "GLD":       "黄金ETF",
    "QQQ":       "纳斯达克100",
    "SPY":       "标普500",
    "^VIX":      "VIX恐慌",
    "^TNX":      "10Y美债",
    "BTC-USD":   "比特币",
    "CL=F":      "WTI原油",
    "DX-Y.NYB":  "美元指数",
}


def fetch_market_data() -> dict:
    """通过 yfinance 获取全部标的最新行情。"""
    result = {}
    for sym, name in WATCHLIST.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if len(hist) < 2:
                raise ValueError("data too short")
            price   = float(hist["Close"].iloc[-1])
            prev    = float(hist["Close"].iloc[-2])
            vol     = float(hist["Volume"].iloc[-1])
            avg_vol = float(hist["Volume"].iloc[-5:-1].mean()) if len(hist) >= 5 else vol
            result[sym] = {
                "name":      name,
                "price":     round(price, 2),
                "pct_chg":   round((price - prev) / prev * 100, 2),
                "vol_ratio": round(vol / avg_vol, 2) if avg_vol > 0 else None,
            }
        except Exception as e:
            result[sym] = {"name": name, "price": None, "pct_chg": None, "error": str(e)}
    return result


def fetch_fear_greed() -> dict:
    """
    CNN Fear & Greed Index (0=极度恐惧, 100=极度贪婪)。
    CNN 用 418 屏蔽 default User-Agent，必须带 Referer/Origin 才放行。
    """
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://www.cnn.com/",
            "Origin":          "https://www.cnn.com",
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = json.load(r)
        fg = raw["fear_and_greed"]
        score = round(float(fg["score"]))
        prev  = round(float(fg.get("previous_close", fg["score"])))
        return {
            "score":      score,
            "rating":     fg["rating"],
            "prev_close": prev,
            "delta":      score - prev,
        }
    except Exception as e:
        return {"score": None, "rating": "N/A", "error": str(e)}


def fetch_vix() -> float | None:
    """只拉VIX最新收盘价，用于15分钟信号周期的宏观快照。"""
    try:
        hist = yf.Ticker("^VIX").history(period="2d")
        return float(hist["Close"].iloc[-1]) if len(hist) >= 1 else None
    except Exception:
        return None


def fetch_dxy(period: str = "10d") -> dict:
    """拉 DXY（美元指数）含近期趋势。黄金宏观分析核心：USD↑ → GLD↓。
    返回 {value, value_5d_ago, pct_chg_5d, pct_chg_20d}。"""
    try:
        hist = yf.Ticker("DX-Y.NYB").history(period=period)
        if len(hist) < 1:
            return {}
        latest = float(hist["Close"].iloc[-1])
        out = {"value": latest}
        if len(hist) >= 5:
            v5 = float(hist["Close"].iloc[-5])
            out["value_5d_ago"] = v5
            out["pct_chg_5d"] = (latest - v5) / v5 * 100
        if len(hist) >= 20:
            v20 = float(hist["Close"].iloc[-20])
            out["pct_chg_20d"] = (latest - v20) / v20 * 100
        return out
    except Exception:
        return {}


def vix_label(v) -> str:
    if v is None: return "N/A"
    if v < 15:   return "极度平静（过度乐观⚠️）"
    if v < 20:   return "平静"
    if v < 25:   return "警戒"
    if v < 30:   return "高度警戒🔶"
    return           "恐慌🔴"


def fg_label(s) -> str:
    if s is None: return "N/A"
    if s < 25:  return "极度恐惧🟢（可能是买入机会）"
    if s < 45:  return "恐惧"
    if s < 55:  return "中性"
    if s < 75:  return "贪婪"
    return          "极度贪婪🔴（警惕回调）"


def yield_label(y) -> str:
    if y is None: return "N/A"
    if y < 3.5:  return "低利率，有利成长股"
    if y < 4.0:  return "中性"
    if y < 4.5:  return "偏高，压制高估值股⚠️"
    return           "高位，显著压制成长股🔴"
