from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:
    from config import SIGNALS_DIR
except Exception:
    SIGNALS_DIR = str(Path(__file__).resolve().parents[1] / "signals")


PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
INBOX_DIR = DATA_DIR / "inbox"
EXAMPLES_DIR = DATA_DIR / "examples"
SOURCE_CONFIG = PACKAGE_DIR / "sources.json"
SOURCE_CONFIG_EXAMPLE = PACKAGE_DIR / "sources.example.json"
SIGNAL_DIR = Path(SIGNALS_DIR) / "jp_social_reco"
CACHE_PATH = SIGNAL_DIR / "aggregate_latest.json"

CACHE_TTL_MIN = 30
DEFAULT_LOOKBACK_HOURS = 168
INTERFACE_VERSION = "jp_social_reco.v1"


# TSE Prime large/liquid starter universe. Extend sources.json for smaller names.
DEFAULT_JP_UNIVERSE = [
    {"code": "7203", "name": "トヨタ自動車", "aliases": ["トヨタ", "Toyota", "TOYOTA"]},
    {"code": "6758", "name": "ソニーG", "aliases": ["ソニー", "Sony", "SONY"]},
    {"code": "9984", "name": "ソフトバンクG", "aliases": ["ソフトバンクG", "SoftBank", "SBG"]},
    {"code": "8035", "name": "東京エレクトロン", "aliases": ["東エレク", "TEL", "Tokyo Electron"]},
    {"code": "6857", "name": "アドバンテスト", "aliases": ["Advantest"]},
    {"code": "8306", "name": "三菱UFJ", "aliases": ["MUFG", "三菱UFJFG"]},
    {"code": "9432", "name": "NTT", "aliases": ["日本電信電話"]},
    {"code": "7974", "name": "任天堂", "aliases": ["Nintendo"]},
    {"code": "6098", "name": "リクルートHD", "aliases": ["リクルート", "Recruit"]},
    {"code": "6861", "name": "キーエンス", "aliases": ["Keyence"]},
    {"code": "4502", "name": "武田薬品", "aliases": ["武田", "Takeda"]},
    {"code": "9433", "name": "KDDI", "aliases": []},
    {"code": "7267", "name": "ホンダ", "aliases": ["Honda", "本田技研"]},
    {"code": "8316", "name": "三井住友FG", "aliases": ["SMFG", "三井住友"]},
    {"code": "4063", "name": "信越化学", "aliases": ["信越", "Shin-Etsu"]},
    {"code": "6594", "name": "ニデック", "aliases": ["Nidec", "日本電産"]},
    {"code": "4519", "name": "中外製薬", "aliases": ["中外"]},
    {"code": "6981", "name": "村田製作所", "aliases": ["村田", "Murata"]},
    {"code": "4543", "name": "テルモ", "aliases": ["Terumo"]},
    {"code": "8058", "name": "三菱商事", "aliases": ["三菱商", "Mitsubishi Corp"]},
    {"code": "8031", "name": "三井物産", "aliases": ["Mitsui"]},
    {"code": "6273", "name": "SMC", "aliases": []},
    {"code": "7269", "name": "スズキ", "aliases": ["Suzuki"]},
    {"code": "8411", "name": "みずほFG", "aliases": ["みずほ"]},
    {"code": "9101", "name": "日本郵船", "aliases": ["郵船", "NYK"]},
    {"code": "8053", "name": "住友商事", "aliases": ["住商", "Sumitomo Corp"]},
    {"code": "4661", "name": "オリエンタルランド", "aliases": ["OLC", "Oriental Land"]},
    {"code": "9020", "name": "JR東日本", "aliases": ["東日本旅客鉄道"]},
    {"code": "8001", "name": "伊藤忠商事", "aliases": ["伊藤忠", "Itochu"]},
    {"code": "4568", "name": "第一三共", "aliases": ["Daiichi Sankyo"]},
]


@dataclass(frozen=True)
class SourceSettings:
    creator: str
    kind: str
    weight: float = 1.0
    enabled: bool = True
    url: str = ""
    note: str = ""


def ensure_dirs() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)


def load_source_config() -> dict:
    """Load sources.json if present; otherwise return a safe empty config."""
    ensure_dirs()
    if SOURCE_CONFIG.exists():
        try:
            return json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_universe() -> list[dict]:
    cfg = load_source_config()
    extra = cfg.get("jp_universe") or []
    by_code: dict[str, dict] = {row["code"]: dict(row) for row in DEFAULT_JP_UNIVERSE}
    for row in extra:
        code = str(row.get("code", "")).strip()
        if len(code) == 4 and code.isdigit():
            by_code[code] = {
                "code": code,
                "name": row.get("name") or code,
                "aliases": row.get("aliases") or [],
            }
    return list(by_code.values())


def load_creator_weights() -> dict[str, float]:
    cfg = load_source_config()
    weights: dict[str, float] = {}
    for src in cfg.get("sources", []):
        creator = str(src.get("creator", "")).strip()
        if not creator or src.get("enabled", True) is False:
            continue
        try:
            weights[creator] = float(src.get("weight", 1.0))
        except Exception:
            weights[creator] = 1.0
    return weights
