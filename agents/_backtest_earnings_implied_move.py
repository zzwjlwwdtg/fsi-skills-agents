"""
_backtest_earnings_implied_move
─────────────────────────────────
验证：
  · MU 历史财报 T+0 实际单日 move 的分布
  · 实际 move > 12% / 6% 的发生率（验证 _apply_earnings_guard 的 bracket）
  · DRAM/MULL 财报 T+1 ~ T+5 跟随幅度
  · MU 当前 implied move（13.4%）vs 历史实际 ±%：是高估还是低估？

不需要历史期权数据 — 只用 yfinance 现货 close。
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta


def _next_trading_close_after(prices: pd.DataFrame, date: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    """返回 date 之后第一个交易日的 (date, close)。"""
    later = prices[prices.index > date]
    if later.empty:
        return None
    return later.index[0], float(later["Close"].iloc[0])


def _prev_trading_close_at_or_before(prices: pd.DataFrame, date: pd.Timestamp) -> tuple[pd.Timestamp, float] | None:
    earlier = prices[prices.index <= date]
    if earlier.empty:
        return None
    return earlier.index[-1], float(earlier["Close"].iloc[-1])


def analyze_mu_earnings_history(years_back: int = 5):
    """拉 MU 过去 N 年财报 + 前后股价。

    AMC 财报 → 股价反应在 next trading day close。
    realized move = (next_close - amc_day_close) / amc_day_close
    """
    print(f"=== MU 过去 {years_back} 年财报 T+0 实际 move 回测 ===\n")
    mu = yf.Ticker("MU")
    ed = mu.earnings_dates
    if ed is None or ed.empty:
        print("无 earnings_dates 数据")
        return None

    # 过滤已发生的财报（reported_eps not NaN）
    past = ed[ed["Reported EPS"].notna()].copy()
    # 限制时间范围
    cutoff = datetime.now() - timedelta(days=years_back * 365)
    past.index = pd.to_datetime(past.index, utc=True).tz_convert("America/New_York").tz_localize(None)
    past = past[past.index >= cutoff]
    if past.empty:
        print(f"过去 {years_back} 年无已发布财报")
        return None

    # 拉 MU 完整价格历史
    px = mu.history(period=f"{years_back}y")
    if px.index.tz is not None:
        px.index = px.index.tz_localize(None)

    rows = []
    for amc_dt in past.index:
        prev = _prev_trading_close_at_or_before(px, amc_dt)
        nxt = _next_trading_close_after(px, amc_dt)
        if not prev or not nxt:
            continue
        amc_close = prev[1]
        next_close = nxt[1]
        move_pct = (next_close - amc_close) / amc_close * 100
        surprise = past.loc[amc_dt, "Surprise(%)"]
        rows.append({
            "amc_date":   amc_dt.date(),
            "amc_close":  round(amc_close, 2),
            "next_date":  nxt[0].date(),
            "next_close": round(next_close, 2),
            "move_pct":   round(move_pct, 2),
            "surprise%":  round(float(surprise) if pd.notna(surprise) else 0, 1),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("无可用数据")
        return None

    print(df.to_string(index=False))
    print()

    abs_moves = df["move_pct"].abs()
    n = len(df)
    print(f"样本数 : {n} 次财报")
    print(f"平均 |move| : {abs_moves.mean():.2f}%")
    print(f"中位 |move| : {abs_moves.median():.2f}%")
    print(f"最大 |move| : {abs_moves.max():.2f}% ({df.loc[abs_moves.idxmax(),'amc_date']})")
    print(f"最小 |move| : {abs_moves.min():.2f}%")
    print()
    for thr in (5, 6, 8, 10, 12, 15, 20):
        pct = (abs_moves > thr).sum() / n * 100
        print(f"  |move| > {thr:>2}% : {(abs_moves > thr).sum():>2}/{n}  ({pct:.0f}%)")
    return df


def compare_implied_vs_realized(current_im_pct: float, df: pd.DataFrame):
    print(f"\n=== MU 当前 implied move = {current_im_pct:.1f}% 对比历史 ===\n")
    abs_moves = df["move_pct"].abs()
    higher = (abs_moves > current_im_pct).sum()
    n = len(df)
    print(f"历史 {n} 次财报中，实际 |move| > {current_im_pct:.1f}% 的次数: {higher}/{n} ({higher/n*100:.0f}%)")
    print(f"  → 若 implied 准确，约 {n - higher}/{n} 次 implied 高估、{higher}/{n} 次 implied 低估")
    print()
    print("guard rule 检验：")
    print(f"  · MULL (2x): leveraged_im = {current_im_pct*2:.1f}% > 20% → 强制 HOLD")
    print(f"    历史 MU 实际 |move| × 2 的分布：")
    for thr in (10, 15, 20, 25, 30):
        pct = ((abs_moves * 2) > thr).sum() / n * 100
        print(f"      MULL 实际 |move| > {thr}% : {((abs_moves * 2) > thr).sum()}/{n}  ({pct:.0f}%)")
    print(f"  · DRAM (1x): leveraged_im = {current_im_pct:.1f}% → 12-20% 范围，conf-3")
    print(f"    历史 MU 实际 |move| 的分布看 DRAM 跟随：")


def check_dram_mull_follow(years_back: int = 3):
    """DRAM/MULL 财报 T+1 跟随：与 MU 同期实际 move 比对。"""
    print(f"\n=== DRAM / MULL 财报跟随 MU 历史 ===\n")
    mu = yf.Ticker("MU")
    ed = mu.earnings_dates
    if ed is None or ed.empty:
        return
    past = ed[ed["Reported EPS"].notna()].copy()
    cutoff = datetime.now() - timedelta(days=years_back * 365)
    past.index = pd.to_datetime(past.index, utc=True).tz_convert("America/New_York").tz_localize(None)
    past = past[past.index >= cutoff]

    for sym, lev in [("DRAM", 1.0), ("MULL", 2.0)]:
        print(f"--- {sym} (与 MU 杠杆 ~{lev}x) ---")
        sym_t = yf.Ticker(sym)
        px = sym_t.history(period=f"{years_back}y")
        if px.empty:
            print(f"  {sym} 无足够历史数据（ETF 可能较新）")
            continue
        if px.index.tz is not None:
            px.index = px.index.tz_localize(None)
        mu_px = mu.history(period=f"{years_back}y")
        if mu_px.index.tz is not None:
            mu_px.index = mu_px.index.tz_localize(None)
        rows = []
        for amc_dt in past.index:
            sp = _prev_trading_close_at_or_before(px, amc_dt)
            sn = _next_trading_close_after(px, amc_dt)
            mp = _prev_trading_close_at_or_before(mu_px, amc_dt)
            mn = _next_trading_close_after(mu_px, amc_dt)
            if not all([sp, sn, mp, mn]):
                continue
            sym_move = (sn[1] - sp[1]) / sp[1] * 100
            mu_move  = (mn[1] - mp[1]) / mp[1] * 100
            beta = sym_move / mu_move if abs(mu_move) > 0.5 else None
            rows.append({
                "amc_date":  amc_dt.date(),
                "mu_move%":  round(mu_move, 2),
                f"{sym}_move%": round(sym_move, 2),
                "beta":      round(beta, 2) if beta else None,
            })
        if not rows:
            print(f"  无可对照数据")
            continue
        df = pd.DataFrame(rows)
        print(df.to_string(index=False))
        valid_beta = df["beta"].dropna()
        if not valid_beta.empty:
            print(f"  {sym} 实际 beta 中位数: {valid_beta.median():.2f}x (设定 leverage={lev}x)")
        print()


def main():
    df = analyze_mu_earnings_history(years_back=5)
    if df is None:
        return
    # 当前 MU implied move = 13.4%（smoothed）— 来自 get_earnings_implied_move
    try:
        from option_walls import get_earnings_implied_move
        em = get_earnings_implied_move("MU")
        current_im = em.get("smoothed_implied_move_pct") or em.get("implied_move_pct") or 13.4
    except Exception:
        current_im = 13.4
    compare_implied_vs_realized(current_im, df)
    check_dram_mull_follow(years_back=3)


if __name__ == "__main__":
    main()
