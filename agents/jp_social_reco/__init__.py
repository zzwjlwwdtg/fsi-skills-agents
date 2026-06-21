"""Japan stock social recommendation scanner.

Framework entry points:
    get_jp_social_signal_cached()
    get_jp_social_signal()
    generate_jp_social_weekly_report()
    format_jp_social_banner()
"""
from .interface import (
    generate_jp_social_weekly_report,
    get_jp_social_signal,
    get_jp_social_signal_cached,
    format_jp_social_banner,
)

__all__ = [
    "generate_jp_social_weekly_report",
    "get_jp_social_signal",
    "get_jp_social_signal_cached",
    "format_jp_social_banner",
]
