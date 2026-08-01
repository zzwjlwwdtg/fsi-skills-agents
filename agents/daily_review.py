"""
DailyReview — 每日复盘 + 滚动胜率更新 + 综合策略建议。
参考 trump-code/learning_engine.py 架构:
  ① 加载昨日信号历史
  ② 检验超过持仓期的信号（用yfinance取价）
  ③ 统计每类规则的滚动胜率（最近30笔）
  ④ 结合回测历史 → 生成综合策略建议

调用入口:
  generate_review_report()  → 复盘报告字符串
  append_signal(...)        → 每次emit时追加信号（由notifier调用）
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

import yfinance as yf

from config import SIGNALS_DIR
from i18n import t
from atomic_io import atomic_write_json
from trading_contracts import (
    BEARISH_SIGNAL_ACTIONS,
    BULLISH_SIGNAL_ACTIONS,
    BUY_ACTIONS,
    REDUCE_ACTIONS,
    SELL_ACTIONS,
)

_HISTORY_PATH  = Path(SIGNALS_DIR) / "signal_history.json"
_BACKTEST_DIR  = Path(SIGNALS_DIR)

# 每个动作的默认持仓天数（日历日）
_HOLD_DAYS = {action: 5 for action in BULLISH_SIGNAL_ACTIONS}
_HOLD_DAYS.update({action: 3 for action in BEARISH_SIGNAL_ACTIONS})
_EXECUTING_BEARISH_ACTIONS = SELL_ACTIONS | REDUCE_ACTIONS

# trump-code 学习参数
_ROLLING_WINDOW = 30
_PROMOTE_RATE   = 0.62
_DEMOTE_RATE    = 0.40
_WEIGHT_UP      = 1.15
_WEIGHT_DOWN    = 0.80

# moomoo ticker → yfinance ticker
_YF_MAP = {
    "US.TQQQ": "TQQQ",
    "US.SOXL": "SOXL",
    "US.GLD":  "GLD",
}


# ── 信号历史 IO ───────────────────────────────────────────────────────────────

def _load_history() -> list:
    if _HISTORY_PATH.exists():
        try:
            return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_history(history: list) -> None:
    atomic_write_json(_HISTORY_PATH, history)


def append_signal(ticker: str, action: str, price: float,
                  confidence: int, reason: str, indicators: dict) -> None:
    """每次 emit 时追加信号（由 notifier 调用），跳过 HOLD。"""
    if action == "HOLD":
        return
    history = _load_history()
    history.append({
        "ticker":      ticker,
        "ts":          datetime.now().isoformat(),
        "action":      action,
        "entry_price": round(price, 2),
        "confidence":  confidence,
        "reason":      reason,
        "hold_days":   _HOLD_DAYS.get(action, 3),
        "indicators":  {k: v for k, v in indicators.items()
                        if k in ("rsi_14", "vol_ratio", "trend", "ma_stack", "is_new_52w_high")},
        "reviewed":    False,
        "exit_price":  None,
        "actual_ret":  None,
        "correct":     None,
    })
    # 只保留最近 500 条
    if len(history) > 500:
        history = history[-500:]
    _save_history(history)


# ── 价格拉取 ─────────────────────────────────────────────────────────────────

def _get_current_price(ticker: str) -> float | None:
    yf_sym = _YF_MAP.get(ticker)
    if not yf_sym:
        return None
    try:
        hist = yf.Ticker(yf_sym).history(period="2d")
        return float(hist["Close"].iloc[-1]) if len(hist) >= 1 else None
    except Exception:
        return None


# ── 核心复盘逻辑 ─────────────────────────────────────────────────────────────

def review_pending_signals() -> tuple[int, int]:
    """
    遍历所有未复盘信号，超过持仓期的打上结果。
    返回 (reviewed_count, total_pending)。
    """
    history = _load_history()
    today   = date.today()
    reviewed = 0

    for entry in history:
        if entry.get("reviewed"):
            continue
        signal_date = datetime.fromisoformat(entry["ts"]).date()
        if (today - signal_date).days < entry["hold_days"]:
            continue  # 还没到期

        price = _get_current_price(entry["ticker"])
        if price is None:
            continue

        ret = (price - entry["entry_price"]) / entry["entry_price"] * 100
        is_bull = entry["action"] in BULLISH_SIGNAL_ACTIONS
        entry.update({
            "exit_price": round(price, 2),
            "actual_ret": round(ret, 2),
            "correct":    (ret > 0) if is_bull else (ret < 0),
            "reviewed":   True,
            "review_date": today.isoformat(),
        })
        reviewed += 1

    _save_history(history)
    pending = sum(1 for e in history if not e.get("reviewed"))
    return reviewed, pending


# ── 统计 + 学习 ──────────────────────────────────────────────────────────────

def _compute_stats(history: list) -> dict:
    """
    参考 trump-code learning_engine.compute_model_stats()
    按 ticker + action + reason 分组统计滚动胜率。
    """
    reviewed = [e for e in history if e.get("reviewed")]
    groups: dict[str, list] = {}

    for e in reviewed:
        key = f"{e['ticker']}|{e['action']}|{e['reason']}"
        groups.setdefault(key, []).append(e)

    stats = {}
    for key, trades in groups.items():
        trades_sorted = sorted(trades, key=lambda x: x["ts"])
        recent = trades_sorted[-_ROLLING_WINDOW:]
        correct = [t for t in recent if t["correct"]]
        rets = [t["actual_ret"] for t in recent if t["actual_ret"] is not None]
        win_rate = len(correct) / len(recent) * 100 if recent else 0
        streak = 0
        for t in reversed(recent):
            if t["correct"]: streak += 1
            else: break

        stats[key] = {
            "ticker":    trades[0]["ticker"],
            "action":    trades[0]["action"],
            "reason":    trades[0]["reason"],
            "total":     len(trades),
            "recent_n":  len(recent),
            "win_rate":  round(win_rate, 1),
            "avg_ret":   round(sum(rets) / len(rets), 2) if rets else 0,
            "streak":    streak,
            "weight":    _calc_weight(win_rate, streak),
        }
    return stats


def _calc_weight(win_rate: float, streak: int) -> float:
    """参考 trump-code 的权重调整逻辑。"""
    w = 1.0
    if win_rate >= _PROMOTE_RATE * 100: w *= _WEIGHT_UP
    elif win_rate <= _DEMOTE_RATE * 100: w *= _WEIGHT_DOWN
    if streak >= 4:  w *= _WEIGHT_UP
    elif streak <= -3: w *= _WEIGHT_DOWN
    return round(min(max(w, 0.1), 3.0), 2)


# ── 综合策略建议 ─────────────────────────────────────────────────────────────

def _load_backtest(ticker: str) -> list:
    path = _BACKTEST_DIR / f"backtest_{ticker.replace('.', '-')}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("results", [])
        except Exception:
            pass
    return []


def synthesize_strategy(ticker: str) -> dict:
    """
    结合回测历史 + 实盘胜率 → 综合建议。
    返回: {recommendation, best_bull_rule, best_bear_rule, live_win_rate, backtest_top}
    """
    history = _load_history()
    stats   = _compute_stats(history)
    bt      = _load_backtest(ticker)

    # 实盘胜率（此ticker，最近30笔）
    live = {k: v for k, v in stats.items() if v["ticker"] == ticker and v["recent_n"] >= 3}
    live_bull = sorted([v for v in live.values() if v["action"] in BUY_ACTIONS],
                       key=lambda x: x["win_rate"] * x["weight"], reverse=True)
    live_bear = sorted([v for v in live.values() if v["action"] in _EXECUTING_BEARISH_ACTIONS],
                       key=lambda x: x["win_rate"] * x["weight"], reverse=True)

    # 回测最优（按测试胜率）
    bt_bull = next((r for r in bt if r["action"] in BUY_ACTIONS), None)
    bt_bear = next((r for r in bt if r["action"] in _EXECUTING_BEARISH_ACTIONS), None)

    # 综合建议
    rec = "HOLD"
    if live_bull and live_bull[0]["win_rate"] >= 58:
        rec = "WATCH_BUY"
    elif live_bear and live_bear[0]["win_rate"] >= 58:
        rec = "CAUTION"
    elif bt_bull and bt_bull["test_wr"] >= 55 and (not live_bear or live_bear[0]["win_rate"] < 55):
        rec = "WATCH_BUY (backtest)"
    elif bt_bear and bt_bear["test_wr"] >= 55:
        rec = "CAUTION (backtest)"

    return {
        "ticker":       ticker,
        "recommendation": rec,
        "live_bull":    live_bull[0] if live_bull else None,
        "live_bear":    live_bear[0] if live_bear else None,
        "bt_bull":      bt_bull,
        "bt_bear":      bt_bear,
        "live_samples": sum(v["total"] for v in live.values()),
    }


# ── 报告生成 ─────────────────────────────────────────────────────────────────

def generate_review_report(tickers: list) -> str:
    W    = 68
    LINE = "-" * W
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 先跑一次复盘
    reviewed, pending = review_pending_signals()

    history = _load_history()
    stats   = _compute_stats(history)
    total   = len([e for e in history if e.get("reviewed")])
    correct = sum(1 for e in history if e.get("correct"))
    overall_wr = round(correct / total * 100, 1) if total else 0

    title    = t("每日复盘报告", "日次復盤レポート")
    unit_pen = t("笔", "回")
    lines = [
        "+" + "=" * (W - 2) + "+",
        "|  " + f"{title}  |  {now}".ljust(W - 4) + "|",
        "+" + "=" * (W - 2) + "+",
        "",
        t(
            f"  本次新复盘: {reviewed} 笔  |  待复盘: {pending} 笔  |  累计胜率: {overall_wr}% ({correct}/{total})",
            f"  今回新規復盤: {reviewed} 件  |  未復盤: {pending} 件  |  累計勝率: {overall_wr}% ({correct}/{total})",
        ),
        "",
    ]

    for ticker in tickers:
        name = ticker.split(".")[-1]
        lines.append(t(f"【{name} 实盘复盘】", f"【{name} 実取引復盤】"))
        lines.append(LINE)

        ticker_entries = [e for e in history if e["ticker"] == ticker and e.get("reviewed")]
        if not ticker_entries:
            lines.append(t("  暂无已复盘记录", "  復盤済の記録なし"))
            lines.append("")
            continue

        recent = sorted(ticker_entries, key=lambda x: x["ts"])[-5:]
        lines.append(t(f"  最近 {len(recent)} 笔:", f"  直近 {len(recent)} 件:"))
        for e in recent:
            icon = "✓" if e.get("correct") else "✗"
            lines.append(t(
                f"    {icon} {e['ts'][:10]}  {e['action']:<10}  "
                f"入场:{e['entry_price']:.2f} → 出场:{e['exit_price']:.2f}  "
                f"{e['actual_ret']:+.2f}%  [{e['reason']}]",
                f"    {icon} {e['ts'][:10]}  {e['action']:<10}  "
                f"エントリー:{e['entry_price']:.2f} → エグジット:{e['exit_price']:.2f}  "
                f"{e['actual_ret']:+.2f}%  [{e['reason']}]",
            ))
        lines.append("")

        # 分组胜率
        t_stats = sorted([v for v in stats.values() if v["ticker"] == ticker],
                         key=lambda x: x["win_rate"], reverse=True)
        if t_stats:
            lines.append(t(
                f"  信号胜率 (最近{_ROLLING_WINDOW}笔滚动):",
                f"  シグナル勝率 (直近{_ROLLING_WINDOW}件ローリング):",
            ))
            for s in t_stats[:5]:
                bar  = "█" * int(s["win_rate"] / 10) + "░" * (10 - int(s["win_rate"] / 10))
                if s["win_rate"] >= _PROMOTE_RATE * 100:
                    flag = t(" ▲权重+", " ▲ウェイト+")
                elif s["win_rate"] <= _DEMOTE_RATE * 100:
                    flag = t(" ▼权重-", " ▼ウェイト-")
                else:
                    flag = ""
                lines.append(
                    f"    {bar} {s['win_rate']:>5.1f}%  {s['action']:<10} "
                    f"{s['reason'][:20]:<20}  n={s['recent_n']}{flag}"
                )
        lines.append("")

    # 综合策略建议
    lines.append(t("【综合策略建议】", "【総合戦略提案】"))
    lines.append(LINE)
    for ticker in tickers:
        syn = synthesize_strategy(ticker)
        name = ticker.split(".")[-1]
        lines.append(f"  {name}: {syn['recommendation']}")
        if syn["live_bull"] and syn["live_bull"]["recent_n"] >= 3:
            lb = syn["live_bull"]
            lines.append(t(
                f"    买入依据: [{lb['reason']}]  实盘胜率 {lb['win_rate']}%  (n={lb['recent_n']})",
                f"    買い根拠: [{lb['reason']}]  実取引勝率 {lb['win_rate']}%  (n={lb['recent_n']})",
            ))
        elif syn["bt_bull"]:
            bb = syn["bt_bull"]
            lines.append(t(
                f"    买入参考: [{bb['name']}]  回测胜率 {bb['test_wr']}%  (n={bb['test_n']}，暂无实盘样本)",
                f"    買い参考: [{bb['name']}]  バックテスト勝率 {bb['test_wr']}%  (n={bb['test_n']}、実取引サンプルなし)",
            ))
        if syn["live_bear"] and syn["live_bear"]["recent_n"] >= 3:
            lb = syn["live_bear"]
            lines.append(t(
                f"    减仓依据: [{lb['reason']}]  实盘胜率 {lb['win_rate']}%  (n={lb['recent_n']})",
                f"    利確根拠: [{lb['reason']}]  実取引勝率 {lb['win_rate']}%  (n={lb['recent_n']})",
            ))
        elif syn["bt_bear"]:
            bb = syn["bt_bear"]
            lines.append(t(
                f"    减仓参考: [{bb['name']}]  回测胜率 {bb['test_wr']}%  (n={bb['test_n']}，暂无实盘样本)",
                f"    利確参考: [{bb['name']}]  バックテスト勝率 {bb['test_wr']}%  (n={bb['test_n']}、実取引サンプルなし)",
            ))

    lines += [
        "",
        "=" * W,
        t("  注: 实盘样本 <5 笔时以回测结果为主，>=5 笔时实盘权重逐渐提升",
          "  注: 実取引サンプル<5件はバックテスト優先、>=5件で実取引ウェイトを徐々に増加"),
        "=" * W,
    ]
    return "\n".join(lines)
