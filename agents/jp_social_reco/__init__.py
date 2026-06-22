"""Japan stock social recommendation scanner.

Framework entry points:
    get_jp_social_signal_cached()
    get_jp_social_signal()
    get_jp_social_with_backtest()
    generate_jp_social_weekly_report()
    format_jp_social_banner() / format_jp_social_banner_enhanced()
"""
from .interface import (
    generate_jp_social_weekly_report,
    get_jp_social_signal,
    get_jp_social_signal_cached,
    get_jp_social_with_backtest,
    format_jp_social_banner,
    format_jp_social_banner_enhanced,
)

__all__ = [
    "generate_jp_social_weekly_report",
    "get_jp_social_signal",
    "get_jp_social_signal_cached",
    "get_jp_social_with_backtest",
    "format_jp_social_banner",
    "format_jp_social_banner_enhanced",
]
