from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import ContentItem
from .settings import INBOX_DIR, ensure_dirs
from .sources import _read_subtitle
from .youtube_rss import fetch_youtube_rss_items

_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([0-9A-Za-z_-]{11})")
_LANG_PREF = "ja,zh-Hans,zh-Hant,zh,en.*,en"
_QUALITY_MODEL = {
    "fast": "tiny",
    "balanced": "small",
    "high": "medium",
}


def extract_video_id(url: str) -> str:
    m = _VIDEO_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", value or "youtube")


def subtitle_inbox_path(creator: str, video_id: str) -> Path:
    ensure_dirs()
    return INBOX_DIR / f"{_safe_name(creator)}__{_safe_name(video_id)}.jsonl"


def _cookies_args(cookies_from_browser: str = "") -> list[str]:
    browser = (cookies_from_browser or "").strip()
    if not browser:
        return []
    return ["--cookies-from-browser", browser]


def list_available_subtitles(url: str, *, cookies_from_browser: str = "",
                             timeout: int = 60) -> tuple[str, str]:
    """Return yt-dlp --list-subs output for diagnostics."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download",
        "--list-subs",
        "--no-warnings",
        *_cookies_args(cookies_from_browser),
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", f"list_subs_timeout: >{timeout}s"
    out = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return out, f"list_subs_failed: {out[:500]}"
    return out, "ok"


def _run_ytdlp_for_subtitles(url: str, out_dir: Path, *, langs: str = _LANG_PREF,
                             timeout: int = 120,
                             cookies_from_browser: str = "") -> tuple[list[Path], str]:
    """Use yt-dlp to download existing or auto-generated subtitles only."""
    statuses: list[str] = []
    lang_list = [x.strip() for x in langs.split(",") if x.strip()]
    if not lang_list:
        lang_list = ["ja", "zh-Hans", "zh-Hant", "zh", "en"]

    for lang in lang_list:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", lang,
            "--sub-format", "vtt/srt/best",
            "--no-warnings",
            "--restrict-filenames",
            *_cookies_args(cookies_from_browser),
            "-o", str(out_dir / "%(id)s.%(ext)s"),
            url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            statuses.append(f"{lang}:timeout")
            continue

        subs_now = sorted(
            [p for p in out_dir.glob("*") if p.suffix.lower() in (".vtt", ".srt")],
            key=lambda p: (0 if f".{lang.lower()}." in p.name.lower() else 1, p.name),
        )
        if subs_now:
            return subs_now, f"ok:{lang}"

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            statuses.append(f"{lang}:{err[:120]}")
        else:
            statuses.append(f"{lang}:no_subs")

    subs = sorted(
        [p for p in out_dir.glob("*") if p.suffix.lower() in (".vtt", ".srt")],
        key=lambda p: (0 if ".ja" in p.name.lower() else 1, p.name),
    )
    if not subs:
        return [], "no_subtitles_downloaded: " + " | ".join(statuses)[:600]
    return subs, "ok"


def _load_info_json(url: str, timeout: int = 60, cookies_from_browser: str = "") -> dict:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json", "--skip-download", "--no-warnings",
        *_cookies_args(cookies_from_browser),
        url,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout.splitlines()[-1])
    except Exception:
        return {}


def _download_audio(url: str, out_dir: Path, *, timeout: int = 180,
                    cookies_from_browser: str = "") -> tuple[Path | None, str]:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio/best",
        "--no-playlist",
        "--no-warnings",
        "--restrict-filenames",
        *_cookies_args(cookies_from_browser),
        "-o", str(out_dir / "%(id)s.%(ext)s"),
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"audio_download_timeout: >{timeout}s"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
        return None, f"audio_download_failed: {err[:500]}"
    audio_files = sorted(
        [p for p in out_dir.glob("*") if p.suffix.lower() not in (".vtt", ".srt", ".json")],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not audio_files:
        return None, "audio_download_failed: no audio file"
    return audio_files[0], "ok"


def _lang_hint(langs: str, force_language: str = "") -> str | None:
    if force_language:
        return force_language
    for lang in [x.strip() for x in (langs or "").split(",") if x.strip()]:
        base = lang.split("-", 1)[0].replace(".*", "")
        if base in {"ja", "zh", "en"}:
            return base
    return None


def _transcribe_audio(audio_path: Path, *, langs: str = _LANG_PREF,
                      model_size: str = "small",
                      force_language: str = "") -> tuple[str, str]:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        return "", f"whisper_missing: {exc}"
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(
            str(audio_path),
            language=_lang_hint(langs, force_language),
            vad_filter=True,
            beam_size=5,
            best_of=5,
            condition_on_previous_text=True,
        )
        text_parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        text = " ".join(text_parts)
        text = re.sub(r"\s+", " ", text).strip()
        lang = getattr(info, "language", "") or ""
        return text, f"ok:whisper:{model_size}:{lang}"
    except Exception as exc:
        return "", f"whisper_failed: {exc}"


def fetch_video_subtitle_item(url: str, *, creator: str = "", timeout: int = 120,
                              langs: str = _LANG_PREF,
                              cookies_from_browser: str = "",
                              whisper_fallback: bool = False,
                              whisper_model: str = "",
                              whisper_language: str = "",
                              quality: str = "balanced") -> tuple[ContentItem | None, str]:
    """Download subtitles for one YouTube URL and return one ContentItem.

    Fast path uses YouTube captions. Optional fallback downloads audio and runs
    local faster-whisper when captions are unavailable.
    """
    video_id = extract_video_id(url)
    with tempfile.TemporaryDirectory(prefix="jp_social_subs_") as td:
        tmp = Path(td)
        subs, status = _run_ytdlp_for_subtitles(
            url, tmp, langs=langs, timeout=timeout,
            cookies_from_browser=cookies_from_browser,
        )
        info = _load_info_json(url, cookies_from_browser=cookies_from_browser)
        title = info.get("title") or ""
        uploader = info.get("uploader_id") or info.get("channel_id") or info.get("uploader") or ""
        published = info.get("upload_date") or ""
        if published and re.match(r"^\d{8}$", str(published)):
            published = f"{published[:4]}-{published[4:6]}-{published[6:8]}T00:00:00Z"
        if not subs:
            if not whisper_fallback:
                return None, status
            audio_path, audio_status = _download_audio(
                url, tmp, timeout=max(timeout, 180),
                cookies_from_browser=cookies_from_browser,
            )
            if not audio_path:
                return None, f"{status}; {audio_status}"
            model_size = whisper_model or _QUALITY_MODEL.get(quality, "small")
            text, whisper_status = _transcribe_audio(
                audio_path,
                langs=langs,
                model_size=model_size,
                force_language=whisper_language,
            )
            if not text:
                return None, f"{status}; {audio_status}; {whisper_status}"
            item = ContentItem(
                source_type="youtube_whisper",
                creator=creator or uploader or "youtube",
                item_id=video_id or audio_path.stem,
                text=text,
                published_at=published,
                url=url,
                title=title,
                meta={
                    "subtitle_status": status,
                    "audio_status": audio_status,
                    "whisper_status": whisper_status,
                    "audio_file": audio_path.name,
                    "uploader": uploader,
                },
            )
            return item, "ok"
        chosen = subs[0]
        parsed = _read_subtitle(chosen)
        if not parsed:
            return None, f"subtitle_parse_failed: {chosen.name}"
        item = parsed[0]
        item.creator = creator or uploader or item.creator
        item.source_type = "youtube_subtitle"
        item.item_id = video_id or item.item_id
        item.url = url
        item.title = title or item.title
        item.published_at = published or item.published_at
        item.meta.update({
            "subtitle_file": chosen.name,
            "subtitle_status": status,
            "uploader": uploader,
        })
        return item, "ok"


def write_subtitle_item_to_inbox(item: ContentItem) -> Path:
    ensure_dirs()
    path = subtitle_inbox_path(item.creator or "youtube", item.item_id or "unknown")
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    return path


def fetch_video_subtitle_to_inbox(url: str, *, creator: str = "", timeout: int = 120,
                                  langs: str = _LANG_PREF,
                                  cookies_from_browser: str = "",
                                  whisper_fallback: bool = False,
                                  whisper_model: str = "",
                                  whisper_language: str = "",
                                  quality: str = "balanced",
                                  force_download: bool = False) -> tuple[Path | None, str]:
    video_id = extract_video_id(url)
    if video_id and creator and not force_download:
        existing = subtitle_inbox_path(creator, video_id)
        if existing.exists():
            return existing, "skipped_existing"
    item, status = fetch_video_subtitle_item(
        url,
        creator=creator,
        timeout=timeout,
        langs=langs,
        cookies_from_browser=cookies_from_browser,
        whisper_fallback=whisper_fallback,
        whisper_model=whisper_model,
        whisper_language=whisper_language,
        quality=quality,
    )
    if not item:
        return None, status
    return write_subtitle_item_to_inbox(item), "ok"


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_recent_channel_subtitles_to_inbox(*, lookback_hours: int = 168,
                                            max_items_per_channel: int = 5,
                                            timeout_per_video: int = 120,
                                            langs: str = _LANG_PREF,
                                            cookies_from_browser: str = "",
                                            whisper_fallback: bool = False,
                                            whisper_model: str = "",
                                            whisper_language: str = "",
                                            quality: str = "balanced") -> tuple[int, int, list[str]]:
    """Fetch subtitles for recent videos from configured YouTube sources."""
    rss_items, errors = fetch_youtube_rss_items(max_items_per_channel=max_items_per_channel)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    fetched = 0
    skipped = 0
    seen: set[str] = set()
    for rss in rss_items:
        dt = _parse_dt(rss.published_at)
        if dt and dt < cutoff:
            continue
        key = rss.url or rss.item_id
        if not key or key in seen:
            continue
        seen.add(key)
        if rss.creator and rss.item_id:
            existing = subtitle_inbox_path(rss.creator, rss.item_id)
            if existing.exists():
                skipped += 1
                continue
        path, status = fetch_video_subtitle_to_inbox(
            rss.url,
            creator=rss.creator,
            timeout=timeout_per_video,
            langs=langs,
            cookies_from_browser=cookies_from_browser,
            whisper_fallback=whisper_fallback,
            whisper_model=whisper_model,
            whisper_language=whisper_language,
            quality=quality,
        )
        if path:
            if status == "skipped_existing":
                skipped += 1
            else:
                fetched += 1
        else:
            errors.append(f"{rss.creator}/{rss.item_id}: {status}")
    return fetched, skipped, errors
