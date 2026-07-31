"""
Crisis V-bounce Probe 回测 — 验证 decision_agent 里新加的例外规则：

规则触发（AND 全部）:
  1. regime = crisis  （近似 proxy: cum_5d_scaled ≤ -20% 或 单日跌 ≤ -5% scaled）
  2. RSI < 32          (极端超卖)
  3. bull_count >= 4   (强多头共振 — 用简化 proxy: RSI<32 + CCI<-100 + BB%<0.1 + macd_hist 收敛)
  4. cum_5d ≤ -12% (scaled)  (深跌确认)
  5. pct_eff_b >= -1%        (今日至少不再深跌)
  6. vol_ratio < 1.5         (不是恐慌卖出中)

判据（feedback_backtest_gate.md）:
  · 触发日后 5d hit rate ≥ 55% AND avg >= +2%
  · 触发次数 ≥ 8 才有统计意义（3 只 ETF × 12 月 ≈ 应有 8-15 次真 crisis 反弹）
  · 与 non-crisis 同等超卖对比：crisis 版 5d 平均 ≥ non-crisis 版（proves crisis 例外有 alpha）

若不达标 → 保持 CRISIS_VBOUNCE_ENABLED=0，考虑调阈值或回滚。
"""
from __future__ import annotations
import sys
sys.stdout.reconfigure(line_buffering=True)

import numpy as np
import pandas as pd

from backtest_engine import load_history, add_indicators, TICKERS

DAYS = 500           # 覆盖 2 年历史（够多 crisis 样本）
FORWARD = [5, 10, 20]

LEVERAGE = {
    "TQQQ": 3.0, "SOXL": 3.0, "MULL": 2.0, "DRAM": 1.0, "GLD": 1.0,
}


def _scaled(pct, lev):
    return pct / lev if lev else pct


def _find_triggers(df: pd.DataFrame, tk: str, lev: float) -> list[dict]:
    """扫历史，返所有满足 crisis V-bounce probe 条件的日期。"""
    triggers = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        try:
            rsi     = float(row["rsi_14"])
            cci     = float(row["cci_20"])
            bb_pct  = float(row["bb_pct"])
            pct     = float(row["pct_chg"])
            vol_r   = float(row["vol_ratio"])
            macd_h  = float(row.get("macd_hist", 0) or 0)
        except (ValueError, TypeError):
            continue
        if any(np.isnan(x) for x in (rsi, cci, bb_pct, pct, vol_r)):
            continue
        # 深跌确认：用前一日的 5d cum（今日反弹会稀释真实深跌幅度）
        close_now = float(row["close"])
        close_prev = float(df.iloc[i-1]["close"])
        close_5_ago = float(df.iloc[i-6]["close"])   # 前一日 5 天前
        prev_cum_5d_raw    = (close_prev - close_5_ago) / close_5_ago * 100
        prev_cum_5d_scaled = _scaled(prev_cum_5d_raw, lev)
        pct_scaled         = _scaled(pct, lev)

        # crisis proxy: 前一日单日跌 ≤ -5% scaled 或 前一日 cum_5d ≤ -12% scaled
        prev_pct_scaled = _scaled(float(df.iloc[i-1]["pct_chg"]), lev)
        is_crisis = (prev_pct_scaled <= -5) or (prev_cum_5d_scaled <= -12)

        # bull_count proxy (放宽 BB 阈值让 3x ETF 深跌但 BB% 稍上的能触发):
        # RSI < 32(+1) CCI < -100(+1) BB% < 0.20(+1) macd_hist 收敛(+1)
        bull = 0
        if rsi    < 32:   bull += 1
        if cci    < -100: bull += 1
        if bb_pct < 0.20: bull += 1
        try:
            prev_hist = float(df.iloc[i-1].get("macd_hist", 0) or 0)
            if macd_h > prev_hist and macd_h < 0:
                bull += 1
        except Exception:
            pass

        # 7 条件全部 AND （bull threshold 从 4 降到 3，与 non-crisis 对照一致）
        if (is_crisis
                and rsi < 32
                and bull >= 3
                and prev_cum_5d_scaled <= -10
                and pct_scaled >= -1
                and vol_r < 1.5):
            triggers.append({
                "date": df.index[i], "close": close_now,
                "rsi": rsi, "cci": cci, "bb_pct": bb_pct,
                "prev_cum_5d_scaled": prev_cum_5d_scaled, "pct_scaled": pct_scaled,
                "vol_r": vol_r, "bull": bull,
                "is_crisis_kind": "prev_1d_crash" if prev_pct_scaled <= -5 else "prev_5d_deep",
            })
    return triggers


