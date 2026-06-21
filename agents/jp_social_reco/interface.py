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
    recs = sig.get("recommendations") or []
    if recs:
        lines.append("")
        lines.append("  Source detail:")
        for rec in recs[:20]:
            day = (rec.get("published_at") or "")[:10] or "unknown-date"
            creator = rec.get("creator") or "unknown"
            code = rec.get("moomoo_code") or f"JP.{rec.get('code', '')}"
            name = rec.get("company_name") or rec.get("code", "")
            side = rec.get("side") or "analysis"
            ev = (rec.get("evidence") or rec.get("thesis") or "").replace("\n", " ")[:90]
            lines.append(f"    {day}  {creator} analyzed {code} {name}  side={side}")
            if ev:
                lines.append(f"        {ev}")
    lines.append("=" * W)
    return lines
