"""Deterministic facts and calculation contracts for the JP watch dashboard.

Numbers and dates in this module are sourced from issuer IR documents.  A model
may summarize verified facts elsewhere, but it must not create this data layer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo


_SCRIPT_DIR = Path(__file__).resolve().parent
_THESIS_PATH = _SCRIPT_DIR / "theses" / "2026_q3.json"
Q3_MACRO_THESIS = json.loads(_THESIS_PATH.read_text(encoding="utf-8"))

MUFG_IR_URL = "https://www.mufg.jp/english/ir/index.html"
MUFG_FY26_PRESENTATION_URL = (
    "https://www.mufg.jp/dam/ir/presentation/2025/pdf/slides2603_en.pdf"
)


_VERIFIED_JP_GUIDANCE = {
    "MUFG": {
        "ticker": "MUFG",
        "source_stock": "8306.T",
        "fiscal_year": "FY2026",
        "fiscal_year_label": "FY2026（2027/3 期）",
        # MUFG FY2025 IR presentation, published 2026-05-19, page 7.
        "net_income_target_jpy": 2_700_000_000_000,
        "net_income_yoy_pct": 11,
        "net_operating_profit_target_jpy": 2_900_000_000_000,
        "roe_target_pct": 12,
        "direction": "新指引",
        "revision_type": "initial",
        "magnitude": "不适用",
        "guidance_effective_date": "2026-05-15",
        "source_published_at": "2026-05-19",
        # Backward-compatible field: this is the guidance effective date, not
        # the date of the investor presentation used as our source.
        "last_update": "2026-05-15",
        "guidance_note": "FY2026（2027/3 期）纯利润目标 ¥2.7 兆（同比 +11%），净营业利润目标 ¥2.9 兆。",
        "revision_reason": "日元利率上升利润桥约 +¥1,700 亿；贷款利息与手续费等约 +¥1,400 亿。",
        "market_reaction": "待核验",
        "confidence": "verified",
        "source_verified": True,
        "source_status": "verified_official",
        "source_label": "MUFG FY2025 IR Presentation · 2026-05-19",
        "source_url": MUFG_FY26_PRESENTATION_URL,
        "source_pages": [2, 7],
        "assumptions": {
            "boj_policy_rate": "约 1%",
            "ff_rate": "3% 中段",
        },
        "earnings_date": "2026-08-03",
        "earnings_source_label": "MUFG IR · FY2026 Q1 财报日程",
        "earnings_source_url": MUFG_IR_URL,
    }
}


_JP_THESIS_FITS = {
    "MUFG": {
        "thesis_id": "2026-Q3",
        "classification": "independent",
        "compatibility": "mixed",
        "label_zh": "独立 / 混合",
        "is_core_expression": False,
        "automatic_score": 0,
        "manual_review": True,
        "summary": (
            "不是 Q3 Fed 2Y/5Y 交易的核心表达，也没有证据支持仅因美国利率回落就判为主要反 thesis；"
            "MUFG 官方 FY2026 目标假设 FF 利率位于 3% 中段。"
        ),
        "drivers": [
            {
                "factor": "BOJ / 日元利率",
                "weight": "high",
                "alignment": "positive",
                "evidence_type": "company_ir",
                "note": "官方利润桥计入日元利率上升约 +¥1,700 亿。",
            },
            {
                "factor": "Fed / 美元利率",
                "weight": "secondary",
                "alignment": "mixed",
                "evidence_type": "inference_unquantified",
                "note": "公司目标假设 FF 利率位于 3% 中段；未见目标必须依赖美国继续加息的证据。",
            },
            {
                "factor": "日元升值折算",
                "weight": "secondary",
                "alignment": "negative",
                "evidence_type": "company_ir",
                "note": "日元升值会压低海外利润的日元折算值。",
            },
        ],
        "upgrade_gate": "FY2026 Q1 结果确认日本利率收益兑现，且年度指引维持或经官方文件上修。",
        "source_url": MUFG_FY26_PRESENTATION_URL,
    }
}


_OFFICIAL_BANK_FUNDAMENTALS = {
    "MUFG": {
        "ticker": "MUFG",
        "source_stock": "8306.T",
        "fundamental_profile": "bank",
        "as_of": "2026-05-19",
        "source_verified": True,
        "source_label": "MUFG FY2025 IR Presentation · 2026-05-19",
        "source_url": MUFG_FY26_PRESENTATION_URL,
        "metrics": [
            {"key": "net_income_target", "label": "FY2026 纯利目标", "value": "¥2.7T", "context": "+11% YoY"},
            {"key": "net_operating_profit", "label": "FY2026 NOP 目标", "value": "¥2.9T", "context": "+¥522.8B YoY"},
            {"key": "roe", "label": "FY2025 ROE", "value": "11.3%", "context": "FY2026 目标约 12%"},
            {"key": "boj_assumption", "label": "BOJ 假设", "value": "约 1%", "context": "FY2026 公司假设"},
            {"key": "jpy_rate_bridge", "label": "日元加息利润桥", "value": "+¥170B", "context": "税后约数"},
            {"key": "ff_assumption", "label": "FF 利率假设", "value": "3% 中段", "context": "FY2026 目标假设"}
        ],
        "note": "银行专用口径；不使用 CROIC、现金周转周期或工业企业债务阈值。",
    }
}


def jp_earnings_event_state(event_date: str, now: datetime | date | None = None) -> str:
    """Classify an issuer event using the Japan calendar day."""
    tz = ZoneInfo("Asia/Tokyo")
    if now is None:
        current_date = datetime.now(tz).date()
    elif isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=tz)
        current_date = now.astimezone(tz).date()
    else:
        current_date = now
    target = date.fromisoformat(event_date)
    if target > current_date:
        return "upcoming"
    if target == current_date:
        return "today"
    return "released"


def earnings_event_payload(
    event_date: str,
    *,
    now: datetime | date | None = None,
    source_label: str = "",
    source_url: str = "",
) -> dict:
    """Return a display-safe event payload; passed dates are never called next."""
    state = jp_earnings_event_state(event_date, now=now)
    tz = ZoneInfo("Asia/Tokyo")
    if now is None:
        current_date = datetime.now(tz).date()
    elif isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=tz)
        current_date = now.astimezone(tz).date()
    else:
        current_date = now
    days = (date.fromisoformat(event_date) - current_date).days
    return {
        "date": event_date,
        "state": state,
        "days": days,
        "source_verified": bool(source_url),
        "source_label": source_label,
        "source_url": source_url,
    }


def official_jp_guidance(ticker: str, now: datetime | date | None = None) -> dict | None:
    """Return a defensive copy of issuer-verified guidance, if onboarded."""
    payload = _VERIFIED_JP_GUIDANCE.get((ticker or "").upper().strip())
    if payload is None:
        return None
    result = deepcopy(payload)
    event = earnings_event_payload(
        result["earnings_date"],
        now=now,
        source_label=result["earnings_source_label"],
        source_url=result["earnings_source_url"],
    )
    result["earnings_event"] = event
    result["next_earnings"] = event["date"] if event["state"] in {"upcoming", "today"} else None
    source_covers_event = date.fromisoformat(result["source_published_at"]) >= date.fromisoformat(
        result["earnings_date"]
    )
    result["current_verified"] = event["state"] == "upcoming" or source_covers_event
    if not result["current_verified"] and event["state"] == "today":
        result["source_status"] = "awaiting_earnings_update"
    elif not result["current_verified"] and event["state"] == "released":
        result["source_status"] = "awaiting_post_earnings_update"
    if not result["current_verified"] and event["state"] == "today":
        result["data_note"] = "财报日为今天；在当日结果经官方文件核验前，仍展示 2026-05-15 公布的年度目标（来源材料 5/19）。"
    elif not result["current_verified"] and event["state"] == "released":
        result["data_note"] = "财报日已过；在 FY2026 Q1 结果接入并经官方文件核验前，仍展示 2026-05-15 公布的年度目标（来源材料 5/19）。"
    else:
        result["data_note"] = "数字来自已核验的发行人 IR 文件。"
    return result


def jp_thesis_fit(ticker: str) -> dict | None:
    payload = _JP_THESIS_FITS.get((ticker or "").upper().strip())
    return deepcopy(payload) if payload else None


def official_bank_fundamentals(ticker: str) -> dict | None:
    payload = _OFFICIAL_BANK_FUNDAMENTALS.get((ticker or "").upper().strip())
    return deepcopy(payload) if payload else None


def compute_ichimoku_series(high, low, close=None, displacement: int = 26) -> dict:
    """Compute standard Ichimoku series with Senkou spans shifted 26 periods."""
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(displacement)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(displacement)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
    }


def classify_ichimoku_position(price: float, senkou_a: float, senkou_b: float) -> tuple[str, str]:
    """Classify price against the cloud already aligned to the same x-coordinate."""
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    if price > cloud_top:
        return "云上", "bullish"
    if price < cloud_bottom:
        return "云下", "bearish"
    return "云中", "neutral"
