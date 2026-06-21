from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ContentItem:
    source_type: str
    creator: str
    item_id: str
    text: str
    published_at: str = ""
    url: str = ""
    title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "creator": self.creator,
            "item_id": self.item_id,
            "text": self.text,
            "published_at": self.published_at,
            "url": self.url,
            "title": self.title,
            "meta": self.meta,
        }


@dataclass
class ExtractedRecommendation:
    code: str
    company_name: str
    side: str
    conviction: int
    horizon: str
    thesis: str
    risks: list[str]
    evidence: str
    creator: str
    source_type: str
    source_url: str = ""
    published_at: str = ""
    item_id: str = ""
    extraction_method: str = "fallback"
    opend_verified: bool = False
    opend_error: str = ""
    last_price: float | None = None
    volume: float | None = None
    turnover: float | None = None
    score: int = 0

    @property
    def moomoo_code(self) -> str:
        return f"JP.{self.code}"

    @property
    def yfinance_code(self) -> str:
        return f"{self.code}.T"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "moomoo_code": self.moomoo_code,
            "yfinance_code": self.yfinance_code,
            "company_name": self.company_name,
            "side": self.side,
            "conviction": self.conviction,
            "horizon": self.horizon,
            "thesis": self.thesis,
            "risks": self.risks,
            "evidence": self.evidence,
            "creator": self.creator,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "item_id": self.item_id,
            "extraction_method": self.extraction_method,
            "opend_verified": self.opend_verified,
            "opend_error": self.opend_error,
            "last_price": self.last_price,
            "volume": self.volume,
            "turnover": self.turnover,
            "score": self.score,
        }
