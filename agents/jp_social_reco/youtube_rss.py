from __future__ import annotations

import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .models import ContentItem
from .settings import INBOX_DIR, ensure_dirs, load_source_config

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_YT = "{http://www.youtube.com/xml/schemas/2015}"


def _get_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _extract_rss_url(channel_url: str) -> tuple[str, str]:
    """Return (rss_url, channel_id)."""
    page_url = channel_url.rstrip("/") + "/videos"
    text = _get_text(page_url)
    text = html.unescape(text)

    m = re.search(r'"rssUrl":"([^"]+)"', text)
    if m:
        rss = m.group(1).replace("\\u0026", "&")
        channel_id = ""
        cm = re.search(r"channel_id=(UC[0-9A-Za-z_-]+)", rss)
        if cm:
            channel_id = cm.group(1)
        return rss, channel_id

    for pat in (r'"externalId":"(UC[0-9A-Za-z_-]{20,})"', r'"browseId":"(UC[0-9A-Za-z_-]{20,})"'):
        m = re.search(pat, text)
        if m:
            channel_id = m.group(1)
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", channel_id
    raise ValueError(f"channel_id_not_found: {channel_url}")


def _entry_text(entry: ET.Element, tag: str) -> str:
    el = entry.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _parse_feed(feed_text: str, *, creator: str, channel_url: str, max_items: int) -> list[ContentItem]:
    root = ET.fromstring(feed_text)
    out: list[ContentItem] = []
    for entry in root.findall(f"{_ATOM}entry")[:max_items]:
        video_id = _entry_text(entry, f"{_YT}videoId")
        title = _entry_text(entry, f"{_ATOM}title")
        published = _entry_text(entry, f"{_ATOM}published")
        link = ""
        link_el = entry.find(f"{_ATOM}link")
        if link_el is not None:
            link = link_el.attrib.get("href", "")
        desc = ""
        group = entry.find(f"{_MEDIA}group")
        if group is not None:
            desc = _entry_text(group, f"{_MEDIA}description")
        text = "\n".join(part for part in [title, desc] if part).strip()
        if not text:
            continue
        out.append(ContentItem(
            source_type="youtube_rss",
            creator=creator,
            item_id=video_id or link or f"{creator}-{len(out)}",
            title=title,
            text=text,
            published_at=published,
            url=link,
            meta={"channel_url": channel_url},
        ))
    return out


def fetch_youtube_rss_items(max_items_per_channel: int = 5) -> tuple[list[ContentItem], list[str]]:
    cfg = load_source_config()
    items: list[ContentItem] = []
    errors: list[str] = []
    for src in cfg.get("sources", []):
        if src.get("enabled", True) is False or src.get("kind") != "youtube":
            continue
        creator = str(src.get("creator") or "").strip()
        url = str(src.get("url") or "").strip()
        if not creator or not url:
            continue
        try:
            rss_url, channel_id = _extract_rss_url(url)
            feed_text = _get_text(rss_url)
            batch = _parse_feed(feed_text, creator=creator, channel_url=url,
                                max_items=max_items_per_channel)
            for item in batch:
                item.meta["rss_url"] = rss_url
                item.meta["channel_id"] = channel_id
            items.extend(batch)
        except Exception as exc:
            errors.append(f"{creator}: {exc}")
    return items, errors


def write_items_to_inbox(items: list[ContentItem]) -> Path:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = INBOX_DIR / f"youtube_rss_{stamp}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    return path


def fetch_youtube_rss_to_inbox(max_items_per_channel: int = 5) -> tuple[Path | None, int, list[str]]:
    items, errors = fetch_youtube_rss_items(max_items_per_channel=max_items_per_channel)
    if not items:
        return None, 0, errors
    path = write_items_to_inbox(items)
    return path, len(items), errors