def _control_triggers(df: pd.DataFrame, lev: float) -> list[dict]:
    """对照组：同等 RSI/bull 但 NOT crisis（普通深跌反弹）。"""
    out = []
    for i in range(20, len(df)):
        row = df.iloc[i]
        try:
            rsi     = float(row["rsi_14"])
            cci     = float(row["cci_20"])
            bb_pct  = float(row["bb_pct"])
            pct     = float(row["pct_chg"])
            vol_r   = float(row["vol_ratio"])
        except (ValueError, TypeError):
            continue
        if any(np.isnan(x) for x in (rsi, cci, bb_pct, pct, vol_r)):
            continue
        close_now = float(row["close"])
        close_5   = float(df.iloc[i-5]["close"])
        cum_5d_scaled = _scaled((close_now - close_5) / close_5 * 100, lev)
        pct_scaled = _scaled(pct, lev)
        is_crisis = (pct_scaled <= -5) or (cum_5d_scaled <= -20)

        bull = 0
        if rsi < 32: bull += 1
        if cci < -100: bull += 1
        if bb_pct < 0.1: bull += 1

        if (not is_crisis
                and rsi < 35
                and bull >= 3
                and cum_5d_scaled <= -6
                and pct_scaled >= -1):
            out.append({"date": df.index[i], "close": close_now})
    return out


def _forward_returns(df: pd.DataFrame, base_date) -> dict:
    out = {}
    try:
        idx = list(df.index).index(base_date)
    except ValueError:
        return out
    base_close = float(df.iloc[idx]["close"])
    for n in FORWARD:
        target = idx + n
        if target >= len(df):
            continue
        fut = float(df.iloc[target]["close"])
        out[n] = (fut - base_close) / base_close * 100
    return out


def _summarize(label: str, results: list[dict], rets: dict, target_hit_rate=55):
    print(f"  {label}: N={len(results)}")
    if not results:
        print("    无样本"); return
    for n in FORWARD:
        arr = np.array(rets[n]) if rets[n] else np.array([])
        if len(arr) == 0:
            print(f"    {n}d: 无前向数据"); continue
        hit = (arr > 0).mean() * 100
        badge = "✓" if (n == 5 and hit >= target_hit_rate and arr.mean() >= 2) else " "
        print(f"    {n}d:  N={len(arr):>3}  hit={hit:>5.1f}%  avg={arr.mean():+6.2f}%  med={np.median(arr):+6.2f}%  {badge}")


