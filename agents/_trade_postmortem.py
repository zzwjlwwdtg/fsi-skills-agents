"""
_trade_postmortem.py
────────────────────
读 signals/trade_log.jsonl，把 BUY/SELL 配对，算每笔交易的：
  · 持仓时长
  · 实现 P&L (%)
  · 触发原因（决策 reason / 退出原因 tag）
  · 触发时市场状态 (regime / RSI / CCI / trend)

输出归因报告：哪类信号最赚，哪类最亏。
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

LOG_PATH = Path(__file__).parent / "signals" / "trade_log.jsonl"
REPORT_PATH = Path(__file__).parent / "signals" / "trade_postmortem.md"


def load_log() -> list:
    if not LOG_PATH.exists():
        return []
    out = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def pair_trades(events: list) -> list[dict]:
    """把同 ticker 的 BUY -> SELL 配对（FIFO）。
    PYRAMID 算追加仓位（加权平均 entry_price），TRAILING/TP/SELL 都算退出事件。"""
    open_positions = defaultdict(list)   # ticker -> [{qty, price, ts, decision, mkt}]
    closed_trades = []

    for ev in events:
        if ev.get("dry_run"):
            continue   # 只复盘真实成交（也可放开看 dry）
        ticker = ev["ticker"]
        side = ev["side"]
        qty = ev["qty"]
        price = ev["price"]
        ts = ev["ts"]
        if side == "BUY":
            open_positions[ticker].append({
                "qty": qty, "price": price, "ts": ts,
                "decision": ev.get("decision", {}), "mkt": ev.get("market", {}),
                "tag": ev.get("tag", ""),
            })
        elif side == "SELL":
            remaining = qty
            while remaining > 0 and open_positions[ticker]:
                pos = open_positions[ticker][0]
                close_qty = min(remaining, pos["qty"])
                entry_dt = datetime.fromisoformat(pos["ts"].replace("Z", "+00:00"))
                exit_dt  = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                hold_days = (exit_dt - entry_dt).total_seconds() / 86400
                pnl_pct = (price - pos["price"]) / pos["price"] * 100
                closed_trades.append({
                    "ticker":     ticker,
                    "entry_ts":   pos["ts"],
                    "exit_ts":    ts,
                    "hold_days":  round(hold_days, 1),
                    "entry_price": pos["price"],
                    "exit_price": price,
                    "qty":        close_qty,
                    "pnl_pct":    round(pnl_pct, 2),
                    "pnl_usd":    round((price - pos["price"]) * close_qty, 2),
                    "entry_reason": pos["decision"].get("reason", ""),
                    "entry_action": pos["decision"].get("action"),
                    "entry_conf":   pos["decision"].get("confidence"),
                    "entry_regime": pos["decision"].get("regime"),
                    "exit_tag":     ev.get("tag", ""),
                    "entry_rsi":    pos["mkt"].get("rsi"),
                    "entry_cci":    pos["mkt"].get("cci"),
                    "entry_trend":  pos["mkt"].get("trend"),
                })
                pos["qty"] -= close_qty
                if pos["qty"] <= 0:
                    open_positions[ticker].pop(0)
                remaining -= close_qty
    return closed_trades


def classify_exit(tag: str) -> str:
    tag = tag.upper()
    if "TRAILING-STOP" in tag: return "TRAILING_STOP"
    if "TAKE-PROFIT" in tag or "TP_" in tag: return "TAKE_PROFIT"
    if "STOP" in tag: return "STOP"
    if "PYRAMID" in tag: return "PYRAMID_EXIT"
    if "REBUY" in tag: return "REBUY"
    return "NORMAL"


def report(trades: list[dict]):
    if not trades:
        print("❌ trade_log.jsonl 无 BUY/SELL 配对（DRY_RUN 过滤后）。")
        print("   → 等 LIVE 模式下跑几笔后再来 / 或临时关闭 DRY 过滤")
        return

    n = len(trades)
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    total_pnl_usd = sum(t["pnl_usd"] for t in trades)
    avg_hold = sum(t["hold_days"] for t in trades) / n
    win_rate = len(wins) / n * 100 if n else 0
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

    print(f"\n{'='*70}")
    print(f"  Trade Postmortem ({n} 笔已平仓交易)")
    print(f"{'='*70}")
    print(f"  胜率 : {win_rate:.0f}% ({len(wins)}/{n})")
    print(f"  平均赢 : +{avg_win:.2f}%   平均亏 : {avg_loss:.2f}%")
    print(f"  盈亏比 : {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "  盈亏比 : ∞")
    print(f"  总 P&L (USD): {total_pnl_usd:+,.2f}")
    print(f"  平均持仓 : {avg_hold:.1f} 天")

    # 按入场原因
    print(f"\n  ── 按入场 reason 归因 ──")
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t["entry_reason"][:50]].append(t)
    for reason, ts in sorted(by_reason.items(), key=lambda x: -sum(t["pnl_pct"] for t in x[1])):
        wr = sum(1 for t in ts if t["pnl_pct"] > 0) / len(ts) * 100
        avg = sum(t["pnl_pct"] for t in ts) / len(ts)
        print(f"    {reason or '(unknown)':<50} n={len(ts):>3}  胜{wr:>3.0f}%  avg{avg:>+6.2f}%")

    # 按退出原因
    print(f"\n  ── 按退出 tag 归因 ──")
    by_exit = defaultdict(list)
    for t in trades:
        by_exit[classify_exit(t["exit_tag"])].append(t)
    for tag, ts in sorted(by_exit.items(), key=lambda x: -sum(t["pnl_pct"] for t in x[1])):
        wr = sum(1 for t in ts if t["pnl_pct"] > 0) / len(ts) * 100
        avg = sum(t["pnl_pct"] for t in ts) / len(ts)
        print(f"    {tag:<20} n={len(ts):>3}  胜{wr:>3.0f}%  avg{avg:>+6.2f}%")

    # 按 ticker
    print(f"\n  ── 按 ticker 归因 ──")
    by_tk = defaultdict(list)
    for t in trades:
        by_tk[t["ticker"]].append(t)
    for tk, ts in sorted(by_tk.items(), key=lambda x: -sum(t["pnl_usd"] for t in x[1])):
        wr = sum(1 for t in ts if t["pnl_pct"] > 0) / len(ts) * 100
        avg = sum(t["pnl_pct"] for t in ts) / len(ts)
        usd = sum(t["pnl_usd"] for t in ts)
        print(f"    {tk:<12} n={len(ts):>3}  胜{wr:>3.0f}%  avg{avg:>+6.2f}%  ${usd:+,.0f}")


def main():
    events = load_log()
    if not events:
        print("❌ signals/trade_log.jsonl 不存在或为空 — 等 trade 累积后再来")
        return 1
    trades = pair_trades(events)
    report(trades)
    return 0


if __name__ == "__main__":
    sys.exit(main())
