from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .models import ExtractedRecommendation
from .opend import verify_with_opend
from .settings import load_creator_weights


_SIDE_MULT = {
    "buy": 1.0,
    "watch": 0.65,
    "sell": -1.0,
    "avoid": -0.8,
}


def enrich_with_opend(recs: list[ExtractedRecommendation], verify_opend: bool = True) -> None:
    if not verify_opend or not recs:
        return
    checks = verify_with_opend(sorted({r.code for r in recs}))
    for rec in recs:
        chk = checks.get(rec.code)
        if not chk:
            continue
        rec.opend_verified = chk.ok
        rec.opend_error = chk.error
        rec.last_price = chk.last_price
        rec.volume = chk.volume
        rec.turnover = chk.turnover


def score_recommendations(recs: list[ExtractedRecommendation]) -> None:
    weights = load_creator_weights()
    for rec in recs:
        creator_w = max(0.2, min(3.0, weights.get(rec.creator, 1.0)))
        side_abs = abs(_SIDE_MULT.get(rec.side, 0.5))
        base = rec.conviction * 10 * creator_w * side_abs
        if rec.opend_verified:
            base += 8
        if rec.risks:
            base -= min(20, 5 * len(rec.risks))
        rec.score = int(max(-100, min(100, round(base))))


def aggregate_by_ticker(recs: list[ExtractedRecommendation]) -> list[dict]:
    grouped: dict[str, list[ExtractedRecommendation]] = defaultdict(list)
    for rec in recs:
        grouped[rec.code].append(rec)

    rows: list[dict] = []
    for code, items in grouped.items():
        signed = 0.0
        creators = set()
        for rec in items:
            creators.add(rec.creator)
            signed += rec.score * (1 if _SIDE_MULT.get(rec.side, 0) >= 0 else -1)
        first = sorted(items, key=lambda r: (r.published_at or "", r.score), reverse=True)[0]
        direction = "bullish" if signed > 20 else "bearish" if signed < -20 else "mixed"
        rows.append({
            "code": code,
            "moomoo_code": first.moomoo_code,
            "yfinance_code": first.yfinance_code,
            "company_name": first.company_name,
            "direction": direction,
            "aggregate_score": int(max(-100, min(100, round(signed)))),
            "mentions": len(items),
            "creators": sorted(creators),
            "opend_verified": any(r.opend_verified for r in items),
            "last_price": first.last_price,
            "turnover": first.turnover,
            "top_evidence": first.evidence,
            "top_source_url": first.source_url,
            "top_creator": first.creator,
            "recommendations": [r.to_dict() for r in sorted(items, key=lambda r: r.score, reverse=True)],
        })
    rows.sort(key=lambda r: (abs(r["aggregate_score"]), r["mentions"]), reverse=True)
    return rows


def build_signal(*, items_count: int, recs: list[ExtractedRecommendation],
                 lookback_hours: int, extraction_status: str,
                 verify_opend: bool) -> dict:
    score_recommendations(recs)
    enriched = aggregate_by_ticker(recs)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": lookback_hours,
        "source_items_count": items_count,
        "recommendation_count": len(recs),
        "tickers": enriched,
        "recommendations": [r.to_dict() for r in sorted(recs, key=lambda r: r.score, reverse=True)],
        "fallback": "fallback" in extraction_status or "not_installed" in extraction_status,
        "extraction_status": extraction_status,
        "opend_checked": verify_opend,
    }
