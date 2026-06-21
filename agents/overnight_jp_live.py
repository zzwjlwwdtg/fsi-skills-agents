"""
日股 Overnight Premium 实盘 (moomoo paper) — 每日动态 top 5 by dollar volume。

策略:
  · 每天 15:25 JST: 查询 30 只大型股的 dollar_vol 排序, 取 top 5
  · 提交 5 笔 OrderType.MARKET BUY → moomoo 路由到 引け itayose 拍卖
  · 次日 08:55 JST: 持仓全部 OrderType.MARKET SELL → 寄付 itayose 拍卖
  · 等权: 每只仓位 = PER_STOCK_JPY (默认 100k 円, 5 只共 500k 円)

⚠️ 必备:
  · moomoo SG/HK 账户开通 JP 市场 paper trading
  · OpenD 已登录 + JP 行情订阅 (LV1 即可)
  · 填入 ACC_ID_JP (用 probe 命令查询)

⚠️ 限制 (paper trading 真实性):
  · moomoo paper 撮合机制可能不是真 itayose 清算价
  · 一般按当时 last trade 或 best bid/ask 撮合 → 和真实 itayose 有微小偏差
  · 真实账户使用 OrderType.MARKET 在 15:25-15:30 提交才参与 引け
  · 实盘前用 paper 跑 1 个月看 fill 行为 (本脚本目的)

CLI:
  python overnight_jp_live.py probe      # 探查账户列表 (找 JP paper ID)
  python overnight_jp_live.py snapshot   # 看当前 universe dollar vol 排名
  python overnight_jp_live.py status     # 看持仓 + 累计盈亏
  python overnight_jp_live.py run        # 启动 (主循环, Ctrl+C 退出)
  python overnight_jp_live.py flatten    # 立即平掉所有持仓 (急救)
"""
from __future__ import annotations

import json
import sys
import time
import csv
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

try:
    from moomoo import (
        OpenSecTradeContext, OpenQuoteContext,
        TrdMarket, SecurityFirm, TrdEnv,
        TrdSide, OrderType, RET_OK,
    )
except ImportError:
    print("ERROR: 缺少 moomoo SDK. 安装: pip install moomoo-api")
    sys.exit(1)

from config import OPEND_HOST, OPEND_PORT


# ============ 用户配置 ============
ACC_ID_JP   = 0  # ← 填入你的 JP paper account ID (运行 probe 查询)
TRD_ENV     = TrdEnv.SIMULATE
PER_STOCK_JPY = 100_000   # 每只 10 万円 (5 只共 50 万円日敞口)
TOP_N         = 5

JST = ZoneInfo("Asia/Tokyo")

# 日股 30 大流动性常驻 — TSE Prime 大型股, 单元株 100
JP_UNIVERSE = [
    ("7203", "トヨタ自動車"),
    ("6758", "ソニーG"),
    ("9984", "ソフトバンクG"),
    ("8035", "東京エレクトロン"),
    ("6857", "アドバンテスト"),
    ("8306", "三菱UFJ"),
    ("9432", "NTT"),
    ("7974", "任天堂"),
    ("6098", "リクルートHD"),
    ("6861", "キーエンス"),
    ("4502", "武田薬品"),
    ("9433", "KDDI"),
    ("7267", "ホンダ"),
    ("8316", "三井住友FG"),
    ("4063", "信越化学"),
    ("6594", "ニデック"),
    ("4519", "中外製薬"),
    ("6981", "村田製作所"),
    ("4543", "テルモ"),
    ("8058", "三菱商事"),
    ("8031", "三井物産"),
    ("6273", "SMC"),
    ("7269", "スズキ"),
    ("8411", "みずほFG"),
    ("9101", "日本郵船"),
    ("8053", "住友商事"),
    ("4661", "オリエンタルランド"),
    ("9020", "JR東日本"),
    ("8001", "伊藤忠商事"),
    ("4568", "第一三共"),
]

# TSE 假日 (写到 2026 年底)
JP_HOLIDAYS = {
    "2026-07-20",  # 海の日
    "2026-08-11",  # 山の日
    "2026-09-21",  # 敬老の日
    "2026-09-23",  # 秋分の日
    "2026-10-12",  # スポーツの日
    "2026-11-03",  # 文化の日
    "2026-11-23",  # 勤労感謝の日
    "2026-12-31",  # 大晦日 (TSE 休市)
}

