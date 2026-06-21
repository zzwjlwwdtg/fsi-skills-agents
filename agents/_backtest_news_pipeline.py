"""
新闻管道改造的回测：keyword 法 vs Claude CLI 结构化解析法

测试场景：今日 (2026-06-10 早晨) 5 月 CPI 还未发布（BLS 8:30 ET 才发）。
对每个经济事件 (CPI/PPI/NFP/PCE/FOMC) 跑两种判定路径：

  legacy: events_watch 原 keyword 法（SPY RSS title 含关键词 → 已落地）
  new   : news_analyzer (Claude CLI) 结构化解析 → 看 is_landed=True 且 period 匹配

Ground truth：硬编码——基于现实日期：
  2026-06-09 FOMC = 已发布
  2026-06-10 CPI = 未发布（早晨）
  其它未来事件 = 未发布

输出：每条事件的 (truth, legacy, new, hit_legacy, hit_new) + 精确率/召回率

不退化判据：CLI 法的错误数 ≤ keyword 法的错误数。
"""
from __future__ import annotations
import sys
sys.stdout.reconfigure(line_buffering=True)

from datetime import date, datetime, timedelta


# Ground truth：今日 (2026-06-10) 视角下每个事件是否已落地
GROUND_TRUTH = {
    ("CPI Release",   "2026-05-13"): True,   # 4月CPI已发布
    ("PPI Release",   "2026-05-14"): True,
    ("NFP Release",   "2026-06-05"): True,   # 5月NFP已发布
    ("FOMC Decision", "2026-06-09"): True,   # 昨日已落地
    ("CPI Release",   "2026-06-10"): False,  # **今日，BLS 8:30 ET 才发，凌晨未发布**
    ("PPI Release",   "2026-06-11"): False,
    ("CPI Release",   "2026-07-15"): False,
    ("FOMC Decision", "2026-07-29"): False,
}


def legacy_check(event_name: str, event_date: str) -> bool:
    """复现 keyword 法的"已落地"判断逻辑（events_watch 改前 2 层流程）。"""
    from events_watch import (_check_agency_rss, _check_rss, _check_fred_series,
                              _EVENT_VERIFY)
    from config import FRED_API_KEY

    cfg = _EVENT_VERIFY.get(event_name)
    if not cfg:
        return False
    # 1. BLS / agency RSS（已修月份匹配，但 keyword 法版本只用 keyword + pubDate）
    if _check_agency_rss(cfg["agency_rss"], cfg["agency_kw"], event_date,
                         umbrella=cfg.get("umbrella", False)):
        return True
    # 2. Yahoo SPY RSS keyword（原逻辑：title 含 keyword → 已落地）
    items = _check_rss("SPY")
    joined = " ".join(i["title"] for i in items).lower()
    if any(kw in joined for kw in cfg["yahoo_kw"]):
        return True
    # 3. FRED 兜底
    if FRED_API_KEY and cfg.get("fred_series"):
        if _check_fred_series(cfg["fred_series"], event_date, FRED_API_KEY):
            return True
    return False


def new_check(event_name: str, event_date: str) -> bool:
    """新链路：events_watch._is_event_landed (BLS month + Yahoo CLI + FRED)。"""
    from events_watch import _is_event_landed
    landed, _src = _is_event_landed(event_name, event_date)
    return landed


def main():
    print("="*72)
    print("  新闻管道回测：keyword vs CLI 结构化")
    print(f"  事件数={len(GROUND_TRUTH)}")
    print("="*72)
    print(f"  {'event':<14} {'date':<11} {'truth':<6} {'legacy':<7} {'new':<5}  {'judge'}")
    print("  " + "-"*72)
    legacy_err = 0
    new_err = 0
    legacy_fp = 0   # 假阳：未落地误判已落地
    legacy_fn = 0   # 假阴：已落地漏判未落地
    new_fp = 0
    new_fn = 0
    for (event, dt), truth in GROUND_TRUTH.items():
        try:
            leg = legacy_check(event, dt)
        except Exception as e:
            leg = f"ERR:{e}"
        try:
            new = new_check(event, dt)
        except Exception as e:
            new = f"ERR:{e}"
        leg_ok = (leg == truth)
        new_ok = (new == truth)
        if not leg_ok:
            legacy_err += 1
            if truth is False and leg is True: legacy_fp += 1
            elif truth is True and leg is False: legacy_fn += 1
        if not new_ok:
            new_err += 1
            if truth is False and new is True: new_fp += 1
            elif truth is True and new is False: new_fn += 1
        judge = ""
        if leg_ok and new_ok: judge = "both ok"
        elif new_ok and not leg_ok: judge = "✓ new fixed"
        elif leg_ok and not new_ok: judge = "✗ new regressed"
        else: judge = "× both wrong"
        print(f"  {event:<14} {dt:<11} {str(truth):<6} {str(leg):<7} {str(new):<5}  {judge}")

    print()
    print(f"  legacy errors = {legacy_err}/{len(GROUND_TRUTH)}  (false-pos={legacy_fp}, false-neg={legacy_fn})")
    print(f"  new    errors = {new_err}/{len(GROUND_TRUTH)}  (false-pos={new_fp}, false-neg={new_fn})")
    print()
    if new_err <= legacy_err:
        print(f"  ✓ 不退化（new {new_err} ≤ legacy {legacy_err}）")
    else:
        print(f"  ✗ 退化（new {new_err} > legacy {legacy_err}）—— 需要回滚")


if __name__ == "__main__":
    main()
