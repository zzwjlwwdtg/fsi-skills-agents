from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import ContentItem
from .settings import INBOX_DIR, ensure_dirs


def _stable_id(parts: Iterable[str]) -> str:
    text = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fresh_enough(item: ContentItem, lookback_hours: int) -> bool:
    if not item.published_at:
        return True
    dt = _parse_dt(item.published_at)
    if not dt:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    return dt >= cutoff


def _item_from_dict(raw: dict, *, fallback_creator: str, fallback_source: str) -> ContentItem | None:
    text = (raw.get("text") or raw.get("content") or raw.get("transcript") or raw.get("tweet") or "").strip()
    if not text:
        return None
    creator = str(raw.get("creator") or raw.get("author") or fallback_creator).strip() or "unknown"
    source_type = str(raw.get("source_type") or raw.get("kind") or fallback_source).strip() or "manual"
    item_id = str(raw.get("item_id") or raw.get("id") or "").strip()
    url = str(raw.get("url") or raw.get("source_url") or "").strip()
    title = str(raw.get("title") or "").strip()
    published_at = str(raw.get("published_at") or raw.get("created_at") or raw.get("date") or "").strip()
    if not item_id:
        item_id = _stable_id([creator, source_type, published_at, url, text[:120]])
    return ContentItem(
        source_type=source_type,
        creator=creator,
        item_id=item_id,
        text=text,
        published_at=published_at,
        url=url,
        title=title,
        meta={k: v for k, v in raw.items() if k not in {
            "text", "content", "transcript", "tweet", "creator", "author",
            "source_type", "kind", "item_id", "id", "url", "source_url",
            "title", "published_at", "created_at", "date",
        }},
    )


def _read_jsonl(path: Path) -> list[ContentItem]:
    out: list[ContentItem] = []
    fallback_source = path.stem.split("_", 1)[0] or "manual"
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except Exception:
            continue
        if isinstance(raw, dict):
            item = _item_from_dict(raw, fallback_creator=path.stem, fallback_source=fallback_source)
            if item:
                out.append(item)
    return out


def _read_json(path: Path) -> list[ContentItem]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    rows = raw if isinstance(raw, list) else raw.get("items", []) if isinstance(raw, dict) else []
    out = []
    for row in rows:
        if isinstance(row, dict):
            item = _item_from_dict(row, fallback_creator=path.stem, fallback_source="manual")
            if item:
                out.append(item)
    return out


def _read_csv(path: Path) -> list[ContentItem]:
    out: list[ContentItem] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            item = _item_from_dict(raw, fallback_creator=path.stem, fallback_source="manual_csv")
            if item:
                out.append(item)
    return out


def _read_text(path: Path) -> list[ContentItem]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    creator, item_id = _creator_item_from_stem(path.stem)
    return [ContentItem(
        source_type="manual_text",
        creator=creator,
        item_id=item_id or _stable_id([path.name, text[:200]]),
        text=text,
        title=path.name,
        meta={"path": str(path)},
    )]


def _creator_item_from_stem(stem: str) -> tuple[str, str]:
    """Parse filenames like creator__videoid.srt into source metadata."""
    if "__" in stem:
        creator, item_id = stem.split("__", 1)
        return creator.strip() or stem, item_id.strip()
    return stem, ""


def _read_subtitle(path: Path) -> list[ContentItem]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    last = ""
    for line in raw.splitlines():
        s = line.strip().lstrip("\ufeff")
        if not s:
            continue
        if s.upper() == "WEBVTT" or s.upper().startswith("NOTE"):
            continue
        if s.startswith("Kind:") or s.startswith("Language:"):
            continue
        if s.isdigit():
            continue
        if "-->" in s:
            continue
        # Remove simple WebVTT/SRT cue markup.
        s = re.sub(r"<[^>]+>", "", s)
        if s and s != last:
            lines.append(s)
            last = s
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    text = _dedupe_repeated_phrases(text)
    if not text:
        return []
    creator, item_id = _creator_item_from_stem(path.stem)
    return [ContentItem(
        source_type="subtitle_file",
        creator=creator,
        item_id=item_id or _stable_id([path.name, text[:200]]),
        text=text,
        title=path.name,
        meta={"path": str(path), "subtitle_format": path.suffix.lower().lstrip(".")},
    )]


def _dedupe_repeated_phrases(text: str, max_phrase_chars: int = 80) -> str:
    """Collapse immediate duplicate subtitle fragments produced by auto-captions."""
    if not text:
        return text
    parts = re.split(r"(?<=[。.!?！？])\s+|\s{2,}", text)
    out: list[str] = []
    last = ""
    for part in parts:
        p = part.strip()
        if not p:
            continue
        if p == last:
            continue
        # Sometimes VTT repeats the same short phrase 3 times before punctuation.
        if len(p) <= max_phrase_chars and out and p in out[-1]:
            continue
        out.append(p)
        last = p
    return " ".join(out)


def collect_inbox_items(lookback_hours: int = 72, max_items: int = 80) -> list[ContentItem]:
    """Read user-supplied X exports, video transcripts, or manual notes.

    Supported files under data/inbox:
    - .jsonl: one object per line
    - .json: {"items":[...]} or a plain list
    - .csv: columns such as creator, source_type, text, published_at, url
    - .txt/.md: one whole file as one item
    - .srt/.vtt: subtitle files, including files downloaded from DownSub
    """
    ensure_dirs()
    items: list[ContentItem] = []
    readers = {
        ".jsonl": _read_jsonl,
        ".json": _read_json,
        ".csv": _read_csv,
        ".txt": _read_text,
        ".md": _read_text,
        ".srt": _read_subtitle,
        ".vtt": _read_subtitle,
    }
    for path in sorted(INBOX_DIR.glob("*")):
        if not path.is_file():
            continue
        reader = readers.get(path.suffix.lower())
        if not reader:
            continue
        try:
            items.extend(reader(path))
        except Exception:
            continue

    filtered = [it for it in items if _fresh_enough(it, lookback_hours)]
    filtered.sort(key=lambda it: it.published_at or "", reverse=True)
    return filtered[:max_items]


def cleanup_inbox_items(lookback_hours: int = 168) -> dict:
    """Remove downloaded inbox files whose dated items are older than lookback.

    Files without parseable dates are kept to avoid deleting manual notes.
    Mixed-date files are kept; collection still filters old rows at read time.
    """
    ensure_dirs()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    readers = {
        ".jsonl": _read_jsonl,
        ".json": _read_json,
        ".csv": _read_csv,
        ".txt": _read_text,
        ".md": _read_text,
        ".srt": _read_subtitle,
        ".vtt": _read_subtitle,
    }
    removed: list[str] = []
    kept: list[str] = []
    errors: list[str] = []
    for path in sorted(INBOX_DIR.glob("*")):
        if not path.is_file():
            continue
        reader = readers.get(path.suffix.lower())
        if not reader:
            kept.append(path.name)
            continue
        try:
            items = reader(path)
            dates = []
            for it in items:
                dt = _parse_dt(it.published_at)
                if dt:
                    dates.append(_to_aware_utc(dt))
            if dates and max(dates) < cutoff:
                path.unlink()
                removed.append(path.name)
            else:
                kept.append(path.name)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
            kept.append(path.name)
    return {"removed": removed, "kept": kept, "errors": errors, "cutoff": cutoff.isoformat()}