# 日志 / 状态目录
BASE = Path(__file__).parent / "overnight_jp_state"
BASE.mkdir(exist_ok=True)
POSITIONS_FILE = BASE / "positions.json"     # 当前持仓
TRADES_FILE    = BASE / "trades.csv"         # 全部交易记录
LOG_FILE       = BASE / "overnight_jp.log"   # 运行日志

# 调度窗口 (JST):
BUY_HOUR, BUY_MIN   = 15, 25  # 引け 拍卖 15:30 前 5 分钟
SELL_HOUR, SELL_MIN =  8, 55  # 寄付 拍卖 09:00 前 5 分钟


# ============ 辅助: 代码格式 / 日志 ============

def to_moomoo(code: str) -> str:
    return f"JP.{code}"

def to_yf(code: str) -> str:
    return f"{code}.T"

def now_jst() -> datetime:
    return datetime.now(JST)

def log(msg: str):
    ts = now_jst().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:   # Sat/Sun
        return False
    if d.strftime("%Y-%m-%d") in JP_HOLIDAYS:
        return False
    return True


# ============ moomoo 连接 ============

_quote_ctx = None
_trd_ctx = None

def get_quote_ctx() -> OpenQuoteContext:
    global _quote_ctx
    if _quote_ctx is None:
        _quote_ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    return _quote_ctx

def get_trd_ctx() -> OpenSecTradeContext:
    global _trd_ctx
    if _trd_ctx is None:
        _trd_ctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.JP,
            host=OPEND_HOST, port=OPEND_PORT,
            security_firm=SecurityFirm.FUTUSECURITIES,
        )
    return _trd_ctx


# ============ 行情 ============

def get_snapshots() -> pd.DataFrame | None:
    codes = [to_moomoo(c) for c, _ in JP_UNIVERSE]
    ctx = get_quote_ctx()
    ret, data = ctx.get_market_snapshot(codes)
    if ret != RET_OK:
        log(f"[ERR] get_market_snapshot 失败: {data}")
        return None
    return data

def rank_top5_by_dollar_vol() -> list[tuple[str, str, float, float]]:
    """返回 top 5: [(code, name, last_price, dollar_vol_today), ...]"""
    snap = get_snapshots()
    if snap is None or snap.empty:
        return []
    snap = snap.copy()
    snap["dollar_vol"] = snap["last_price"] * snap["volume"]
    snap = snap.sort_values("dollar_vol", ascending=False).head(TOP_N)
    code_to_name = {to_moomoo(c): n for c, n in JP_UNIVERSE}
    return [
        (row["code"].split(".", 1)[1], code_to_name.get(row["code"], "?"),
         float(row["last_price"]), float(row["dollar_vol"]))
        for _, row in snap.iterrows()
    ]


# ============ 状态持久化 ============

def load_positions() -> dict:
    if not POSITIONS_FILE.exists():
        return {"date": None, "positions": []}
    return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))

def save_positions(state: dict):
    POSITIONS_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")

def log_trade(side: str, code: str, name: str, qty: int, price: float,
              order_id: str, status: str, tag: str = ""):
    ts = now_jst().strftime("%Y-%m-%d %H:%M:%S")
    header_needed = not TRADES_FILE.exists()
    with TRADES_FILE.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if header_needed:
            w.writerow(["timestamp", "side", "code", "name", "qty",
                        "price", "order_id", "status", "tag"])
        w.writerow([ts, side, code, name, qty, f"{price:.1f}",
                    order_id, status, tag])


# ============ 下单: 成行 (MARKET) → moomoo 路由到 itayose ============

def place_market_order(code: str, name: str, side, qty: int, tag: str) -> tuple[str, float]:
    """
    用 OrderType.MARKET 提交. 在 15:25-15:30 提交时, moomoo 将其路由到 引け itayose;
    在 08:55-09:00 提交时, 路由到 寄付 itayose.
    paper account 撮合可能不是真 itayose 价 (见脚本头注释).
    返回 (order_id, fill_price)
    """
    mcode = to_moomoo(code)
    side_label = "BUY" if side == TrdSide.BUY else "SELL"
    ctx = get_trd_ctx()
    if ACC_ID_JP == 0:
        log(f"[ERR] ACC_ID_JP 未设置 (运行 'probe' 查询)")
        return ("", 0.0)
    try:
        ret, info = ctx.place_order(
            price=0,   # MARKET 时 price 被忽略
            qty=float(qty), code=mcode,
            trd_side=side, order_type=OrderType.MARKET,
            trd_env=TRD_ENV, acc_id=ACC_ID_JP,
        )
    except Exception as e:
        log(f"[ERR] place_order EXC {side_label} {qty} {mcode}: {e}")
        log_trade(side_label, code, name, qty, 0, "", "EXC", tag)
        return ("", 0.0)
    if ret != RET_OK:
        log(f"[ERR] place_order FAIL {side_label} {qty} {mcode}: {info}")
        log_trade(side_label, code, name, qty, 0, "", "FAIL", tag)
        return ("", 0.0)
    oid = str(info.iloc[0]["order_id"])
    log(f"[OK ] {side_label:<4} {qty:>5} {code} {name:<14} order={oid}  ({tag})")
    log_trade(side_label, code, name, qty, 0, oid, "SUBMITTED", tag)
    return (oid, 0.0)


