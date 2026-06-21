"""
工具菜单 — 用 Python 替代 bat 菜单，避免 cmd.exe 在日文 Windows 上解析 UTF-8
bat 文件的编码问题。tools.bat 只做 ASCII 启动器。
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 确保子进程 stdout 也是 UTF-8
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent.resolve()
PY = sys.executable

# 默认 LIVE（在 moomoo SIMULATE 账户实际下单）；要 dry: set TRADER_DRY_RUN=1
os.environ.setdefault("TRADER_DRY_RUN", "0")


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def run(args: list[str]) -> None:
    """运行子命令，把输出原样接管。"""
    full = [PY, "-X", "utf8"] + args
    subprocess.run(full, cwd=SCRIPT_DIR)


def pause():
    input("\n按回车继续...")


def confirm(prompt: str) -> bool:
    ans = input(prompt + " (y/N): ").strip().lower()
    return ans == "y"


def cmd_status():    run(["paper_trader.py", "status"]);  pause()
def cmd_picks():     run(["paper_trader.py", "picks"]);   pause()
def cmd_regime():    run(["regime_today.py"]);            pause()
def cmd_pick():      run(["universe_picker.py"]);         pause()
def cmd_pca():       run(["pca_sox.py"]);                 pause()
def cmd_snapshot():  run(["_snapshot_today.py"]);          pause()
def cmd_trump():     run(["trump_signal.py", "--hours", "24"]); pause()
def cmd_backtest():  run(["backtest_menu.py"])  # 子菜单自己 pause


def cmd_flatten():
    print()
    print("*** 警告：会对账户里所有 LONG 持仓挂 SELL 限价单 (排队等开盘) ***")
    if not confirm("确认平仓？"):
        return
    run(["paper_trader.py", "flatten"])
    pause()


def cmd_reset():
    print()
    print("*** 警告：会删除 trader_state.json (账户实际持仓不变) ***")
    if not confirm("确认清空 state？"):
        return
    run(["paper_trader.py", "reset"])
    pause()


def cmd_logs():
    today = datetime.now().strftime("%Y%m%d")
    log = SCRIPT_DIR / "logs" / f"run_{today}.log"
    if log.exists():
        if os.name == "nt":
            os.startfile(str(log))
        else:
            subprocess.run(["xdg-open", str(log)])
    else:
        print(f"今日尚无 log：{log}")
        pause()


def cmd_moomoo_ai():
    """打开/创建今日 moomoo AI 手动输入文件，让用户从 moomoo app 复制粘贴 AI 回答。"""
    today = datetime.now().strftime("%Y-%m-%d")
    p = SCRIPT_DIR / "signals" / f"manual_moomoo_ai_{today}.txt"
    if not p.exists():
        p.parent.mkdir(exist_ok=True)
        p.write_text(
            "# 把 moomoo app 里 AI 助手的回答粘贴到这里\n"
            "# ai_prompt.py 会自动读取并附加到 Claude/Codex 提问稿\n"
            "# 没用的话留空文件即可\n\n",
            encoding="utf-8",
        )
    if os.name == "nt":
        os.startfile(str(p))
    else:
        subprocess.run(["xdg-open", str(p)])


MENU = [
    ("1", "trader status",       "模拟账户余额 + 持仓 + 未结订单",         cmd_status),
    ("2", "trader picks",        "今日卫星仓候选池 + 活跃 ticker",         cmd_picks),
    ("3", "trader flatten",      "平掉所有 LONG 持仓 (周一开盘用得上)",    cmd_flatten),
    ("4", "regime today",        "手动重算今日 regime + 显示",             cmd_regime),
    ("5", "snapshot today",      "一键今日全貌：regime+trump+信号+事件",   cmd_snapshot),
    ("6", "trump signal",        "Trump Truth Social 24h 信号（CLI 解析）", cmd_trump),
    ("7", "universe pick",       "手动跑一次选股 (不写文件)",              cmd_pick),
    ("8", "pca sox",             "手动跑 SOX 板块 PCA 报告",               cmd_pca),
    ("b", "backtest 菜单",       "改完代码必跑（regime/news/trump/engine）", cmd_backtest),
    ("r", "trader reset state",  "清空 trader_state.json (账户不动)",      cmd_reset),
    ("l", "show today log",      "记事本打开今日 log",                     cmd_logs),
    ("m", "moomoo AI 输入",      "粘贴 moomoo app 里 AI 回答给 Claude 复盘", cmd_moomoo_ai),
]


def main():
    while True:
        clear()
        dry = os.environ.get("TRADER_DRY_RUN", "1") == "1"
        mode = "[DRY-RUN]" if dry else "[LIVE]"
        print("=" * 62)
        print(f"  Trading Agents - 工具菜单  {mode}")
        print("=" * 62)
        print()
        print("  -- 账户 / 持仓 --")
        for k, label, desc, _ in MENU[:3]:
            print(f"   {k}.  {label:<22} {desc}")
        print()
        print("  -- 今日决策 / 数据 --")
        for k, label, desc, _ in MENU[3:8]:
            print(f"   {k}.  {label:<22} {desc}")
        print()
        print("  -- 回测 / 维护 / 外部 --")
        for k, label, desc, _ in MENU[8:]:
            print(f"   {k}.  {label:<22} {desc}")
        print()
        print("   q.  退出")
        print()
        choice = input("请选择 (字母/数字, q退出): ").strip().lower()
        if choice == "q":
            return
        for k, _, _, fn in MENU:
            if choice == k:
                try:
                    fn()
                except KeyboardInterrupt:
                    print("\n[已中断]")
                    pause()
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n再见")
