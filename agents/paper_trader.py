"""
本地 Paper Trader — 消费 decision_agent 的输出，通过 OpenD 在 SIMULATE
账户（acc_id 来自 secrets.local.json 的 MOOMOO_ACC_ID）自动下单。挂机模式：由 orchestrator 每个交易窗口
调用 execute()。

7 条核心规则：
  1) 仅 BUY/SELL/WATCH_BUY/REDUCE 触发下单（CAUTION/HOLD 忽略）
  2) confidence >= 6 才下单
  3) 仓位：每笔 = 账户购买力 × POSITION_FRACTION_BASE (1/10)；卫星 z 高时升到 MAX (1/6.7)
  4) 仅 midday + pre-close 实际下单，pre-open 跳过
  5) BUY 成交后挂 stop-loss（若 decision.stop_ref 给了价位）
  6) GLD 纳入交易
  7) 默认 LIVE（在 SIMULATE 账户实际下单）；DRY-run 见环境变量 TRADER_DRY_RUN=1

核心+卫星架构（B 方案）：
  · 3 只核心仓 (TQQQ/SOXL/GLD)：每天都跑
  · 至多 5 只卫星仓：每天 pre-open 由 universe_picker 从 SOX 28 只里选
  · 总持仓上限 8 (3 + 5)；新 picks 进来 → 把不在 picks 里且持仓最久的卫星踢出

CLI:
  python paper_trader.py status   # 看持仓 + state
  python paper_trader.py flatten  # 平掉账户所有 LONG
  python paper_trader.py reset    # 清空 state 文件（不动账户）
  python paper_trader.py picks    # 看今日卫星仓候选池
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from moomoo import (
    OpenSecTradeContext, TrdMarket, SecurityFirm, TrdEnv,
    TrdSide, OrderType, ModifyOrderOp, RET_OK,
)

from config import OPEND_HOST, OPEND_PORT, MOOMOO_ACC_ID
from notifier import logger


ACC_ID  = MOOMOO_ACC_ID
TRD_ENV = TrdEnv.SIMULATE

TRADE_WINDOWS = {"pre-market", "post-open", "midday", "pre-close"}

# 每个窗口的下单参数（成熟系统标准）：盘前严门槛 + 大 buffer + 允许 RTH 外撮合
# pre-market buffer 故意大（2.5%）因为日内 daily K 价和实时价可能有大 gap
# （如 -10% 隔夜跌），太窄 buffer 会让单子挂在书上等不到撮合
WINDOW_CFG = {
    "pre-market": {"conf_min": 7, "buffer": 0.025, "fill_outside_rth": True},
    "post-open":  {"conf_min": 6, "buffer": 0.005, "fill_outside_rth": False},
    "midday":     {"conf_min": 6, "buffer": 0.005, "fill_outside_rth": False},
    "pre-close":  {"conf_min": 6, "buffer": 0.005, "fill_outside_rth": False},
}
# 兼容旧用：默认阈值
CONFIDENCE_THRESHOLD = 6

# ========== 仓位规模引擎 (Vol-Target + DD Floor + VIX Multiplier) ==========
#
# 最终仓位公式（机构 vol-target 标准）:
#   size_pct = (TARGET_PORT_VOL[regime] / asset_vol_annual)
#              × VIX_MULTIPLIER × DD_MULTIPLIER × CONF_MULTIPLIER
#   capped to POSITION_FRACTION_MAX per ticker
#
# 每个 regime 的目标组合年化波动率 (越激进越高)
TARGET_PORT_VOL = {
    "bull_extended":  0.30,
    "bull_pulling":   0.25,
    "bull_trending":  0.22,
    "bull_chop":      0.15,
    "neutral":        0.12,
    "overheated":     0.08,
    "recession_risk": 0.05,
    "crisis":         0.00,
}
POSITION_FRACTION_MAX    = 0.40   # 单笔最高 40% (避免 single trade 爆仓)
ACCOUNT_POWER_FALLBACK   = 1_500_000

# 每个核心 ticker 的年化波动率 (回测算出, 缓存值)
ASSET_VOL_DEFAULTS = {
    "US.TQQQ": 0.60,   # 3x NDX, 高波
    "US.SOXL": 0.80,   # 3x SOX, 更高
    "US.GLD":  0.15,   # 黄金 ETF, 低波
}

# 卫星票动态算 (yfinance 60d), 缓存到避免每次查
_ASSET_VOL_CACHE: dict[str, float] = {}


def _annual_vol(ticker: str) -> float:
    """计算单只标的年化波动率 (yfinance 60 日 daily return std × sqrt(252))。"""
    if ticker in ASSET_VOL_DEFAULTS:
        return ASSET_VOL_DEFAULTS[ticker]
    if ticker in _ASSET_VOL_CACHE:
        return _ASSET_VOL_CACHE[ticker]
    try:
        import yfinance as yf
        import numpy as np
        symbol = ticker.replace("US.", "")
        h = yf.Ticker(symbol).history(period="80d", interval="1d", auto_adjust=True)
        if len(h) < 30:
            return 0.40
        ret = h["Close"].pct_change().dropna()
        v = float(ret.tail(60).std() * np.sqrt(252))
        _ASSET_VOL_CACHE[ticker] = v
        return v
    except Exception:
        return 0.40   # 兜底


# Layer 2 (强化版): VIX-band 仓位倍数 — 低 VIX 加杠杆, 高 VIX 现金
def _vix_multiplier() -> float:
    try:
        from regime_today import get_today_info
        vix = (get_today_info().get("inputs") or {}).get("vix")
        if vix is None: return 1.0
        v = float(vix)
        if v < 13: return 1.8    # 超低波 → 满杠
        if v < 18: return 1.3
        if v < 22: return 0.8
        if v < 28: return 0.4
        if v < 35: return 0.1
        return 0.0               # 极端 panic → 不开新仓
    except Exception:
        return 1.0


# Drawdown Floor: 组合从 NAV peak 跌幅触发降仓 (CPPI 思路)
NAV_PEAK_KEY = "__nav_peak"
def _drawdown_multiplier() -> float:
    state = _state_load()
    meta = state.get(NAV_PEAK_KEY, {})
    peak = meta.get("peak_nav", 0)
    cur  = meta.get("current_nav", 0)
    if not peak or not cur or cur >= peak:
        return 1.0
    dd = (cur - peak) / peak
    if dd > -0.05: return 1.0
    if dd > -0.10: return 0.7
    if dd > -0.15: return 0.4
    if dd > -0.20: return 0.2
    return 0.0


def _update_nav_peak(current_nav: float) -> None:
    state = _state_load()
    meta  = state.get(NAV_PEAK_KEY, {"peak_nav": 0, "current_nav": 0})
    meta["current_nav"] = float(current_nav)
    if current_nav > meta.get("peak_nav", 0):
        meta["peak_nav"] = float(current_nav)
    state[NAV_PEAK_KEY] = meta
    _state_save(state)

CORE_TICKERS = {"US.TQQQ", "US.SOXL", "US.GLD", "US.DRAM", "US.MULL"}

# #4 修复: 总持仓上限放宽 8 → 12 (3 核心 + 9 卫星), 允许 ~150% 总暴露 (用上 margin)
MAX_TOTAL_POSITIONS  = 12
MAX_SATELLITE_POSITIONS = 9

# #3 修复: REDUCE 后 24h 内若价格反弹 +3% → 自动 re-BUY 平回仓位
REBUY_LOOKBACK_HOURS = 24
# REBUY_BOUNCE_PCT 已替换为 _rebuy_bounce_pct(ticker) — 见下方杠杆缩放

# 阶梯止盈 (基础 1x, 实际按 sqrt(leverage) 缩放)
TP_BASE_LEVELS = [
    (0.15, 0.30, "tp15"),   # 1x +15% 卖 30%, SOXL (3x) +26% 卖 30%
    (0.30, 0.30, "tp30"),   # 1x +30% 卖 30%, SOXL +52%
    (0.50, 0.40, "tp50"),   # 1x +50% 卖剩下, SOXL +87%
]

# Trailing Stop: 从入场后最高价跌 N% 全平 (基础 1x = 8%; SOXL ~14%)
TRAILING_STOP_BASE_PCT = 0.08

# REBUY 反弹门槛 (基础 1x = +3%; SOXL ~+5.2%)
REBUY_BOUNCE_BASE_PCT  = 0.03

# Pyramid 加仓: 每层加 50% 原仓, 最多 3 层
PYRAMID_MAX_LAYERS = 3
PYRAMID_ADD_FRAC   = 0.50


def _leverage_sqrt(ticker: str) -> float:
    """返回 sqrt(leverage) 缩放因子。1x → 1.0, 3x → 1.73"""
    import math
    from config import LEVERAGE_FACTORS
    return math.sqrt(LEVERAGE_FACTORS.get(ticker, 1.0))


def _trailing_stop_pct(ticker: str) -> float:
    return TRAILING_STOP_BASE_PCT * _leverage_sqrt(ticker)


def _tp_levels(ticker: str) -> list[tuple[float, float, str]]:
    s = _leverage_sqrt(ticker)
    return [(t * s, frac, label) for t, frac, label in TP_BASE_LEVELS]


def _rebuy_bounce_pct(ticker: str) -> float:
    return REBUY_BOUNCE_BASE_PCT * _leverage_sqrt(ticker)

# 反向 ETF 对照表：BUY 前若已持有"反向对子" → 跳过，避免内部对冲
# 例：已持 TQQQ (3x 多头 QQQ)，再买 SQQQ (3x 空头 QQQ) = 互相对冲，纯亏交易成本
INVERSE_PAIRS = {
    "US.TQQQ": ["US.SQQQ", "US.PSQ", "US.QID"],
    "US.SQQQ": ["US.TQQQ", "US.QLD"],
    "US.QLD":  ["US.SQQQ", "US.PSQ", "US.QID"],
    "US.SOXL": ["US.SOXS"],
    "US.SOXS": ["US.SOXL"],
    "US.SPY":  ["US.SH", "US.SDS", "US.SPXU"],
    "US.SH":   ["US.SPY", "US.SSO", "US.UPRO"],
    "US.SPXU": ["US.SPY", "US.UPRO", "US.SSO"],
    "US.UPRO": ["US.SPY", "US.SPXU", "US.SDS"],
    "US.GLD":  ["US.DGLD", "US.JDST", "US.GLL"],
    "US.NVDA": ["US.NVDD"],
    "US.NVDD": ["US.NVDA", "US.NVDU"],
    "US.NVDU": ["US.NVDD"],
    "US.TSLA": ["US.TSLZ", "US.TSLQ"],
    "US.TSLZ": ["US.TSLA", "US.TSLL"],
    "US.TSLQ": ["US.TSLA", "US.TSLL"],
    "US.TSLL": ["US.TSLZ", "US.TSLQ"],
    "US.AAPL": ["US.AAPD"],
    "US.AAPD": ["US.AAPL", "US.AAPU"],
    "US.AAPU": ["US.AAPD"],
}

# 杠杆/底层标的对照表：BUY 前若已持有"对子另一边" → 跳过，避免叠杠杆
# 例：MULL 是 2x MU，已有 MULL 时不再买 MU（否则相当于 3x MU 暴露）
LEVERAGED_PAIRS = {
    "US.MU":    ["US.MULL"],
    "US.MULL":  ["US.MU"],
    "US.NVDA":  ["US.NVDU", "US.NVDX", "US.NVDD"],
    "US.NVDU":  ["US.NVDA"],
    "US.NVDX":  ["US.NVDA"],
    "US.TSLA":  ["US.TSLL", "US.TSLR", "US.TSLZ", "US.TSLQ"],
    "US.TSLL":  ["US.TSLA"],
    "US.TSLR":  ["US.TSLA"],
    "US.GOOGL": ["US.GGLL"],
    "US.GGLL":  ["US.GOOGL"],
    "US.AMD":   ["US.AMDL", "US.AMDU"],
    "US.AMDL":  ["US.AMD"],
    "US.AAPL":  ["US.AAPU", "US.AAPB"],
    "US.AAPU":  ["US.AAPL"],
    "US.META":  ["US.METU", "US.METD"],
    "US.METU":  ["US.META"],
    "US.MSFT":  ["US.MSFU"],
    "US.AVGO":  ["US.AVGX"],
    "US.AMZN":  ["US.AMZU", "US.AMZD"],
}

BUY_ACTIONS    = {"BUY", "WATCH_BUY"}
SELL_ACTIONS   = {"SELL"}
REDUCE_ACTIONS = {"REDUCE"}

DRY_RUN = os.environ.get("TRADER_DRY_RUN", "0") == "1"

STATE_PATH    = Path(__file__).parent / "trader_state.json"
UNIVERSE_PATH = Path(__file__).parent / "universe_state.json"


# ---------- Trade context (lazy singleton) ----------

_ctx = None

def _ctx_get() -> OpenSecTradeContext:
    global _ctx
    if _ctx is None:
        _ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.US,
            host=OPEND_HOST, port=OPEND_PORT,
            security_firm=SecurityFirm.FUTUSECURITIES,
        )
    return _ctx


def _ctx_close() -> None:
    global _ctx
    if _ctx is not None:
        try: _ctx.close()
        except Exception: pass
        _ctx = None


# ---------- State ----------

def _state_load() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _state_save(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _universe_load() -> dict:
    if not UNIVERSE_PATH.exists():
        return {"date": None, "regime": None, "picks": []}
    try:
        return json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"date": None, "regime": None, "picks": []}


def _universe_save(uni: dict) -> None:
    UNIVERSE_PATH.write_text(
        json.dumps(uni, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _picks_by_ticker(uni: dict) -> dict:
    """{'US.NVDA': {z, size_usd, ...}, ...}"""
    return {p["ticker_full"]: p for p in (uni.get("picks") or [])}


# 账户购买力缓存（5 分钟）
_power_cache: float | None = None
_power_cache_ts: float = 0.0


def _get_account_power() -> float:
    """查 SIMULATE 账户购买力，5 分钟内缓存。OpenD 故障时返回 ACCOUNT_POWER_FALLBACK。"""
    global _power_cache, _power_cache_ts
    now = time.time()
    if _power_cache is not None and now - _power_cache_ts < 300:
        return _power_cache
    try:
        ctx = _ctx_get()
        ret, info = ctx.accinfo_query(trd_env=TRD_ENV, acc_id=ACC_ID, currency="USD")
        if ret == RET_OK and info is not None and not info.empty:
            p = float(info.iloc[0].get("power", 0) or 0)
            if p > 0:
                _power_cache, _power_cache_ts = p, now
                return p
    except Exception:
        pass
    return ACCOUNT_POWER_FALLBACK


def _position_size_usd(ticker: str, conf: int = 6) -> float:
    """
    Vol-Target + DD Floor + VIX Multiplier (机构标准 sizing):

      raw_pct  = TARGET_PORT_VOL[regime] / asset_vol_annual
      final    = raw_pct × vix_mult × dd_mult × conf_mult
      capped at POSITION_FRACTION_MAX = 40%

    例 (bull_extended + VIX 16 + TQQQ vol 60%):
      raw = 0.30 / 0.60 = 0.50 (50%)
      × VIX 1.3 × DD 1.0 × conf 1.0 (conf 6) = 65% → cap 40%
    """
    if ticker not in CORE_TICKERS:
        uni = _universe_load()
        if not _picks_by_ticker(uni).get(ticker):
            return 0.0

    power = _get_account_power()
    # 1) 当前 regime → 目标组合波动率
    try:
        from regime_today import get_today_regime
        regime = get_today_regime()
    except Exception:
        regime = "neutral"
    target_vol = TARGET_PORT_VOL.get(regime, 0.12)
    if target_vol <= 0:
        return 0.0   # crisis / 未知 regime → 不开新仓

    # 2) 单股年化波动
    asset_vol = _annual_vol(ticker)
    raw_pct = target_vol / asset_vol if asset_vol > 0 else 0

    # 3) 乘数
    vix_mult  = _vix_multiplier()
    dd_mult   = _drawdown_multiplier()
    # conf 微调: conf 6 = 1.0, conf 10 = 1.4 (vol-target 已主导,conf 只是微调)
    conf_mult = 1.0 + max(0, conf - 6) * 0.10

    final_pct = raw_pct * vix_mult * dd_mult * conf_mult
    final_pct = min(final_pct, POSITION_FRACTION_MAX)
    return power * final_pct


# ---------- AI target loader (A 方案：Claude 结构化目标覆盖)----------

def _load_ai_target_safe(ticker: str) -> dict | None:
    """从 signals/ai_targets_<date>.json 读取该 ticker 的 Claude 目标。
    失败/不存在返回 None，不影响默认下单流程。"""
    try:
        from ai_prompt import load_ai_target
        return load_ai_target(ticker)
    except Exception:
        return None


# ---------- Position query ----------

def _position_qty(code: str) -> int:
    ctx = _ctx_get()
    ret, pos = ctx.position_list_query(trd_env=TRD_ENV, acc_id=ACC_ID, code=code)
    if ret != RET_OK or pos is None or pos.empty:
        return 0
    row = pos.iloc[0]
    try:
        return int(float(row.get("can_sell_qty", 0)))
    except Exception:
        return 0


# ---------- Order placement ----------

def _get_realtime_price(code: str, fallback: float) -> float:
    """
    pre-market/after-hours 时取真实实时价，避免 daily K 收盘价和实时价有大 gap
    导致限价单挂在书上等不到撮合。fail-safe 回退到 fallback。
    """
    try:
        import yfinance as yf
        symbol = code.replace("US.", "")
        df = yf.Ticker(symbol).history(period="1d", interval="1m", prepost=True)
        if df is not None and not df.empty:
            rt = float(df["Close"].iloc[-1])
            if rt > 0:
                return rt
    except Exception as e:
        logger.warning(f"[trader] realtime price for {code} failed: {e}")
    return fallback


def _place(code: str, side, qty: int, price: float, tag: str = "",
           buffer: float = 0.005, fill_outside_rth: bool = False):
    """
    返回 order_id（实盘）或 'DRY'（dry-run）或 None（失败/跳过）。
    buffer:             限价偏离 ref 的比例 (BUY 出高 / SELL 出低)；窗口决定
    fill_outside_rth:   True 允许盘前盘后撮合（pre-market 用）
                        同时触发: 用 yfinance 拉实时盘前价 替代 daily K 价
    """
    if qty <= 0 or price <= 0:
        logger.warning(f"[trader] SKIP {side} {code} qty={qty} price={price}")
        return None
    side_label = "BUY " if side == TrdSide.BUY else "SELL"
    # pre-market: 用实时价覆盖 daily K 收盘 (避免 gap)
    ref_price = price
    if fill_outside_rth:
        rt = _get_realtime_price(code, price)
        if abs(rt - price) / price > 0.02:  # 2% 以上 gap 才用实时价
            logger.info(f"[trader] {code} 实时 ${rt:.2f} vs daily K ref ${price:.2f} (gap {(rt-price)/price*100:+.1f}%) → 用实时价")
            ref_price = rt
    if side == TrdSide.BUY:
        order_price = round(ref_price * (1 + buffer), 2)
    else:
        order_price = round(ref_price * (1 - buffer), 2)
    rth_label = "+RTHx" if fill_outside_rth else ""
    ref_label = f"ref {ref_price:.2f}" + (f" / daily {price:.2f}" if ref_price != price else "")
    if DRY_RUN:
        logger.info(f"[trader-DRY ] {side_label} {qty:>5} {code:<8} @ {order_price:>8.2f} ({ref_label}) {rth_label} {tag}")
        return "DRY"
    ctx = _ctx_get()
    try:
        ret, info = ctx.place_order(
            price=order_price, qty=float(qty), code=code,
            trd_side=side, order_type=OrderType.NORMAL,
            trd_env=TRD_ENV, acc_id=ACC_ID,
            fill_outside_rth=fill_outside_rth,
        )
    except TypeError:
        # 老版 moomoo SDK 不认识 fill_outside_rth 参数，回退到不传
        ret, info = ctx.place_order(
            price=order_price, qty=float(qty), code=code,
            trd_side=side, order_type=OrderType.NORMAL,
            trd_env=TRD_ENV, acc_id=ACC_ID,
        )
    if ret != RET_OK:
        logger.error(f"[trader] FAIL  {side_label} {qty} {code} @ {order_price:.2f}: {info}")
        return None
    oid = info.iloc[0]["order_id"]
    logger.info(f"[trader-LIVE] {side_label} {qty:>5} {code:<8} @ {order_price:>8.2f} ({ref_label}) {rth_label} order={oid} {tag}")
    return oid


def _place_stop_loss(code: str, qty: int, stop_price: float):
    """BUY 后挂 SELL STOP 保护。失败不影响主流程。"""
    if DRY_RUN:
        logger.info(f"[trader-DRY ] STOP  {qty:>5} {code:<8} trigger={stop_price:.2f}")
        return None
    try:
        ctx = _ctx_get()
        ret, info = ctx.place_order(
            price=round(stop_price * 0.99, 2),   # limit 略低于 trigger，保证能成交
            qty=float(qty), code=code,
            trd_side=TrdSide.SELL,
            order_type=OrderType.STOP,
            trd_env=TRD_ENV, acc_id=ACC_ID,
            aux_price=round(stop_price, 2),
        )
        if ret == RET_OK:
            oid = info.iloc[0]["order_id"]
            logger.info(f"[trader-LIVE] STOP  {qty:>5} {code:<8} trigger={stop_price:.2f}  order={oid}")
            return oid
        logger.warning(f"[trader] STOP FAIL {code} @ {stop_price:.2f}: {info}")
    except Exception as e:
        logger.warning(f"[trader] STOP EXC  {code}: {e}")
    return None


# ---------- Main entry ----------

def execute(ticker: str, decision: dict, mkt: dict, window: str | None,
            _manual: bool = False) -> None:
    """
    orchestrator 在每个 ticker 决策出来后调用。
    window:  pre-open / midday / post-open / pre-close / None
    _manual: True 表示这是手动测试调用（demo/test script），
             window_key 用 "manual:..." 前缀不污染真窗口的防重复机制。
    """
    if window not in TRADE_WINDOWS:
        return

    is_core = ticker in CORE_TICKERS
    action_for_sizing = (decision or {}).get("action")
    conf_for_sizing = (decision or {}).get("confidence") or 6
    size_usd = _position_size_usd(ticker, conf=conf_for_sizing)
    # 卫星票必须在今日 picks 里才允许 BUY；老仓 SELL/REDUCE 仍允许
    if not is_core and size_usd == 0:
        # 未上今日候选池：仅当已有仓位且收到 SELL/REDUCE 时继续；其它跳过
        action_now = (decision or {}).get("action")
        if action_now in BUY_ACTIONS:
            return
        size_usd = 0  # SELL 不需要 size_usd

    action = (decision or {}).get("action")
    conf   = (decision or {}).get("confidence") or 0
    price  = (mkt or {}).get("price")
    if not action or not price:
        return
    win_cfg = WINDOW_CFG.get(window, {})
    conf_min = win_cfg.get("conf_min", CONFIDENCE_THRESHOLD)
    if conf < conf_min:
        return

    state  = _state_load()
    tstate = state.get(ticker, {})

    # ── 纪律性管理（与方向信号解耦, 任一触发立刻 return 不走 normal action）──
    pos_qty_check = _position_qty(ticker)
    cur_price = float(price)
    if pos_qty_check > 0:
        # 更新 entry_high (持仓期间最高)
        entry_price = float(tstate.get("entry_price") or cur_price)
        entry_high  = float(tstate.get("entry_high")  or entry_price)
        if cur_price > entry_high:
            entry_high = cur_price
            tstate["entry_high"] = entry_high

        # #3 Trailing Stop: 从入场后高点跌 ≥ N% (按杠杆缩放) → 全平
        ts_pct = _trailing_stop_pct(ticker)
        if entry_high > 0 and (cur_price - entry_high) / entry_high <= -ts_pct:
            qty = pos_qty_check
            tag = f"[TRAILING-STOP from high ${entry_high:.2f} → ${cur_price:.2f} ({(cur_price-entry_high)/entry_high*100:+.1f}%)]"
            oid = _place(ticker, TrdSide.SELL, qty, cur_price, tag=tag,
                         buffer=win_cfg.get("buffer", 0.005),
                         fill_outside_rth=win_cfg.get("fill_outside_rth", False))
            if oid:
                tstate.update({"last_action":"TRAILING_STOP","last_qty":qty,
                               "last_price":cur_price,
                               "last_time_utc": datetime.now(timezone.utc).isoformat(),
                               "last_window_key": window_key,
                               "last_order_id": None if oid=="DRY" else oid})
                tstate.pop("first_entry_utc", None)
                tstate.pop("entry_price", None)
                tstate.pop("entry_high", None)
                tstate.pop("pyramid_layer", None)
                tstate.pop("tp_levels_hit", None)
                state[ticker] = tstate
                _state_save(state)
                return

        # #2 阶梯止盈: 涨 +15%/+30%/+50% 各卖 30%/30%/40%
        gain = (cur_price - entry_price) / entry_price
        tp_hit = set(tstate.get("tp_levels_hit", []))
        original_qty = int(tstate.get("entry_qty") or pos_qty_check)
        for thresh, sell_frac, label in _tp_levels(ticker):
            if gain >= thresh and label not in tp_hit:
                qty = max(1, int(original_qty * sell_frac))
                qty = min(qty, pos_qty_check)
                if qty <= 0: break
                tag = f"[TAKE-PROFIT {label} (+{gain*100:.1f}% from ${entry_price:.2f})]"
                oid = _place(ticker, TrdSide.SELL, qty, cur_price, tag=tag,
                             buffer=win_cfg.get("buffer", 0.005),
                             fill_outside_rth=win_cfg.get("fill_outside_rth", False))
                if oid:
                    tp_hit.add(label)
                    tstate["tp_levels_hit"] = list(tp_hit)
                    tstate.update({"last_action":f"TP_{label}","last_qty":qty,
                                   "last_price":cur_price,
                                   "last_time_utc": datetime.now(timezone.utc).isoformat(),
                                   "last_window_key": window_key,
                                   "last_order_id": None if oid=="DRY" else oid})
                    state[ticker] = tstate
                    _state_save(state)
                    return
                break

    # 每个 window 每天最多 1 笔（防同一窗口重复触发）
    # _manual=True 时 key 用 "manual:<unix>" 不污染真窗口的去重
    today = datetime.now(timezone.utc).date().isoformat()
    if _manual:
        window_key = f"manual:{int(time.time())}"
    else:
        window_key = f"{today}:{window}"
    if tstate.get("last_window_key") == window_key:
        return

    # #3 修复 (v2): REDUCE 后自动 re-BUY — 回到 vol-target 目标仓位，不只是上次卖量
    if (tstate.get("last_action") == "REDUCE"
            and tstate.get("last_price")):
        try:
            last_time = datetime.fromisoformat(tstate["last_time_utc"])
            hours_since = (datetime.now(timezone.utc) - last_time).total_seconds() / 3600
            last_price = float(tstate["last_price"])
            cur_price = float(price)
            bounce = (cur_price - last_price) / last_price
            if (hours_since < REBUY_LOOKBACK_HOURS
                    and bounce >= _rebuy_bounce_pct(ticker)
                    and not tstate.get("rebuy_done")):
                # v2: 算出 vol-target 应有仓位，与当前差额就是 rebuy 量
                target_size_usd = _position_size_usd(ticker, conf=conf)
                target_qty = int(target_size_usd // cur_price)
                current_qty = _position_qty(ticker)
                rebuy_qty = max(0, target_qty - current_qty)
                if rebuy_qty > 0:
                    rb_oid = _place(
                        ticker, TrdSide.BUY, rebuy_qty, cur_price,
                        tag=f"[REBUY → vol-target. bounce {bounce*100:+.1f}%, 现有 {current_qty}→目标 {target_qty}]",
                        buffer=win_cfg.get("buffer", 0.005),
                        fill_outside_rth=win_cfg.get("fill_outside_rth", False),
                    )
                    if rb_oid:
                        tstate["rebuy_done"] = True
                        tstate["last_action"] = "REBUY"
                        tstate["last_time_utc"] = datetime.now(timezone.utc).isoformat()
                        state[ticker] = tstate
                        _state_save(state)
                        return
        except (ValueError, KeyError):
            pass

    pos_qty = _position_qty(ticker)
    side = qty = None
    stop = None

    if action in BUY_ACTIONS:
        if pos_qty > 0:
            # #1 Pyramid 加仓: 已持仓时若 conf 比入场 conf 高 ≥1 → 加 50% 原仓
            entry_conf = int(tstate.get("entry_conf") or 6)
            layer = int(tstate.get("pyramid_layer") or 1)
            if (conf >= entry_conf + 1
                    and layer < PYRAMID_MAX_LAYERS
                    and size_usd > 0):
                add_qty = int((size_usd * PYRAMID_ADD_FRAC) // price)
                if add_qty > 0:
                    tag = f"[PYRAMID L{layer+1} (conf {entry_conf}→{conf})]"
                    oid = _place(ticker, TrdSide.BUY, add_qty, float(price), tag=tag,
                                 buffer=win_cfg.get("buffer", 0.005),
                                 fill_outside_rth=win_cfg.get("fill_outside_rth", False))
                    if oid:
                        tstate["pyramid_layer"] = layer + 1
                        tstate["entry_conf"]    = conf   # 新 layer 用新 conf
                        tstate.update({"last_action":"PYRAMID","last_qty":add_qty,
                                       "last_price":float(price),
                                       "last_time_utc": datetime.now(timezone.utc).isoformat(),
                                       "last_window_key": window_key,
                                       "last_order_id": None if oid=="DRY" else oid})
                        state[ticker] = tstate
                        _state_save(state)
                    return
            logger.info(f"[trader] {ticker} {action} 但已有 {pos_qty} 仓位 (layer {layer}, conf={entry_conf}), 跳过加仓")
            return
        # 杠杆对子去重：账户里已有"对子的另一只"则跳过，避免叠杠杆
        for paired in LEVERAGED_PAIRS.get(ticker, []):
            paired_qty = _position_qty(paired)
            if paired_qty > 0:
                logger.info(
                    f"[trader] {ticker} BUY 跳过：账户已持有杠杆对 {paired} "
                    f"({paired_qty} 股)，避免叠杠杆"
                )
                return
        # 反向对子去重：账户里已有反向 ETF 则跳过，避免内部对冲
        for inverse in INVERSE_PAIRS.get(ticker, []):
            inv_qty = _position_qty(inverse)
            if inv_qty > 0:
                logger.info(
                    f"[trader] {ticker} BUY 跳过：账户已持反向对 {inverse} "
                    f"({inv_qty} 股)，避免内部对冲"
                )
                return
        if size_usd <= 0:
            return
        # A 方案：Claude AI target 覆盖（entry_ref + stop_ref + use_limit）
        ai_t = _load_ai_target_safe(ticker)
        ai_price = float(price)  # 默认用当前价撮合
        ai_use_limit = False
        ai_stop_override = None
        if ai_t and ai_t.get("action") in ("watch_buy", "buy"):
            ai_entry = ai_t.get("entry_ref")
            if ai_entry and ai_t.get("use_limit") and ai_entry < float(price):
                # 等回踩：用 entry_ref 作为限价（必须低于当前价才合理）
                ai_price = float(ai_entry)
                ai_use_limit = True
                logger.info(f"[trader] {ticker} AI 限价等回踩 ${ai_entry:.2f} (现价 ${price:.2f})")
            ai_stop_override = ai_t.get("stop_ref")
        qty  = int(size_usd // ai_price)
        side = TrdSide.BUY
        # stop_ref 优先级：AI > decision_agent > None
        stop = ai_stop_override or decision.get("stop_ref")
    elif action in SELL_ACTIONS:
        if pos_qty <= 0:
            logger.info(f"[trader] {ticker} {action} 但无持仓，跳过")
            return
        qty  = pos_qty
        side = TrdSide.SELL
    elif action in REDUCE_ACTIONS:
        if pos_qty <= 0:
            logger.info(f"[trader] {ticker} REDUCE 但无持仓，跳过")
            return
        qty  = max(1, pos_qty // 2)
        side = TrdSide.SELL
    else:
        return                                     # HOLD / CAUTION

    # AI 限价模式：用 entry_ref 作为撮合价，buffer 收紧到 0.001（精确挂在 AI 目标价）
    place_price = float(price)
    place_buffer = win_cfg.get("buffer", 0.005)
    place_tag = f"[{action} conf={conf} win={window} {'core' if is_core else 'sat'}]"
    if side == TrdSide.BUY and 'ai_use_limit' in locals() and ai_use_limit:
        place_price = ai_price
        place_buffer = 0.001  # 精确挂在 AI 目标价
        place_tag = f"[{action} conf={conf} win={window} AI-LIMIT@${ai_price:.2f} {'core' if is_core else 'sat'}]"
    oid = _place(
        ticker, side, qty, place_price,
        tag=place_tag,
        buffer=place_buffer,
        fill_outside_rth=win_cfg.get("fill_outside_rth", False),
    )
    if oid is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    tstate.update({
        "is_core":         is_core,
        "last_action":     action,
        "last_side":       "BUY" if side == TrdSide.BUY else "SELL",
        "last_qty":        qty,
        "last_price":      float(price),
        "last_time_utc":   now_iso,
        "last_order_id":   None if oid == "DRY" else oid,
        "last_window_key": window_key,
    })
    if side == TrdSide.BUY and not tstate.get("first_entry_utc"):
        tstate["first_entry_utc"] = now_iso
        # 首次入场: 记 entry 数据供 TP/SL/Pyramid 用
        tstate["entry_price"]    = float(price)
        tstate["entry_high"]     = float(price)
        tstate["entry_qty"]      = qty
        tstate["entry_conf"]     = conf
        tstate["pyramid_layer"]  = 1
        tstate["tp_levels_hit"]  = []
    if side == TrdSide.SELL and pos_qty == qty:
        # 清仓后清掉所有 entry 元数据
        for k in ("first_entry_utc","entry_price","entry_high","entry_qty",
                  "entry_conf","pyramid_layer","tp_levels_hit"):
            tstate.pop(k, None)
    # 每次新动作清掉 rebuy_done 标记 (允许下次 REDUCE 后再 rebuy)
    if action == "REDUCE":
        tstate.pop("rebuy_done", None)
    state[ticker] = tstate
    _state_save(state)

    if side == TrdSide.BUY and stop and stop > 0:
        _place_stop_loss(ticker, qty, float(stop))


# ---------- Universe lifecycle ----------

def _list_satellite_positions() -> list[dict]:
    """返回当前账户的卫星持仓（排除核心仓 + 0 仓位）。"""
    ctx = _ctx_get()
    ret, pos = ctx.position_list_query(trd_env=TRD_ENV, acc_id=ACC_ID)
    if ret != RET_OK or pos is None or pos.empty:
        return []
    out = []
    for _, row in pos.iterrows():
        code = row.get("code")
        qty  = float(row.get("can_sell_qty", 0))
        if qty <= 0 or code in CORE_TICKERS:
            continue
        out.append({"code": code, "qty": qty,
                    "nominal_price": float(row.get("nominal_price", 0))})
    return out


def apply_universe(picks_result: dict) -> dict:
    """
    orchestrator 在 pre-open 算完 picks 后调用。
    步骤：
      1. 持久化今日 picks
      2. 对每个新 pick：若已持仓 → 更新 last_seen_in_picks_utc
      3. 计算踢出：当前卫星持仓 - 今日 picks，按 first_entry_utc 旧→新排序，
         踢到 (卫星持仓 + 待新建) ≤ MAX_SATELLITE_POSITIONS 为止
      4. SELL 全平踢出名单（受 DRY_RUN 控制）
    返回 {"kept": [...], "kicked": [...], "new": [...]}
    """
    picks = picks_result.get("picks") or []
    pick_tickers = {p["ticker_full"] for p in picks}

    today = datetime.now(timezone.utc).date().isoformat()
    _universe_save({
        "date":   today,
        "regime": picks_result.get("regime"),
        "ts":     picks_result.get("ts"),
        "picks":  picks,
    })

    state = _state_load()
    now_iso = datetime.now(timezone.utc).isoformat()
    for tk in pick_tickers:
        ts = state.setdefault(tk, {})
        ts["last_seen_in_picks_utc"] = now_iso
        ts["is_core"] = False
    _state_save(state)

    sat_positions = _list_satellite_positions()
    held = {p["code"]: p for p in sat_positions}
    # 候选踢出 = 已持仓的卫星 - 今日 picks
    kickout_candidates = [code for code in held if code not in pick_tickers]
    # 按 first_entry_utc 排序，最老的优先踢
    kickout_candidates.sort(
        key=lambda c: (state.get(c, {}) or {}).get("first_entry_utc") or ""
    )

    new_picks_to_open = [tk for tk in pick_tickers if tk not in held]
    keep_existing_sat = [tk for tk in held if tk in pick_tickers]
    # 不踢的话最终的卫星持仓数 = 全部现持仓 + 全部新 picks
    # （现持仓里"在 picks"的不变；现持仓里"不在 picks"的依然占位；再加新进入的）
    projected_total = len(held) + len(new_picks_to_open)

    kicked = []
    while projected_total > MAX_SATELLITE_POSITIONS and kickout_candidates:
        victim = kickout_candidates.pop(0)
        kicked.append(victim)
        projected_total -= 1   # 踢一个腾一个位

    # 踢出 = 立即 SELL 全平（不等 SELL 信号触发，因为这是强制周转规则）
    for code in kicked:
        info = held[code]
        qty = int(info["qty"])
        price = info["nominal_price"]
        if qty <= 0 or price <= 0:
            continue
        oid = _place(code, TrdSide.SELL, qty, price,
                     tag=f"[kickout 不在新 picks 内 + 超出 MAX_SATELLITE]")
        if oid:
            ts = state.setdefault(code, {})
            ts.update({
                "last_action":     "KICKOUT",
                "last_side":       "SELL",
                "last_qty":        qty,
                "last_price":      price,
                "last_time_utc":   now_iso,
                "last_order_id":   None if oid == "DRY" else oid,
            })
            ts.pop("first_entry_utc", None)
    _state_save(state)

    # 踢出后真正留下来的卫星持仓 = (现持仓 - 被踢的) + 新开
    survivors = [tk for tk in held if tk not in kicked]
    return {
        "kept":   sorted(keep_existing_sat),
        "kicked": sorted(kicked),
        "new":    sorted(new_picks_to_open),
        "held_after": sorted(set(survivors) | set(new_picks_to_open)),
    }


def get_active_tickers() -> list[str]:
    """orchestrator 用：当前应该跑 cycle 的所有 ticker = 核心 + 今日 picks + 还在持仓的卫星老仓。"""
    uni = _universe_load()
    pick_tickers = [p["ticker_full"] for p in (uni.get("picks") or [])]
    held = {p["code"] for p in _list_satellite_positions()}
    return sorted(set(CORE_TICKERS) | set(pick_tickers) | held)


def refresh_nav_peak() -> None:
    """每个 cycle 调用一次: 查账户总值, 更新 NAV peak (用于 drawdown floor)。"""
    try:
        ctx = _ctx_get()
        ret, info = ctx.accinfo_query(trd_env=TRD_ENV, acc_id=ACC_ID, currency="USD")
        if ret == RET_OK and info is not None and not info.empty:
            total = float(info.iloc[0].get("total_assets") or 0)
            if total > 0:
                _update_nav_peak(total)
    except Exception:
        pass


# ---------- CLI ----------

def _cli_status():
    print(f"DRY_RUN={DRY_RUN}  acc_id={ACC_ID}  env={TRD_ENV}")
    state = _state_load()
    print("\n--- trader_state.json ---")
    print(json.dumps(state, indent=2, ensure_ascii=False) if state else "(空)")

    ctx = _ctx_get()
    print("\n--- 账户 ---")
    ret, info = ctx.accinfo_query(trd_env=TRD_ENV, acc_id=ACC_ID, currency="USD")
    if ret == RET_OK and not info.empty:
        r = info.iloc[0]
        print(f"  total={r.get('total_assets')}  cash={r.get('cash')}  "
              f"market_val={r.get('market_val')}  power={r.get('power')}")
    print("\n--- 持仓 ---")
    ret, pos = ctx.position_list_query(trd_env=TRD_ENV, acc_id=ACC_ID)
    if ret == RET_OK and pos is not None and not pos.empty:
        cols = ["code", "qty", "can_sell_qty", "cost_price", "nominal_price", "market_val", "pl_ratio"]
        keep = [c for c in cols if c in pos.columns]
        print(pos[keep].to_string(index=False))
    else:
        print("(无持仓)")
    print("\n--- 未结订单 ---")
    ret, od = ctx.order_list_query(trd_env=TRD_ENV, acc_id=ACC_ID)
    if ret == RET_OK and od is not None and not od.empty:
        pending = od[od["order_status"].isin(["SUBMITTED", "SUBMITTING", "WAITING_SUBMIT"])]
        if not pending.empty:
            print(pending[["order_id", "code", "trd_side", "qty", "price", "order_status"]].to_string(index=False))
        else:
            print("(无未结)")
    else:
        print("(无)")


def _cli_flatten():
    ctx = _ctx_get()
    ret, od = ctx.order_list_query(trd_env=TRD_ENV, acc_id=ACC_ID)
    if ret == RET_OK and od is not None and not od.empty:
        pending = od[od["order_status"].isin(["SUBMITTED", "SUBMITTING", "WAITING_SUBMIT"])]
        for _, row in pending.iterrows():
            ctx.modify_order(modify_order_op=ModifyOrderOp.CANCEL,
                             order_id=row["order_id"], qty=0, price=0,
                             trd_env=TRD_ENV, acc_id=ACC_ID)
            print(f"  CANCEL {row['code']} order={row['order_id']}")
    time.sleep(1)
    ret, pos = ctx.position_list_query(trd_env=TRD_ENV, acc_id=ACC_ID)
    if ret != RET_OK or pos is None or pos.empty:
        print("(无持仓)"); return
    pos = pos[(pos["qty"] > 0) & (pos["position_side"] == "LONG")]
    for _, row in pos.iterrows():
        code, qty, price = row["code"], float(row["can_sell_qty"]), float(row["nominal_price"])
        r, info = ctx.place_order(price=round(price, 2), qty=qty, code=code,
                                  trd_side=TrdSide.SELL, order_type=OrderType.NORMAL,
                                  trd_env=TRD_ENV, acc_id=ACC_ID)
        oid = info.iloc[0]["order_id"] if r == RET_OK else "FAIL"
        print(f"  SELL {qty:>6.0f} {code:<10} @ {price:>8.2f}  -> {oid}")


def _cli_reset():
    if STATE_PATH.exists():
        STATE_PATH.unlink()
        print(f"已删除 {STATE_PATH}")
    else:
        print("state 不存在，无需清理")


def _cli_picks():
    uni = _universe_load()
    print(f"DRY_RUN={DRY_RUN}  caps: total<={MAX_TOTAL_POSITIONS}  satellite<={MAX_SATELLITE_POSITIONS}")
    print(f"\n--- universe_state.json ---")
    if not uni.get("picks"):
        print(f"(无 picks; date={uni.get('date')} regime={uni.get('regime')})")
        return
    print(f"date={uni['date']}  regime={uni['regime']}  ts={uni.get('ts')}")
    print(f"\n  {'#':<3} {'ticker':<10} {'z(σ)':>7} {'α-t':>6} {'$':>6}  {'主题':<14} 提示")
    for i, p in enumerate(uni["picks"], 1):
        print(f"  {i:<3} {p['ticker_full']:<10} {p.get('z',0):>+6.2f} "
              f"{p.get('alpha_t',0):>+6.2f} ${p.get('size_usd',0):>5.0f}  "
              f"{p.get('theme','?'):<14} {p.get('hint','')}")
    print(f"\n--- 当前活跃 tickers (core + 持仓卫星 + 今日 picks) ---")
    print("  " + ", ".join(get_active_tickers()))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        {
            "status":  _cli_status,
            "flatten": _cli_flatten,
            "reset":   _cli_reset,
            "picks":   _cli_picks,
        }[cmd]()
    except KeyError:
        print(f"用法: python paper_trader.py {{status|flatten|reset|picks}}"); sys.exit(2)
    finally:
        _ctx_close()
