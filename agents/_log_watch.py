"""
_log_watch.py
─────────────
独立日志监视窗口 — tail 当天的 run_YYYYMMDD.log。

特点：
  · 只读追加 follow，跟 orchestrator 完全解耦
  · 启动先回放最后 N 行（默认 30）
  · 跨午夜自动切到新文件 run_<明天>.log
  · 文件还没创建会等待（轮询）
  · 关掉窗口对 orchestrator 零影响

用法：
  watch.bat              # 默认 30 行 backlog
  set WATCH_TAIL=100 & watch.bat   # 启动看后 100 行
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
POLL_SEC = 0.5
WAIT_FILE_SEC = 5
INITIAL_LINES = int(os.environ.get("WATCH_TAIL", "30"))


def current_log_path() -> Path:
    return LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d')}.log"


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def print_initial_tail(path: Path, n: int) -> None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for line in lines[-n:]:
            sys.stdout.write(line)
        sys.stdout.flush()
    except Exception as exc:
        print(f"[watch] backlog 读取失败: {exc}")


def tail_until_rollover(path: Path) -> None:
    """跟随 path 直到当日变化（午夜），返回让上层切到新文件。"""
    f = open(path, encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    today = today_str()
    while True:
        line = f.readline()
        if line:
            sys.stdout.write(line)
            sys.stdout.flush()
            continue
        if today_str() != today:
            f.close()
            return
        time.sleep(POLL_SEC)


def main() -> int:
    print("=" * 68)
    print("  Orchestrator Log Watcher")
    print(f"  log dir : {LOG_DIR}")
    print(f"  policy  : 跟随当天 run_YYYYMMDD.log，午夜自动切换")
    print(f"  closing : Ctrl+C 或 X 都不影响 orchestrator")
    print("=" * 68)

    while True:
        path = current_log_path()
        # 文件可能还没创建（早于 orchestrator 第一次写入），轮询等待
        while not path.exists():
            print(f"[watch] {path.name} 还未生成，等待...")
            time.sleep(WAIT_FILE_SEC)
            new_path = current_log_path()
            if new_path != path:
                path = new_path  # 跨午夜了

        print()
        print(f"--- 跟随中: {path.name}  ({datetime.now():%Y-%m-%d %H:%M:%S}) ---")
        if INITIAL_LINES > 0:
            print_initial_tail(path, INITIAL_LINES)
            print("--- [tail begin] ---")

        try:
            tail_until_rollover(path)
        except KeyboardInterrupt:
            print("\n[watch] 已关闭（orchestrator 仍在跑）")
            return 0
        except Exception as exc:
            print(f"\n[watch] tail 异常: {exc}，3 秒后重连同一文件")
            time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