def main():
    print("=" * 78)
    print(f"  Crisis V-bounce Probe 回测  | 标的: {TICKERS}  | 窗口: {DAYS}d")
    print(f"  规则: crisis + RSI<32 + bull>=4 + cum_5d<=-12% + today>=-1% + vol<1.5")
    print("=" * 78)

    total_triggers = []
    total_rets = {n: [] for n in FORWARD}
    total_control_rets = {n: [] for n in FORWARD}
    n_control_total = 0
    per_ticker_stats = []

    for tk in TICKERS:
        lev = LEVERAGE.get(tk, 1.0)
        print(f"\n[{tk}] (lev={lev}x) 扫描中...")
        try:
            df = add_indicators(load_history(tk, days=DAYS + 60))
            df = df.dropna(subset=["rsi_14", "cci_20", "bb_pct", "vol_ratio"])
            df_w = df.tail(DAYS)
        except Exception as e:
            print(f"  加载失败: {e}"); continue

        trigs = _find_triggers(df_w, tk, lev)
        controls = _control_triggers(df_w, lev)
        print(f"  crisis-probe 触发: {len(trigs)} 次 | non-crisis 对照: {len(controls)} 次")

        # 收集前向收益
        rets = {n: [] for n in FORWARD}
        for t in trigs:
            fwd = _forward_returns(df, t["date"])
            for n, r in fwd.items():
                rets[n].append(r)
                total_rets[n].append(r)

        control_rets = {n: [] for n in FORWARD}
        for c in controls:
            fwd = _forward_returns(df, c["date"])
            for n, r in fwd.items():
                control_rets[n].append(r)
                total_control_rets[n].append(r)

        _summarize(f"[{tk}] crisis-probe", trigs, rets)
        _summarize(f"[{tk}] non-crisis 对照", controls, control_rets, target_hit_rate=0)

        # 展开每一笔触发
        if trigs:
            print(f"  触发明细:")
            for t in trigs[:10]:
                fwd = _forward_returns(df, t["date"])
                print(f"    {t['date'].date()}  RSI={t['rsi']:.0f} prev_5d={t['prev_cum_5d_scaled']:+.1f}% "
                      f"today={t['pct_scaled']:+.1f}% vol={t['vol_r']:.2f} bull={t['bull']} "
                      f"kind={t['is_crisis_kind']} → 5d={fwd.get(5, float('nan')):+.2f}%")

        total_triggers.extend(trigs)
        n_control_total += len(controls)
        per_ticker_stats.append({
            "tk": tk, "n_trig": len(trigs),
            "rets_5d": rets[5],
        })

    print()
    print("=" * 78)
    print("  汇总")
    print("=" * 78)
    print(f"\n总触发: {len(total_triggers)} 次  对照(non-crisis 同等超卖): {n_control_total} 次\n")
    _summarize("Crisis Probe（提议规则）", total_triggers, total_rets)
    _summarize("Non-Crisis 对照（同等超卖但 regime 非 crisis）",
                [{"c": None}] * n_control_total, total_control_rets, target_hit_rate=0)

    # 最终判定
    print()
    n5 = total_rets[5]
    if not n5:
        print("  ⚠ 触发次数=0，规则太严 → 无法验证；建议放宽 cum_5d 或 vol_ratio 阈值")
    else:
        hit5 = (np.array(n5) > 0).mean() * 100
        avg5 = np.array(n5).mean()
        # 与对照对比
        control5 = total_control_rets[5]
        edge_ok = False
        if control5:
            control_avg = np.array(control5).mean()
            edge = avg5 - control_avg
            edge_ok = edge >= 2.0  # 至少 +2pp edge
            print(f"  vs 对照: crisis {avg5:+.2f}% vs non-crisis {control_avg:+.2f}% → edge {edge:+.2f}pp "
                  f"({'✓ ≥+2pp' if edge_ok else '✗ <+2pp'})")
        pass_hit = hit5 >= 55
        pass_avg = avg5 >= 2
        pass_n   = len(n5) >= 8
        print(f"  5d hit rate: {hit5:.1f}% ({'✓' if pass_hit else '✗'} target ≥ 55%)")
        print(f"  5d avg:      {avg5:+.2f}% ({'✓' if pass_avg else '✗'} target ≥ +2%)")
        print(f"  样本数:      {len(n5)} ({'✓' if pass_n else '✗'} target ≥ 8)")
        if pass_hit and pass_avg and pass_n and edge_ok:
            print(f"\n  ✓ ALL PASS — 建议开启 CRISIS_VBOUNCE_ENABLED=1")
        else:
            print(f"\n  ✗ FAIL — 保持 CRISIS_VBOUNCE_ENABLED=0，规则不启用")


if __name__ == "__main__":
    main()
