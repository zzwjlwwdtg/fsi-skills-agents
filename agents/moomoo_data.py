"""
moomoo_data.py — openD 期权链 + K 线双轨适配层

功能：
  · 期权链：get_option_chain_via_openD(ticker) → 返回 yfinance-format DataFrame
  · 日 K 线：get_kline_via_openD(ticker, n) → 返回 yfinance-format DataFrame
  · 市场报价：get_snapshot_via_openD(ticker) → dict(price, pct_1d, volume ...)

设计原则：
  · 全部封装 try/except，openD 不可用或没订阅 → 返 None，让调用方 fallback yfinance
  · Ticker 转换：yfinance "NVDA" / "6762.T" → openD "US.NVDA" / "JP.6762"
  · 数据格式与 yfinance 输出严格对齐，让 _compute_ticker_options 等无缝双轨
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def to_openD_code(ticker: str) -> Optional[str]:
    """yfinance-style ticker → openD code.
      "NVDA"      → "US.NVDA"
      "6762.T"    → "JP.6762"
      "285A.T"    → "JP.285A"
      "US.NVDA"   → "US.NVDA" (已是 openD 格式)
      "JP.6762"   → "JP.6762"
    """
    if not ticker:
        return None
    tk = ticker.strip().upper()
    if "." in tk and tk.split(".")[0] in ("US", "JP", "HK", "SH", "SZ"):
        return tk
    if tk.endswith(".T"):
        return f"JP.{tk[:-2]}"
    if tk.endswith(".HK"):
        return f"HK.{tk[:-3]}"
    # 默认按 US 处理
    if tk.replace(".", "").isalnum():
        return f"US.{tk}"
    return None


def get_kline_via_openD(ticker: str, days: int = 180) -> Optional["pd.DataFrame"]:
    """从 openD 拉日 K 线，返回与 yfinance history() 相同结构的 DataFrame
    （columns: Open High Low Close Volume, index=Timestamp）。
    """
    code = to_openD_code(ticker)
    if not code:
        return None
    try:
        from moomoo_pool import get_quote_ctx
        from moomoo import RET_OK, KLType, AuType
        import pandas as pd
        ctx = get_quote_ctx()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=int(days * 1.6))).strftime("%Y-%m-%d")  # buffer 假期
        ret, kl, _ = ctx.request_history_kline(
            code, start=start, end=end,
            ktype=KLType.K_DAY, autype=AuType.QFQ,
            max_count=1000,
        )
        if ret != RET_OK or kl is None or kl.empty:
            return None
        # openD 返 columns: code / name / time_key / open / close / high / low / volume ...
        df = kl.rename(columns={
            "open":   "Open",
            "high":   "High",
            "low":    "Low",
            "close":  "Close",
            "volume": "Volume",
        })
        df["time_key"] = pd.to_datetime(df["time_key"])
        df = df.set_index("time_key")[["Open", "High", "Low", "Close", "Volume"]]
        df = df.astype(float).tail(days)
        return df
    except Exception:
        return None


def get_snapshot_via_openD(ticker: str) -> Optional[dict]:
    """当前报价快照（price / prev_close / pct_1d / volume）。"""
    code = to_openD_code(ticker)
    if not code:
        return None
    try:
        from moomoo_pool import get_quote_ctx
        from moomoo import RET_OK
        ctx = get_quote_ctx()
        ret, snap = ctx.get_market_snapshot([code])
        if ret != RET_OK or snap is None or snap.empty:
            return None
        row = snap.iloc[0]
        price = float(row.get("last_price") or row.get("nominal_price") or 0)
        prev  = float(row.get("prev_close_price") or 0)
        return {
            "code":     code,
            "price":    price,
            "prev":     prev,
            "pct_1d":   round((price / prev - 1) * 100, 2) if prev else 0,
            "volume":   int(row.get("volume") or 0),
            "turnover": float(row.get("turnover") or 0),
        }
    except Exception:
        return None


def get_option_chain_via_openD(ticker: str, expiry: str | None = None) -> Optional[dict]:
    """从 openD 拉期权链。返回:
      { "expiry": "YYYY-MM-DD",
        "calls":  DataFrame(strike, volume, openInterest, lastPrice, bid, ask),
        "puts":   DataFrame(...) }
    expiry=None → 用最近的到期日。

    openD 期权链要求订阅对应市场行情（US 免费/JP 付费）。
    """
    code = to_openD_code(ticker)
    if not code:
        return None
    try:
        from moomoo_pool import get_quote_ctx
        from moomoo import RET_OK, OptionCondType
        import pandas as pd
        ctx = get_quote_ctx()

        # 1) 拉全部到期日 → 筛选未来 60 天
        ret_e, exp_df = ctx.get_option_expiration_date(code)
        if ret_e != RET_OK or exp_df is None or exp_df.empty:
            return None
        today = datetime.now().date()
        exp_df = exp_df.copy()
        exp_df["_days"] = exp_df["strike_time"].apply(
            lambda s: (datetime.strptime(s, "%Y-%m-%d").date() - today).days
        )
        exp_df = exp_df[(exp_df["_days"] >= 0) & (exp_df["_days"] <= 60)].sort_values("_days")
        if exp_df.empty:
            return None
        if expiry is None:
            expiry = exp_df["strike_time"].iloc[0]  # 最近

        # 2) 拉这个到期日的完整链
        ret_c, chain = ctx.get_option_chain(
            code=code, start=expiry, end=expiry,
            option_cond_type=OptionCondType.ALL,
        )
        if ret_c != RET_OK or chain is None or chain.empty:
            return None

        # openD 结构: 每行含 code(期权代码)/option_type(CALL/PUT)/strike_price/name...
        # 需要拉每个期权的 snapshot 拿 volume/OI/last/bid/ask
        opt_codes = chain["code"].tolist()
        # 分批拉 snapshot（moomoo 每次最多 400 只）
        snaps = []
        for i in range(0, len(opt_codes), 400):
            ret_s, snap = ctx.get_market_snapshot(opt_codes[i:i+400])
            if ret_s == RET_OK and snap is not None and not snap.empty:
                snaps.append(snap)
        if not snaps:
            return None
        snap_all = pd.concat(snaps, ignore_index=True)
        # openD 期权字段是 option_open_interest / option_implied_volatility 等（前缀 option_）
        keep_cols = [
            "code", "last_price", "bid_price", "ask_price", "volume",
            "option_open_interest", "option_implied_volatility",
            "option_delta", "option_gamma", "option_vega", "option_theta",
        ]
        snap_all = snap_all[[c for c in keep_cols if c in snap_all.columns]].rename(columns={
            "last_price":                "lastPrice",
            "bid_price":                 "bid",
            "ask_price":                 "ask",
            "option_open_interest":      "openInterest",
            "option_implied_volatility": "impliedVolatility",
            "option_delta":              "delta",
            "option_gamma":              "gamma",
            "option_vega":               "vega",
            "option_theta":              "theta",
        })
        merged = chain.merge(snap_all, on="code", how="left")
        merged["strike"] = merged["strike_price"].astype(float)
        merged["volume"] = merged["volume"].fillna(0).astype(int)
        merged["openInterest"] = merged["openInterest"].fillna(0).astype(int)

        base_cols = ["strike", "volume", "openInterest", "lastPrice", "bid", "ask"]
        greek_cols = [c for c in ["impliedVolatility", "delta", "gamma", "vega", "theta"]
                      if c in merged.columns]
        cols = base_cols + greek_cols
        calls = merged[merged["option_type"] == "CALL"][cols].copy()
        puts  = merged[merged["option_type"] == "PUT"][cols].copy()
        return {"expiry": expiry, "calls": calls, "puts": puts,
                "has_greeks": bool(greek_cols)}
    except Exception:
        return None


def health_check() -> dict:
    """快速检查 openD 是否可用 + 支持哪些市场。"""
    try:
        from moomoo_pool import get_quote_ctx
        from moomoo import RET_OK
        ctx = get_quote_ctx()
        ret, state = ctx.get_global_state()
        if ret != RET_OK:
            return {"available": False, "error": "get_global_state failed"}
        # state 是 dict：'market_us' / 'market_hk' / 'market_jp' ...
        return {
            "available": True,
            "market_us": state.get("market_us"),
            "market_jp": state.get("market_jp"),
            "market_hk": state.get("market_hk"),
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:100]}
