"""
i18n — bilingual (zh / ja) string switch.

Design philosophy (in English so it survives any language migration):
  - Default language: zh (Chinese). This preserves existing run.bat behavior.
  - When OUTPUT_LANG=ja, all calls to t() resolve to the Japanese variant.
  - The Chinese string is the primary; the Japanese is optional fallback.
  - If only zh is given, both run.bat and run_ja.bat will see Chinese.

Usage:
  from i18n import t, is_ja, lang
  logger.info(t("信号", "シグナル"))
  logger.info(t(f"价格:{price}", f"価格:{price}"))

For dict-based labels (icons, regime names, reason mapping):
  from i18n import pick
  REGIME = pick({
      "bull_trending": ("牛市延续", "強気継続"),
      ...
  })  # returns a flat dict picked by current lang
"""

from __future__ import annotations

import os
from typing import Mapping, Tuple


_LANG = os.environ.get("OUTPUT_LANG", "").lower()


def lang() -> str:
    """Returns 'zh' (default) or 'ja'."""
    return "ja" if _LANG == "ja" else "zh"


def is_ja() -> bool:
    return _LANG == "ja"


def t(zh: str, ja: str = "") -> str:
    """Pick zh or ja string based on OUTPUT_LANG."""
    if _LANG == "ja" and ja:
        return ja
    return zh


def pick(mapping: Mapping[str, Tuple[str, str]]) -> dict[str, str]:
    """
    Flatten a {key: (zh, ja)} dict into {key: zh_or_ja}.
    """
    idx = 1 if _LANG == "ja" else 0
    return {k: v[idx] if v[idx] else v[0] for k, v in mapping.items()}
