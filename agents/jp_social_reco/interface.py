from __future__ import annotations

import json
from datetime import datetime

from .aggregator import build_signal, enrich_with_opend
from .extractor import extract_recommendations
from .settings import (
    CACHE_PATH,
    CACHE_TTL_MIN,
    DEFAULT_LOOKBACK_HOURS,
    INBOX_DIR,
    INTERFACE_VERSION,
    ensure_dirs,
)
from .sources import collect_inbox_items


def _cache_fresh(max_age_min: int) -> bool:
    if not CACHE_PATH.exists():
        return False
    cache_mtime = CACHE_PATH.stat().st_mtime
    try:
        newest_input = max(
            (p.stat().st_mtime for p in INBOX_DIR.glob("*") if p.is_file()),
            default=0,
        )
        if newest_input > cache_mtime:
            return False
    except Exception:
        pass
    age_min = (datetime.now().timestamp() - CACHE_PATH.stat().st_mtime) / 60
    return age_min <= max_age_min


def get_jp_social_signal(*, lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
                         max_items: int = 80,
                         use_llm: bool = True,
                         verify_opend: bool = True,
                         min_abs_score: int = 0) -> dict:
    """Main framework interface.

    Returns a JSON-serializable dict. It never raises for missing OpenD/LLM;
    errors are surfaced in extraction_status and per-recommendation opend_error.
    """
    ensure_dirs()
    items = collect_inbox_items(lookback_hours=lookback_hours, max_items=max_items)
    recs, status = extract_recommendations(items, use_llm=use_llm)
    enrich_with_opend(recs, verify_opend=verify_opend)
    if min_abs_score:
        # Score once before filtering so callers can suppress weak social noise.
        from .aggregator import score_recommendations
        score_recommendations(recs)
        recs = [r for r in recs if abs(r.score) >= min_abs_score]
    sig = build_signal(
        items_count=len(items),
        recs=recs,
        lookback_hours=lookback_hours,
        extraction_status=status,
        verify_opend=verify_opend,
    )
    sig["interface_version"] = INTERFACE_VERSION
    try:
        CACHE_PATH.write_text(json.dumps(sig, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return sig


def get_jp_social_signal_cached(*, lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
                                max_age_min: int = CACHE_TTL_MIN,
                                **kwargs) -> dict:
    """Cached framework interface, similar to trump_signal.get_trump_signal_cached."""
    ensure_dirs()
    if _cache_fresh(max_age_min):
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return get_jp_social_signal(lookback_hours=lookback_hours, **kwargs)


def get_jp_social_with_backtest(*, lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
                                  max_age_min: int = CACHE_TTL_MIN,
                                  attach_backtest: bool = True,
                                  **kwargs) -> dict:
    """信号 + yfinance 回测一站式。在 cached 信号上附加：
    - `creator_accuracy`: 每个 creator 历史胜率（1d/3d/5d/20d/60d）
    - `tickers[i].backtest`: 该 ticker 推荐后的 price_check 结果（按 horizon）

    主框架（snap.bat / orchestrator）可直接消费。yfinance 不可用时不阻塞，
    缺失字段为空。
    """
    sig = get_jp_social_signal_cached(
        lookback_hours=lookback_hours, max_age_min=max_age_min, **kwargs)
    if not attach_backtest:
        return sig
    if not sig.get("recommendations"):
        sig["creator_accuracy"] = []
        return sig
    try:
        from .backtest import (price_moves_for_recommendations,
                                summarize_creator_accuracy, _rec_key)
        # price_moves_for_recommendations 返回 dict[rec_key → enriched_move_dict]
        # 需要把每个原 rec 附加 price_check 字段，sig["recommendations"] 仍是 list
        recs_list = sig.get("recommendations") or []
        price_checks = price_moves_for_recommendations(recs_list)
        # 给每个 rec 加 price_check 字段
        for idx, rec in enumerate(recs_list):
            key = _rec_key(idx, rec)
            if key in price_checks:
                rec["price_check"] = price_checks[key]
        # 同步给 ticker.recommendations 加 price_check（通过 creator+code+date 匹配）
        rec_lookup = {}
        for r in recs_list:
            k = (r.get("creator", ""), r.get("code", ""),
                 (r.get("published_at") or "")[:10])
            rec_lookup[k] = r.get("price_check")
        for tk in sig.get("tickers") or []:
            for r in tk.get("recommendations") or []:
                k = (r.get("creator", ""), r.get("code", ""),
                     (r.get("published_at") or "")[:10])
                if k in rec_lookup:
                    r["price_check"] = rec_lookup[k]
            # ticker 级别聚合 horizon_hit（哪个周期最多成功）
            horizon_hits = {"1d": 0, "3d": 0, "5d": 0, "20d": 0, "60d": 0}
            horizon_total = {"1d": 0, "3d": 0, "5d": 0, "20d": 0, "60d": 0}
            for r in tk.get("recommendations") or []:
                chk = r.get("price_check") or {}
                for h, info in (chk.get("horizons") or {}).items():
                    if h in horizon_hits:
                        outcome = info.get("outcome", "pending")
                        horizon_total[h] += 1
                        if outcome == "success":
                            horizon_hits[h] += 1
            tk["horizon_hit"] = {h: [horizon_hits[h], horizon_total[h]]
                                  for h in horizon_hits}
        # summarize_creator_accuracy 返回 {rule, horizons, creators:[...]}, 取 creators list
        acc_full = summarize_creator_accuracy(recs_list)
        sig["creator_accuracy"] = acc_full.get("creators", []) if isinstance(acc_full, dict) else acc_full
    except Exception as exc:
        sig["backtest_error"] = str(exc)
        sig["creator_accuracy"] = []
    return sig


def generate_jp_social_weekly_report(*,
                                     lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
                                     max_items: int = 80,
                                     use_llm: bool = True,
                                     verify_opend: bool = True,
                                     fresh: bool = True,
                                     report_use_llm: bool = True,
                                     report_llm_timeout: int = 420,
                                     include_backtest: bool = True,
                                     output_dir: str | None = None,
                                     write_pdf: bool = True,
                                     write_md: bool = True) -> dict:
    """Framework interface for a one-week creator report.

    Returns paths for Markdown/PDF plus the signal and report generation status.
    """
    if fresh:
        sig = get_jp_social_signal(
            lookback_hours=lookback_hours,
            max_items=max_items,
            use_llm=use_llm,
            verify_opend=verify_opend,
        )
    else:
        sig = get_jp_social_signal_cached(
            lookback_hours=lookback_hours,
            max_items=max_items,
            use_llm=use_llm,
            verify_opend=verify_opend,
        )
    from .weekly_report import write_weekly_report
    report = write_weekly_report(
        sig=sig,
        lookback_hours=lookback_hours,
        max_items=max_items,
        output_dir=output_dir,
        use_llm=report_use_llm,
        llm_timeout=report_llm_timeout,
        include_backtest=include_backtest,
        write_pdf=write_pdf,
        write_md=write_md,
    )
    report["signal_path"] = str(CACHE_PATH)
    report["extraction_status"] = sig.get("extraction_status", "")
    report["opend_checked"] = sig.get("opend_checked", False)
    return report


def format_jp_social_banner(sig: dict) -> list[str]:
    """简版 banner（兼容老调用方）。新代码推荐用 format_jp_social_banner_enhanced。"""
    W = 86
    lines = [
        "+" + "=" * (W - 2) + "+",
        f"|  JP Social Reco  |  {sig.get('ts', '')[:16]}  lookback={sig.get('lookback_hours')}h".ljust(W - 1) + "|",
        "+" + "=" * (W - 2) + "+",
    ]
    lines.append(
        f"  source_items={sig.get('source_items_count', 0)}  "
        f"recs={sig.get('recommendation_count', 0)}  "
        f"status={sig.get('extraction_status', '')}"
    )
    if not sig.get("tickers"):
        lines.append("  (no actionable JP stock recommendation found)")
        lines.append("=" * W)
        return lines
    lines.append(f"  {'code':<8} {'name':<16} {'dir':<8} {'score':>6} {'mentions':>8} {'OpenD':>7}  creators")
    lines.append(f"  {'-'*8} {'-'*16} {'-'*8} {'-'*6} {'-'*8} {'-'*7}  {'-'*20}")
    for row in sig.get("tickers", [])[:12]:
        ok = "ok" if row.get("opend_verified") else "-"
        creators = ",".join(row.get("creators", [])[:3])
        lines.append(
            f"  {row.get('moomoo_code',''):<8} {row.get('company_name','')[:16]:<16} "
            f"{row.get('direction',''):<8} {row.get('aggregate_score',0):>+6} "
            f"{row.get('mentions',0):>8} {ok:>7}  {creators}"
        )
        ev = (row.get("top_evidence") or "").replace("\n", " ")[:100]
        if ev:
            lines.append(f"      evidence: {ev}")
    lines.append("=" * W)
    return lines


def _star_rating(mentions: int, n_creators: int) -> str:
    """根据推荐次数 + 涉及创作者数算星标。
       ★★★★★：≥3 创作者 OR ≥5 mentions（强烈共识）
       ★★★★：2 创作者 + ≥3 mentions
       ★★★：2 创作者 OR ≥3 mentions（多人/多次提及）
       ★★：≥2 mentions
       ★：1 mention
    """
    if n_creators >= 3 or mentions >= 5:
        return "★★★★★"
    if n_creators >= 2 and mentions >= 3:
        return "★★★★"
    if n_creators >= 2 or mentions >= 3:
        return "★★★"
    if mentions >= 2:
        return "★★"
    return "★"


def _creator_acc_lookup(creator_accuracy: list[dict], creator: str) -> dict:
    for row in creator_accuracy or []:
        if row.get("creator") == creator:
            return row
    return {}


def _creator_winrate_str(acc_row: dict) -> str:
    """从 summarize_creator_accuracy 行里取最佳/总体胜率。"""
    if not acc_row:
        return ""
    overall = acc_row.get("overall", {})
    if overall.get("judged"):
        rate = overall.get("accuracy_pct")
        return f"overall {overall['n_over_m']} ({rate}%)" if rate is not None else ""
    return ""


def format_jp_social_banner_enhanced(sig: dict) -> list[str]:
    """增强版 banner（含星标 / thesis / 创作者胜率 / 按 horizon 回测）。"""
    W = 92
    lines = [
        "+" + "=" * (W - 2) + "+",
        f"|  JP Social Reco — 博主推荐  |  {sig.get('ts', '')[:16]}  lookback={sig.get('lookback_hours')}h".ljust(W - 1) + "|",
        "+" + "=" * (W - 2) + "+",
    ]
    lines.append(
        f"  source_items={sig.get('source_items_count', 0)}  "
        f"recs={sig.get('recommendation_count', 0)}  "
        f"status={sig.get('extraction_status', '')}"
    )

    # 创作者胜率摘要（按 overall hit 排序）
    creator_acc = sig.get("creator_accuracy") or []
    if creator_acc:
        ranked = sorted(creator_acc,
                        key=lambda x: (x.get("overall", {}).get("accuracy_pct") or 0,
                                       x.get("total_opinions") or 0),
                        reverse=True)
        lines.append("")
        lines.append("  ── 博主历史胜率（yfinance 回测） ──")
        for row in ranked[:8]:
            ov = row.get("overall", {})
            horizons = row.get("horizons", {})
            best_h = ""
            best_rate = -1
            for h_key in ("1d", "3d", "5d", "20d", "60d"):
                hr = horizons.get(h_key, {})
                rate = hr.get("accuracy_pct")
                if rate is not None and rate > best_rate and hr.get("judged", 0) >= 2:
                    best_rate = rate
                    best_h = f"{h_key} {hr['n_over_m']}={rate}%"
            overall_str = (f"{ov.get('n_over_m', '0/0')}={ov.get('accuracy_pct', 0)}%"
                           if ov.get('accuracy_pct') is not None else "n/a")
            lines.append(
                f"    {row.get('creator', '?'):<18} 总判 {row.get('total_opinions', 0):>3}"
                f"  总体 {overall_str:<14}  最佳 {best_h}"
            )

    if not sig.get("tickers"):
        lines.append("")
        lines.append("  (本期暂无可执行的 JP 股推荐)")
        lines.append("=" * W)
        return lines

    # 推荐标的（按 mentions + score 排序，含星标 + thesis + 胜率）
    lines.append("")
    lines.append("  ── 推荐标的（按推荐力度排） ──")
    for row in sig.get("tickers", [])[:10]:
        mentions = row.get("mentions", 0)
        creators_list = row.get("creators", [])
        n_creators = len(creators_list)
        star = _star_rating(mentions, n_creators)
        dir_arrow = {"bullish": "▲", "bearish": "▼", "mixed": "·"}.get(
            row.get("direction"), "·")
        opend_tag = "✓OpenD" if row.get("opend_verified") else "(未验证)"
        last_p = row.get("last_price")
        price_tag = f"¥{last_p:.0f}" if last_p else ""
        lines.append("")
        lines.append(
            f"  {star:<6} {dir_arrow} {row.get('moomoo_code', ''):<8} "
            f"{row.get('company_name', '')[:18]:<18} "
            f"{row.get('direction', ''):<8} score {row.get('aggregate_score', 0):>+4}  "
            f"提及 {mentions}× / {n_creators}人  {opend_tag}  {price_tag}"
        )
        # 创作者列表 + 各自胜率
        for c in creators_list[:5]:
            acc_row = _creator_acc_lookup(creator_acc, c)
            wr = _creator_winrate_str(acc_row)
            lines.append(f"      · {c}" + (f"  [{wr}]" if wr else ""))
        # 看好/看空逻辑（thesis）— 取最高 score 的 rec 的 thesis
        recs = row.get("recommendations") or []
        if recs:
            top = recs[0]
            thesis = (top.get("thesis") or top.get("evidence") or "").replace("\n", " ").strip()
            if thesis:
                lines.append(f"      逻辑: {thesis[:140]}")
            risks = top.get("risks") or []
            if risks:
                risk_str = " / ".join(r[:30] for r in risks[:3])
                lines.append(f"      风险: {risk_str}")
            horizon = top.get("horizon")
            if horizon:
                lines.append(f"      时间维度: {horizon}")
        # 该 ticker 在各 horizon 的回测 hit
        hh = row.get("horizon_hit") or {}
        hit_strs = []
        for h in ("1d", "3d", "5d", "20d", "60d"):
            hit, tot = hh.get(h, (0, 0))
            if tot > 0:
                hit_strs.append(f"{h}={hit}/{tot}")
        if hit_strs:
            lines.append(f"      回测命中: {' | '.join(hit_strs)}")

    if sig.get("fallback"):
        lines.append("")
        lines.append("  ⚠ extraction fallback（LLM 不可用或失败），结果可能不完整")
    lines.append("=" * W)
    return lines