def query_fill(order_id: str) -> tuple[float, int, str]:
    """查询订单成交均价 + 已成交数量 + 状态."""
    ctx = get_trd_ctx()
    ret, data = ctx.order_list_query(order_id=order_id,
                                      trd_env=TRD_ENV, acc_id=ACC_ID_JP)
    if ret != RET_OK or data.empty:
        return (0.0, 0, "UNKNOWN")
    row = data.iloc[0]
    return (float(row.get("dealt_avg_price", 0)),
            int(row.get("dealt_qty", 0)),
            str(row.get("order_status", "UNKNOWN")))


# ============ 日例程: 买 + 卖 ============

def routine_buy():
    """15:25 JST: 选 top 5, 等权各下 PER_STOCK_JPY/price 股 (单元 100), MARKET 单."""
    today = now_jst().date()
    state = load_positions()
    if state.get("date") == today.isoformat() and state.get("positions"):
        log(f"[skip] 今天 {today} 已建仓 ({len(state['positions'])} 只), 跳过")
        return
    if not is_trading_day(today):
        log(f"[skip] {today} 不是 TSE 交易日")
        return

    top5 = rank_top5_by_dollar_vol()
    if len(top5) < TOP_N:
        log(f"[ERR] 获取 top5 失败, 只拿到 {len(top5)} 只")
        return

    log(f"=== 引け 建仓: top 5 by dollar vol ===")
    new_positions = []
    for code, name, price, dvol in top5:
        if price <= 0:
            log(f"[skip] {code} {name} 价格异常 {price}")
            continue
        # 整百 (TSE 单元株)
        raw_qty = PER_STOCK_JPY / price
        qty = max(100, int(raw_qty // 100) * 100)
        log(f"  {code} {name:<14} 价 ¥{price:>8.1f}  dvol ¥{dvol/1e8:>6.1f}亿  → 买 {qty} 株")
        oid, _ = place_market_order(code, name, TrdSide.BUY, qty,
                                     tag=f"OVERNIGHT-BUY-{today}")
        if oid:
            new_positions.append({
                "code": code, "name": name, "qty": qty,
                "buy_price_hint": price, "buy_order_id": oid,
                "buy_time": now_jst().isoformat(),
            })
    save_positions({"date": today.isoformat(), "positions": new_positions})
    log(f"=== 建仓完成: {len(new_positions)} 只持仓过夜 ===")


def routine_sell():
    """08:55 JST: 把昨天的持仓全部 MARKET 卖出 (寄付 itayose)."""
    state = load_positions()
    positions = state.get("positions", [])
    if not positions:
        log("[skip] 无昨日持仓, 跳过寄付卖出")
        return
    today = now_jst().date()
    if not is_trading_day(today):
        log(f"[skip] {today} 不是 TSE 交易日 (持仓保留到下一交易日)")
        return

    log(f"=== 寄付 平仓: {len(positions)} 只 ===")
    for p in positions:
        oid, _ = place_market_order(p["code"], p["name"], TrdSide.SELL,
                                     p["qty"], tag=f"OVERNIGHT-SELL-{today}")
        p["sell_order_id"] = oid
        p["sell_time"] = now_jst().isoformat()

    # 等 30 秒让 fill 回来, 然后查询填上买卖价格
    time.sleep(30)
    for p in positions:
        if p.get("buy_order_id"):
            bp, _, _ = query_fill(p["buy_order_id"])
            p["buy_fill_price"] = bp
        if p.get("sell_order_id"):
            sp, _, _ = query_fill(p["sell_order_id"])
            p["sell_fill_price"] = sp

    # 写入 trades.csv 完整记录 + 计算单只 P&L
    total_pnl = 0
    for p in positions:
        bp = p.get("buy_fill_price", 0)
        sp = p.get("sell_fill_price", 0)
        if bp > 0 and sp > 0:
            pnl = (sp - bp) * p["qty"]
            pct = (sp / bp - 1) * 100
            total_pnl += pnl
            log(f"  {p['code']} {p['name']:<14} 买 ¥{bp:>7.1f} → 卖 ¥{sp:>7.1f}  "
                f"({pct:+.2f}%)  PnL ¥{pnl:+,.0f}")
        else:
            log(f"  {p['code']} {p['name']:<14} fill 未确认 (buy={bp}, sell={sp})")
    log(f"=== 本日合计 P&L: ¥{total_pnl:+,.0f} ===")

    # 清空持仓状态
    save_positions({"date": None, "positions": []})


# ============ CLI ============

def cmd_probe():
    """列出可用 trade 账户."""
    ctx = get_trd_ctx()
    ret, data = ctx.get_acc_list()
    if ret != RET_OK:
        print(f"FAIL: {data}")
        return
    print("可用 trade 账户:")
    print(data.to_string())
    print("\n→ 把 JP SIMULATE 账户的 acc_id 填到脚本 ACC_ID_JP")

def cmd_snapshot():
    """看当前 universe top 5."""
    print(f"[{now_jst()}] universe 30 → top {TOP_N} by dollar_vol:")
    top5 = rank_top5_by_dollar_vol()
    for code, name, price, dvol in top5:
        print(f"  {code} {name:<14} 价 ¥{price:>8.1f}  dvol ¥{dvol/1e8:>6.1f}亿")

def cmd_status():
    """看当前持仓 + 累计 P&L."""
    state = load_positions()
    print(f"State date: {state.get('date')}")
    print(f"当前持仓 ({len(state.get('positions', []))} 只):")
    for p in state.get("positions", []):
        print(f"  {p['code']} {p['name']:<14} qty={p['qty']}  buy_oid={p.get('buy_order_id')}")
    if TRADES_FILE.exists():
        df = pd.read_csv(TRADES_FILE)
        print(f"\n累计交易: {len(df)} 行 (见 {TRADES_FILE})")

def cmd_flatten():
    """急救: 平掉所有 JP 持仓 (不管 state 文件)."""
    ctx = get_trd_ctx()
    ret, data = ctx.position_list_query(trd_env=TRD_ENV, acc_id=ACC_ID_JP)
    if ret != RET_OK:
        print(f"FAIL: {data}")
        return
    print(f"当前账户 {len(data)} 个持仓, 全部 MARKET SELL:")
    for _, row in data.iterrows():
        code = row["code"]
        qty = int(row["qty"])
        if qty <= 0:
            continue
        ret2, info = ctx.place_order(
            price=0, qty=float(qty), code=code,
            trd_side=TrdSide.SELL, order_type=OrderType.MARKET,
            trd_env=TRD_ENV, acc_id=ACC_ID_JP,
        )
        print(f"  {code} qty={qty}: {'OK' if ret2 == RET_OK else f'FAIL {info}'}")
    save_positions({"date": None, "positions": []})

def cmd_run():
    """主循环: 每 30s 检查时间, 触发 buy/sell."""
    if ACC_ID_JP == 0:
        print("ERROR: 请先把 ACC_ID_JP 填进脚本 (运行 probe 查询)")
        return
    log(f"=== 启动 overnight_jp_live (acc={ACC_ID_JP}, env={TRD_ENV}) ===")
    log(f"  universe: {len(JP_UNIVERSE)} 只, top_n={TOP_N}, per_stock=¥{PER_STOCK_JPY:,}")
    last_buy_date = None
    last_sell_date = None
    while True:
        try:
            now = now_jst()
            today = now.date().isoformat()
            # SELL 窗口: 08:55-08:59 JST (寄付前)
            if (now.hour == SELL_HOUR and SELL_MIN <= now.minute < SELL_MIN + 5
                and last_sell_date != today):
                routine_sell()
                last_sell_date = today
            # BUY 窗口: 15:25-15:29 JST (引け前)
            elif (now.hour == BUY_HOUR and BUY_MIN <= now.minute < BUY_MIN + 5
                  and last_buy_date != today):
                routine_buy()
                last_buy_date = today
            time.sleep(30)
        except KeyboardInterrupt:
            log("收到 Ctrl+C, 退出")
            break
        except Exception as e:
            log(f"[ERR] main loop: {e}")
            time.sleep(60)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    {
        "probe":    cmd_probe,
        "snapshot": cmd_snapshot,
        "status":   cmd_status,
        "flatten":  cmd_flatten,
        "run":      cmd_run,
    }.get(cmd, lambda: print(f"未知命令: {cmd}"))()


if __name__ == "__main__":
    main()
