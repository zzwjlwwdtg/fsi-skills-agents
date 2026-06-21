"""创建 agents 目录快照 zip。排除大数据缓存目录。"""
from __future__ import annotations
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).parent.resolve()
PARENT = ROOT.parent
BACKUP_DIR = PARENT / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
ZIP_PATH = BACKUP_DIR / f"agents_backup_{STAMP}_with_AB.zip"

# 排除：大缓存 + 临时文件 + 日志
EXCLUDE_DIRS = {
    "__pycache__",
    "logs",
    "signals/news_cache",
    "signals/trump_cache",
    "_archive",
}
EXCLUDE_FILES_PREFIX = (
    "option_walls_",   # 期权墙每日缓存
    "backtest_",       # 回测大文件
    "evolved_rules_",  # 进化规则（每个 ~500KB）
    "signal_history",  # 信号历史
)
EXCLUDE_EXACT = {
    ".orchestrator.lock",
    ".snapshot_today.lock",
}


def should_skip(p: Path) -> bool:
    rel = p.relative_to(ROOT).as_posix()
    if any(part in EXCLUDE_DIRS for part in rel.split("/")):
        return True
    # signals 子目录里特定前缀
    if "signals/" in rel:
        name = p.name
        if any(name.startswith(pre) for pre in EXCLUDE_FILES_PREFIX):
            return True
    if p.name in EXCLUDE_EXACT:
        return True
    return False


def main():
    print(f"Source: {ROOT}")
    print(f"Output: {ZIP_PATH}")
    print()
    count, total_size = 0, 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in ROOT.rglob("*"):
            if not p.is_file() or should_skip(p):
                continue
            rel = p.relative_to(ROOT)
            zf.write(p, arcname=str(rel))
            count += 1
            total_size += p.stat().st_size
    print(f"  archived: {count} files")
    print(f"  uncompressed total: {total_size/(1024*1024):.1f} MB")
    print(f"  zip size: {ZIP_PATH.stat().st_size/(1024*1024):.1f} MB")
    print(f"[done] {ZIP_PATH}")


if __name__ == "__main__":
    main()
